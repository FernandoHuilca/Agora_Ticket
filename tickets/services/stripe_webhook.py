import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from events.models import Event
from tickets.models import Payment, Reservation, StripeEvent, Ticket
from tickets.services.qr_signing import sign_ticket
from tickets.services.reservations import release_reservation


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefundRequest:
    payment_id: int
    payment_intent_id: str


class PayloadMismatch(Exception):
    """Raised when a verified checkout does not match its reservation."""


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _session_from_event(event):
    return _get(_get(event, 'data', {}), 'object', {})


def _reservation_id(session):
    metadata = _get(session, 'metadata', {}) or {}
    return metadata.get('reservation_id') or _get(session, 'client_reference_id')


def _payment_intent_id(session):
    payment_intent = _get(session, 'payment_intent')
    if isinstance(payment_intent, str):
        return payment_intent
    return _get(payment_intent, 'id')


def _paid_at(event_created):
    if event_created:
        return datetime.fromtimestamp(int(event_created), tz=timezone.get_current_timezone())
    return timezone.now()


def _amount_matches(session, reservation):
    amount_total = _get(session, 'amount_total')
    currency = _get(session, 'currency')
    if amount_total is None or currency is None:
        return False

    try:
        received_amount = int(amount_total)
        expected_amount = int(reservation.total_amount * 100)
    except (TypeError, ValueError):
        return False

    return (
        received_amount == expected_amount
        and str(currency).lower() == reservation.currency.lower()
    )


def _completed_payload_matches(event):
    session = _session_from_event(event)
    raw_reservation_id = _reservation_id(session)
    try:
        reservation_uuid = UUID(str(raw_reservation_id))
    except (TypeError, ValueError):
        logger.error(
            'Stripe event %s has an invalid reservation reference.',
            _get(event, 'id', ''),
        )
        return False

    reservation = Reservation.objects.filter(pk=reservation_uuid).first()
    if reservation is None:
        logger.error(
            'Stripe event %s references missing reservation %s.',
            _get(event, 'id', ''),
            raw_reservation_id,
        )
        return False

    amount_total = _get(session, 'amount_total')
    currency = _get(session, 'currency')
    if not _amount_matches(session, reservation):
        logger.error(
            'Stripe event %s reservation %s amount mismatch: '
            'expected %s %s, received %s %s.',
            _get(event, 'id', ''),
            reservation.id,
            int(reservation.total_amount * 100),
            reservation.currency.lower(),
            amount_total,
            str(currency).lower() if currency is not None else currency,
        )
        return False
    return True


def _activate_tickets(reservation, issued_at):
    for ticket in reservation.tickets.filter(status=Ticket.Status.PENDING):
        token = sign_ticket(ticket.id, reservation.event_id, reservation.user_id)
        Ticket.objects.filter(
            pk=ticket.pk,
            status=Ticket.Status.PENDING,
        ).update(
            status=Ticket.Status.ISSUED,
            issued_at=issued_at,
            qr_payload_hash=token.rsplit('.', 1)[1],
        )


def _create_paid_payment(reservation, payment_intent_id, amount, paid_at):
    payment, created = Payment.objects.get_or_create(
        reservation=reservation,
        defaults={
            'stripe_payment_intent_id': payment_intent_id,
            'amount': amount,
            'status': Payment.Status.PAID,
            'paid_at': paid_at,
        },
    )
    if not created and payment.status != Payment.Status.PAID:
        payment.stripe_payment_intent_id = payment_intent_id
        payment.amount = amount
        payment.status = Payment.Status.PAID
        payment.paid_at = paid_at
        payment.save(update_fields=[
            'stripe_payment_intent_id',
            'amount',
            'status',
            'paid_at',
        ])
    return payment


def _handle_completed(event):
    session = _session_from_event(event)
    event_id = _get(event, 'id', '')
    if _get(session, 'payment_status') != 'paid':
        logger.info('Stripe event %s ignored: payment is not paid.', event_id)
        return None

    raw_reservation_id = _reservation_id(session)
    try:
        reservation_uuid = UUID(str(raw_reservation_id))
    except (TypeError, ValueError):
        logger.warning('Stripe event %s has no valid reservation reference.', event_id)
        return None

    payment_intent_id = _payment_intent_id(session)
    if not payment_intent_id:
        logger.warning('Stripe event %s has no payment intent.', event_id)
        return None

    refund_request = None
    with transaction.atomic():
        try:
            reservation = Reservation.objects.select_for_update().get(
                pk=reservation_uuid
            )
        except Reservation.DoesNotExist:
            logger.warning('Stripe event %s references no reservation.', event_id)
            return None

        if not _amount_matches(session, reservation):
            logger.error(
                'Stripe event %s reservation %s amount mismatch: '
                'expected %s %s, received %s %s.',
                event_id,
                reservation.id,
                int(reservation.total_amount * 100),
                reservation.currency.lower(),
                _get(session, 'amount_total'),
                str(_get(session, 'currency')).lower(),
            )
            raise PayloadMismatch

        amount = reservation.total_amount
        paid_at = _paid_at(_get(event, 'created'))

        if reservation.status == Reservation.Status.PAID:
            return None

        if reservation.status == Reservation.Status.PENDING:
            reservation.status = Reservation.Status.PAID
            reservation.save(update_fields=['status'])
            _create_paid_payment(
                reservation,
                str(payment_intent_id),
                amount,
                paid_at,
            )
            _activate_tickets(reservation, paid_at)
            return None

        if reservation.status != Reservation.Status.EXPIRED:
            logger.info(
                'Stripe event %s ignored: reservation is not payable.',
                event_id,
            )
            return None

        ticket_count = reservation.tickets.filter(
            status=Ticket.Status.CANCELLED,
        ).count()
        recovered = Event.objects.filter(
            pk=reservation.event_id,
            available_tickets__gte=ticket_count,
        ).update(
            available_tickets=F('available_tickets') - ticket_count,
        )
        if recovered == 1:
            reservation.status = Reservation.Status.PAID
            reservation.save(update_fields=['status'])
            Ticket.objects.filter(
                reservation=reservation,
                status=Ticket.Status.CANCELLED,
            ).update(status=Ticket.Status.PENDING)
            _create_paid_payment(
                reservation,
                str(payment_intent_id),
                amount,
                paid_at,
            )
            _activate_tickets(reservation, paid_at)
        else:
            payment, created = Payment.objects.get_or_create(
                reservation=reservation,
                defaults={
                    'stripe_payment_intent_id': str(payment_intent_id),
                    'amount': amount,
                    'status': Payment.Status.PENDING,
                },
            )
            if not created and payment.status != Payment.Status.REFUNDED:
                payment.stripe_payment_intent_id = str(payment_intent_id)
                payment.amount = amount
                payment.status = Payment.Status.PENDING
                payment.save(update_fields=[
                    'stripe_payment_intent_id',
                    'amount',
                    'status',
                ])
            refund_request = RefundRequest(
                payment_id=payment.pk,
                payment_intent_id=str(payment_intent_id),
            )

    if refund_request is not None:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            stripe.Refund.create(
                payment_intent=refund_request.payment_intent_id,
            )
        except stripe.StripeError:
            logger.exception(
                'Stripe refund failed for payment %s.',
                refund_request.payment_id,
            )
            raise
        Payment.objects.filter(pk=refund_request.payment_id).update(
            status=Payment.Status.REFUNDED,
        )
    return None


def _handle_expired(event):
    session = _session_from_event(event)
    raw_reservation_id = _reservation_id(session)
    try:
        reservation_uuid = UUID(str(raw_reservation_id))
    except (TypeError, ValueError):
        logger.warning(
            'Stripe expiration event %s has no valid reservation reference.',
            _get(event, 'id', ''),
        )
        return

    reservation = Reservation.objects.filter(pk=reservation_uuid).first()
    if reservation is not None:
        release_reservation(reservation)


def process_stripe_event(event):
    """Process one verified Stripe event and return after idempotent handling."""
    event_id = _get(event, 'id')
    event_type = _get(event, 'type')
    if not event_id or not event_type:
        raise ValueError('Stripe event requires id and type.')

    try:
        with transaction.atomic():
            if StripeEvent.objects.filter(event_id=str(event_id)).exists():
                return
            if (
                event_type == 'checkout.session.completed'
                and not _completed_payload_matches(event)
            ):
                # A verified but inconsistent checkout is terminal input; return
                # 200 without recording it so a corrected retry can be processed.
                return
            StripeEvent.objects.create(
                event_id=str(event_id),
                type=str(event_type),
            )

        if event_type == 'checkout.session.completed':
            _handle_completed(event)
        elif event_type == 'checkout.session.expired':
            _handle_expired(event)
    except PayloadMismatch:
        with transaction.atomic():
            StripeEvent.objects.filter(event_id=str(event_id)).delete()
        return
    except Exception:
        with transaction.atomic():
            StripeEvent.objects.filter(event_id=str(event_id)).delete()
        raise

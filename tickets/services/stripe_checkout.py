from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import stripe
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from tickets.services.reservations import release_reservation


class CheckoutError(RuntimeError):
    """Raised when Stripe cannot create a checkout session."""


def create_checkout_session(reservation) -> str:
    if reservation.total_amount <= Decimal('0.00'):
        raise CheckoutError('Solo las reservas de pago pueden usar Stripe.')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    now = timezone.now()
    minimum_expiry = int(now.timestamp()) + int(timedelta(minutes=30).total_seconds())
    expires_at = max(int(reservation.expires_at.timestamp()), minimum_expiry)
    tickets = list(reservation.tickets.all())
    quantity = len(tickets)
    if not quantity:
        raise CheckoutError('La reserva no contiene tickets.')

    unit_amount = int(
        (tickets[0].unit_price * 100).quantize(
            Decimal('1'),
            rounding=ROUND_HALF_UP,
        )
    )
    expected_total = unit_amount * quantity
    reservation_total = int(
        (reservation.total_amount * 100).quantize(
            Decimal('1'),
            rounding=ROUND_HALF_UP,
        )
    )
    if expected_total != reservation_total or any(
        ticket.unit_price != tickets[0].unit_price for ticket in tickets
    ):
        raise CheckoutError('El total de la reserva no es válido.')

    try:
        session = stripe.checkout.Session.create(
            mode='payment',
            client_reference_id=str(reservation.id),
            metadata={'reservation_id': str(reservation.id)},
            expires_at=expires_at,
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'Tickets - {reservation.event.name}',
                    },
                    'unit_amount': unit_amount,
                },
                'quantity': quantity,
            }],
            success_url=(
                f'{settings.SITE_URL}{reverse("tickets:ok")}'
                '?session_id={CHECKOUT_SESSION_ID}'
            ),
            cancel_url=f'{settings.SITE_URL}{reverse("tickets:cancel")}',
        )
    except stripe.StripeError as exc:
        release_reservation(reservation)
        raise CheckoutError('No se pudo crear la sesión de pago.') from exc

    session_url = getattr(session, 'url', None)
    session_id = getattr(session, 'id', None)
    if not session_url or not session_id:
        release_reservation(reservation)
        raise CheckoutError('Stripe devolvió una sesión incompleta.')

    reservation.stripe_checkout_session_id = session_id
    reservation.save(update_fields=['stripe_checkout_session_id'])
    return session_url

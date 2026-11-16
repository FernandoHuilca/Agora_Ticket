from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from events.models import Event
from tickets.models import Reservation, Ticket
from tickets.services.qr_signing import sign_ticket


LOCAL_TIMEZONE = ZoneInfo('America/Guayaquil')


class SoldOut(Exception):
    """Raised when an event has insufficient available capacity."""


class EventNotAvailable(Exception):
    """Raised when an event cannot accept new reservations."""


class AgeRestricted(Exception):
    """Raised when the buyer does not satisfy an event's age restriction."""


class PerUserLimitExceeded(Exception):
    """Raised when a free event's per-user ticket limit is exceeded."""


def _age_on_date(date_of_birth, today):
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def _issue_free_ticket(ticket, reservation, now):
    token = sign_ticket(ticket.id, reservation.event_id, reservation.user_id)
    ticket.status = Ticket.Status.ISSUED
    ticket.issued_at = now
    ticket.qr_payload_hash = token.rsplit('.', 1)[1]
    ticket.save(update_fields=['status', 'issued_at', 'qr_payload_hash'])


@transaction.atomic
def create_reservation(user, event, attendees: list[dict]) -> Reservation:
    now = timezone.now()
    event = Event.objects.get(pk=event.pk)

    if event.status != Event.Status.PUBLISHED or event.end_date <= now:
        raise EventNotAvailable

    quantity = len(attendees)
    if quantity <= 0:
        raise ValueError('Debe reservar al menos un ticket.')

    if event.is_adult_only:
        today = now.astimezone(LOCAL_TIMEZONE).date()
        if not user.date_of_birth or _age_on_date(user.date_of_birth, today) < 18:
            raise AgeRestricted

    if event.is_free:
        existing_count = Ticket.objects.filter(
            reservation__user=user,
            event=event,
            status__in=[Ticket.Status.PENDING, Ticket.Status.ISSUED],
        ).count()
        if existing_count + quantity > event.max_tickets_per_user:
            raise PerUserLimitExceeded

    updated = Event.objects.filter(
        pk=event.pk,
        status=Event.Status.PUBLISHED,
        end_date__gt=now,
        available_tickets__gte=quantity,
    ).update(available_tickets=F('available_tickets') - quantity)
    if updated != 1:
        raise SoldOut

    total_amount = (
        Decimal('0.00') if event.is_free else event.price * quantity
    )
    reservation = Reservation.objects.create(
        user=user,
        event=event,
        status=(
            Reservation.Status.PAID
            if event.is_free
            else Reservation.Status.PENDING
        ),
        total_amount=total_amount,
        currency='usd',
        expires_at=now + timedelta(minutes=settings.RESERVATION_HOLD_MINUTES),
    )

    for attendee in attendees:
        attendee_name = str(attendee.get('attendee_name', '')).strip()
        if not attendee_name:
            raise ValueError('Cada asistente debe tener un nombre.')

        ticket = Ticket.objects.create(
            reservation=reservation,
            event=event,
            attendee_name=attendee_name,
            attendee_email=(attendee.get('attendee_email') or '').strip(),
            status=(
                Ticket.Status.ISSUED
                if event.is_free
                else Ticket.Status.PENDING
            ),
            unit_price=event.price,
            issued_at=now if event.is_free else None,
        )
        if event.is_free:
            _issue_free_ticket(ticket, reservation, now)

    return reservation


@transaction.atomic
def release_reservation(reservation) -> bool:
    released = Reservation.objects.filter(
        pk=reservation.pk,
        status=Reservation.Status.PENDING,
    ).update(status=Reservation.Status.EXPIRED)
    if released != 1:
        return False

    released_tickets = Ticket.objects.filter(
        reservation_id=reservation.pk,
        status=Ticket.Status.PENDING,
    ).update(status=Ticket.Status.CANCELLED)
    if released_tickets:
        Event.objects.filter(pk=reservation.event_id).update(
            available_tickets=F('available_tickets') + released_tickets,
        )
    return True

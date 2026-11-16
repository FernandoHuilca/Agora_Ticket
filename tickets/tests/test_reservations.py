from datetime import timedelta
from decimal import Decimal
from io import StringIO


from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from tickets.models import Reservation, Ticket
from tickets.services.qr_signing import parse_token, sign_ticket, verify_signature
from tickets.services.reservations import (
    AgeRestricted,
    EventNotAvailable,
    PerUserLimitExceeded,
    SoldOut,
    create_reservation,
    release_reservation,
)
from users.models import User


class ReservationServiceTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='test-password',
        )
        self.event = Event.objects.create(
            organizer=self.user,
            name='Evento de prueba',
            description='Descripción suficientemente larga para pruebas.',
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=4),
            location='Sala principal',
            capacity=3,
            available_tickets=3,
            is_free=True,
            price=Decimal('0.00'),
        )

    def attendees(self, count=1):
        return [
            {
                'attendee_name': f'Asistente {index}',
                'attendee_email': f'attendee{index}@example.com',
            }
            for index in range(count)
        ]

    def test_valid_reservation_creates_tickets_and_reduces_capacity(self):
        reservation = create_reservation(self.user, self.event, self.attendees(2))

        self.assertEqual(reservation.status, Reservation.Status.PAID)
        self.assertEqual(reservation.tickets.count(), 2)
        self.assertEqual(
            Event.objects.get(pk=self.event.pk).available_tickets,
            1,
        )
        self.assertTrue(
            reservation.tickets.filter(status=Ticket.Status.ISSUED).exists()
        )

    def test_no_capacity_creates_nothing(self):
        self.event.available_tickets = 0
        self.event.save(update_fields=['available_tickets'])

        with self.assertRaises(SoldOut):
            create_reservation(self.user, self.event, self.attendees())

        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_draft_and_cancelled_events_are_rejected(self):
        for status in (Event.Status.DRAFT, Event.Status.CANCELLED):
            with self.subTest(status=status):
                self.event.status = status
                self.event.save(update_fields=['status'])
                with self.assertRaises(EventNotAvailable):
                    create_reservation(self.user, self.event, self.attendees())

    def test_finished_event_is_rejected(self):
        now = timezone.now()
        Event.objects.filter(pk=self.event.pk).update(
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(days=1),
        )
        self.event.refresh_from_db()

        with self.assertRaises(EventNotAvailable):
            create_reservation(self.user, self.event, [{'attendee_name': 'Ana'}])

    def test_adult_event_requires_adult_buyer(self):
        self.event.is_adult_only = True
        self.event.save(update_fields=['is_adult_only'])

        with self.assertRaises(AgeRestricted):
            create_reservation(self.user, self.event, self.attendees())

        self.user.date_of_birth = timezone.localdate() - timedelta(days=17 * 365)
        self.user.save(update_fields=['date_of_birth'])
        with self.assertRaises(AgeRestricted):
            create_reservation(self.user, self.event, self.attendees())

    def test_free_event_applies_per_user_limit(self):
        self.event.max_tickets_per_user = 2
        self.event.save(update_fields=['max_tickets_per_user'])

        create_reservation(self.user, self.event, self.attendees(2))
        with self.assertRaises(PerUserLimitExceeded):
            create_reservation(self.user, self.event, self.attendees())

    def test_paid_event_does_not_apply_free_event_limit(self):
        self.event.is_free = False
        self.event.price = Decimal('10.00')
        self.event.capacity = 5
        self.event.available_tickets = 5
        self.event.max_tickets_per_user = 1
        self.event.save()

        reservation = create_reservation(self.user, self.event, self.attendees(2))

        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.tickets.count(), 2)

    def test_free_event_emits_signed_tickets(self):
        reservation = create_reservation(self.user, self.event, self.attendees())
        ticket = reservation.tickets.get()
        token = sign_ticket(ticket.id, self.event.id, self.user.id)
        parsed = parse_token(token)

        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNotNone(ticket.issued_at)
        self.assertEqual(ticket.qr_payload_hash, parsed.mac)
        self.assertTrue(verify_signature(parsed))

    def test_release_is_idempotent_and_restores_capacity_once(self):
        self.event.is_free = False
        self.event.price = Decimal('10.00')
        self.event.save()
        reservation = create_reservation(self.user, self.event, self.attendees(2))

        self.assertTrue(release_reservation(reservation))
        self.assertFalse(release_reservation(reservation))
        reservation.refresh_from_db()

        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(
            Event.objects.get(pk=self.event.pk).available_tickets,
            self.event.capacity,
        )
        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.CANCELLED).count(),
            2,
        )

    def test_expire_command_releases_expired_reservations(self):
        self.event.is_free = False
        self.event.price = Decimal('10.00')
        self.event.save()
        reservation = create_reservation(self.user, self.event, self.attendees())
        Reservation.objects.filter(pk=reservation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        output = StringIO()
        call_command('expire_reservations', stdout=output)
        reservation.refresh_from_db()

        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)
        self.assertIn('Reservas liberadas: 1', output.getvalue())

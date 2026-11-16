from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tickets.models import Ticket
from tickets.services.reservations import create_reservation
from users.models import User


class TicketViewsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner@example.com',
            password='test-password',
        )
        self.other = User.objects.create_user(
            email='other@example.com',
            password='test-password',
        )
        self.organizer = User.objects.create_user(
            email='organizer@example.com',
            password='test-password',
            role=User.Role.ORGANIZER,
        )
        self.other_organizer = User.objects.create_user(
            email='other-organizer@example.com',
            password='test-password',
            role=User.Role.ORGANIZER,
        )
        self.event = self._event(self.organizer, 'Evento propio')
        self.other_event = self._event(self.other_organizer, 'Otro evento')
        self.reservation = create_reservation(
            self.owner,
            self.event,
            [{'attendee_name': 'Asistente', 'attendee_email': ''}],
        )
        self.ticket = self.reservation.tickets.get()

    def _event(self, organizer, name):
        now = timezone.now()
        return Event.objects.create(
            organizer=organizer,
            name=name,
            description='Descripción suficientemente larga para pruebas.',
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=4),
            location='Sala principal',
            capacity=5,
            available_tickets=5,
            is_free=False,
            price=Decimal('12.50'),
        )

    def test_user_cannot_view_or_download_another_users_ticket(self):
        self.client.force_login(self.other)

        detail = self.client.get(
            reverse('tickets:tk', kwargs={'pk': self.ticket.pk}),
        )
        qr = self.client.get(
            reverse('tickets:qr', kwargs={'pk': self.ticket.pk}),
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(qr.status_code, 404)

    def test_qr_is_only_available_for_issued_ticket(self):
        self.client.force_login(self.owner)

        pending = self.client.get(
            reverse('tickets:qr', kwargs={'pk': self.ticket.pk}),
        )
        self.ticket.status = Ticket.Status.ISSUED
        self.ticket.save(update_fields=['status'])
        issued = self.client.get(
            reverse('tickets:qr', kwargs={'pk': self.ticket.pk}),
        )

        self.assertEqual(pending.status_code, 404)
        self.assertEqual(issued.status_code, 200)
        self.assertEqual(issued['Content-Type'], 'image/png')
        self.assertEqual(issued['Cache-Control'], 'private, no-store')

    def test_ok_does_not_change_reservation_state(self):
        self.reservation.stripe_checkout_session_id = 'cs_test_f6'
        self.reservation.save(update_fields=['stripe_checkout_session_id'])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('tickets:ok'),
            {'session_id': 'cs_test_f6'},
        )

        self.assertEqual(response.status_code, 200)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'PENDING')

    def test_organizer_of_another_event_gets_404(self):
        self.client.force_login(self.other_organizer)

        response = self.client.get(
            reverse('tickets:tk', kwargs={'pk': self.ticket.pk}),
        )

        self.assertEqual(response.status_code, 404)

    def test_reservation_status_only_returns_own_reservation(self):
        self.reservation.stripe_checkout_session_id = 'cs_test_status'
        self.reservation.save(update_fields=['stripe_checkout_session_id'])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('tickets:reservation_status'),
            {'session_id': 'cs_test_status'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'PENDING'})

        self.client.force_login(self.other)
        forbidden = self.client.get(
            reverse('tickets:reservation_status'),
            {'session_id': 'cs_test_status'},
        )
        self.assertEqual(forbidden.status_code, 404)

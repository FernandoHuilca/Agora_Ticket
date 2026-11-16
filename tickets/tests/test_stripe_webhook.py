from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tickets.models import Payment, Reservation, StripeEvent, Ticket
from tickets.services.reservations import create_reservation, release_reservation
from tickets.services.stripe_webhook import process_stripe_event
from users.models import User


class StripeWebhookTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='test-password',
        )
        self.event = Event.objects.create(
            organizer=self.user,
            name='Evento de webhook',
            description='Descripción suficientemente larga para pruebas.',
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=4),
            location='Sala principal',
            capacity=3,
            available_tickets=3,
            is_free=False,
            price=Decimal('12.50'),
        )

    def _reservation(self, count=1):
        return create_reservation(
            self.user,
            self.event,
            [
                {'attendee_name': f'Persona {index}', 'attendee_email': ''}
                for index in range(count)
            ],
        )

    def _event(self, reservation, event_id='evt_test_1', **session_values):
        session = {
            'payment_status': 'paid',
            'amount_total': int(reservation.total_amount * 100),
            'currency': reservation.currency.lower(),
            'payment_intent': 'pi_test_1',
            'client_reference_id': str(reservation.id),
            'metadata': {'reservation_id': str(reservation.id)},
        }
        session.update(session_values)
        return {
            'id': event_id,
            'type': 'checkout.session.completed',
            'created': int(timezone.now().timestamp()),
            'data': {'object': session},
        }

    def test_duplicate_event_issues_one_set_and_one_payment(self):
        reservation = self._reservation(2)
        event = self._event(reservation)

        process_stripe_event(event)
        process_stripe_event(event)

        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.ISSUED).count(),
            2,
        )
        self.assertEqual(Payment.objects.filter(reservation=reservation).count(), 1)
        self.assertEqual(StripeEvent.objects.filter(event_id='evt_test_1').count(), 1)

    def test_amount_mismatch_does_not_activate(self):
        reservation = self._reservation()

        process_stripe_event(self._event(reservation, amount_total=999))

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertFalse(reservation.tickets.filter(status=Ticket.Status.ISSUED).exists())
        self.assertFalse(Payment.objects.filter(reservation=reservation).exists())

    def test_amount_mismatch_changes_nothing(self):
        reservation = self._reservation()
        event_id = 'evt_amount_mismatch'

        with self.assertLogs(
            'tickets.services.stripe_webhook',
            level='ERROR',
        ) as logs:
            process_stripe_event(
                self._event(
                    reservation,
                    event_id=event_id,
                    amount_total=int(reservation.total_amount * 100) + 1,
                )
            )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.PENDING).count(),
            1,
        )
        self.assertFalse(Payment.objects.filter(reservation=reservation).exists())
        self.assertFalse(StripeEvent.objects.filter(event_id=event_id).exists())
        self.assertTrue(any(event_id in message for message in logs.output))

        process_stripe_event(self._event(reservation, event_id=event_id))

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PAID)
        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.ISSUED).count(),
            1,
        )
        self.assertEqual(Payment.objects.filter(reservation=reservation).count(), 1)

    def test_unpaid_session_does_not_activate(self):
        reservation = self._reservation()

        process_stripe_event(
            self._event(reservation, payment_status='unpaid')
        )

        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.PENDING).count(),
            1,
        )
        self.assertFalse(Payment.objects.filter(reservation=reservation).exists())

    def test_expired_event_releases_capacity(self):
        reservation = self._reservation()
        event = self._event(reservation, event_id='evt_expired')
        event['type'] = 'checkout.session.expired'

        process_stripe_event(event)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(
            Event.objects.get(pk=self.event.pk).available_tickets,
            self.event.capacity,
        )

    def test_late_payment_recovers_capacity_and_issues(self):
        reservation = self._reservation()
        release_reservation(reservation)

        process_stripe_event(self._event(reservation, event_id='evt_late'))

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PAID)
        self.assertEqual(
            reservation.tickets.filter(status=Ticket.Status.ISSUED).count(),
            1,
        )
        self.assertEqual(
            Payment.objects.get(reservation=reservation).status,
            Payment.Status.PAID,
        )

    @patch('tickets.services.stripe_webhook.stripe.Refund.create')
    def test_late_payment_without_capacity_is_refunded(self, refund):
        reservation = self._reservation()
        release_reservation(reservation)
        Event.objects.filter(pk=self.event.pk).update(available_tickets=0)

        process_stripe_event(self._event(reservation, event_id='evt_refund'))

        payment = Payment.objects.get(reservation=reservation)
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertFalse(reservation.tickets.filter(status=Ticket.Status.ISSUED).exists())
        refund.assert_called_once_with(payment_intent='pi_test_1')

    @patch('tickets.views.stripe.Webhook.construct_event')
    def test_invalid_signature_returns_400(self, construct_event):
        construct_event.side_effect = ValueError('invalid signature')

        response = self.client.post(
            reverse('tickets:stripe_webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad',
        )

        self.assertEqual(response.status_code, 400)

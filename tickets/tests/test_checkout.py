from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tickets.models import Reservation
from tickets.services.reservations import create_reservation
from tickets.services.stripe_checkout import CheckoutError, create_checkout_session
from users.models import User


class CheckoutTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='test-password',
        )
        self.event = Event.objects.create(
            organizer=self.user,
            name='Evento de checkout',
            description='Descripción suficientemente larga para pruebas.',
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=4),
            location='Sala principal',
            capacity=5,
            available_tickets=5,
            is_free=False,
            price=Decimal('12.50'),
        )

    def _attendees(self, count=1):
        return [
            {'attendee_name': f'Persona {index}', 'attendee_email': ''}
            for index in range(count)
        ]

    def _formset_data(self, count, names=None):
        names = names or [f'Persona {index}' for index in range(count)]
        data = {
            'form-TOTAL_FORMS': str(count),
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '10',
        }
        for index, name in enumerate(names):
            data[f'form-{index}-attendee_name'] = name
            data[f'form-{index}-attendee_email'] = ''
        return data

    @patch('tickets.services.stripe_checkout.stripe.checkout.Session.create')
    def test_checkout_stores_pending_reservation_and_session_id(self, create):
        create.return_value = SimpleNamespace(
            id='cs_test_123',
            url='https://checkout.stripe.test/session',
        )
        reservation = create_reservation(
            self.user,
            self.event,
            self._attendees(3),
        )

        url = create_checkout_session(reservation)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.stripe_checkout_session_id, 'cs_test_123')
        self.assertEqual(url, 'https://checkout.stripe.test/session')
        self.assertEqual(create.call_args.kwargs['line_items'][0]['price_data']['unit_amount'], 1250)
        self.assertEqual(create.call_args.kwargs['line_items'][0]['quantity'], 3)

    @patch('tickets.services.stripe_checkout.stripe.checkout.Session.create')
    def test_stripe_failure_releases_capacity(self, create):
        create.side_effect = stripe.StripeError('failure')
        reservation = create_reservation(
            self.user,
            self.event,
            self._attendees(),
        )

        with self.assertRaises(CheckoutError):
            create_checkout_session(reservation)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)
        self.assertEqual(
            Event.objects.get(pk=self.event.pk).available_tickets,
            self.event.capacity,
        )

    @patch('tickets.views.create_checkout_session')
    @patch('tickets.views.create_reservation')
    def test_pay_ignores_client_price(self, create_reservation_mock, checkout_mock):
        reservation = Reservation(
            id='00000000-0000-0000-0000-000000000001',
            user=self.user,
            event=self.event,
            status=Reservation.Status.PENDING,
            total_amount=Decimal('12.50'),
            currency='usd',
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        create_reservation_mock.return_value = reservation
        checkout_mock.return_value = 'https://checkout.stripe.test/session'
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': self.event.id}),
            dict(self._formset_data(1), total='0.01'),
        )

        self.assertEqual(response.status_code, 303)
        self.assertNotIn('price', create_reservation_mock.call_args.kwargs)
        checkout_mock.assert_called_once_with(reservation)

    @patch('tickets.views.create_checkout_session')
    def test_pay_three_attendees_creates_three_pending_tickets(self, checkout_mock):
        checkout_mock.return_value = 'https://checkout.stripe.test/session'
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': self.event.id}),
            dict(self._formset_data(3), total='0.01'),
        )

        reservation = Reservation.objects.get(user=self.user, event=self.event)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(reservation.tickets.count(), 3)
        self.assertEqual(reservation.total_amount, Decimal('37.50'))
        self.assertTrue(
            reservation.tickets.filter(status='PENDING').count() == 3
        )

    def test_formset_rejects_zero_attendees_and_blank_name(self):
        self.client.force_login(self.user)

        empty_response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': self.event.id}),
            self._formset_data(0),
        )
        blank_response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': self.event.id}),
            self._formset_data(1, names=['']),
        )

        self.assertEqual(empty_response.status_code, 400)
        self.assertEqual(blank_response.status_code, 400)
        self.assertFalse(Reservation.objects.filter(user=self.user).exists())

    def test_formset_rejects_more_than_available_capacity(self):
        Event.objects.filter(pk=self.event.pk).update(available_tickets=2)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': self.event.id}),
            self._formset_data(3),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reservation.objects.filter(user=self.user).exists())

    def test_free_event_allows_only_remaining_per_user_limit(self):
        free_event = Event.objects.create(
            organizer=self.user,
            name='Evento gratuito checkout',
            description='Descripción suficientemente larga para pruebas.',
            start_date=timezone.now() + timedelta(hours=2),
            end_date=timezone.now() + timedelta(hours=4),
            location='Sala gratuita',
            capacity=10,
            available_tickets=10,
            is_free=True,
            price=Decimal('0.00'),
            max_tickets_per_user=4,
        )
        create_reservation(self.user, free_event, self._attendees(3))
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('tickets:pay', kwargs={'event_id': free_event.id}),
            self._formset_data(2),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            free_event.tickets.filter(reservation__user=self.user).count(),
            3,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(
            reverse('tickets:pay', kwargs={'event_id': self.event.id})
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

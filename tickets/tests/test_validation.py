import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tickets.models import EventScanner, Ticket, TicketValidation
from tickets.services.qr_signing import sign_ticket
from tickets.services.reservations import create_reservation
from users.models import User


class TicketValidationTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email='organizer-validation@example.com',
            password='test-password',
            role=User.Role.ORGANIZER,
        )
        self.owner = User.objects.create_user(
            email='owner-validation@example.com',
            password='test-password',
        )
        self.scanner = User.objects.create_user(
            email='scanner-validation@example.com',
            password='test-password',
            role=User.Role.SCANNER,
        )
        self.other_scanner = User.objects.create_user(
            email='other-scanner-validation@example.com',
            password='test-password',
            role=User.Role.SCANNER,
        )
        self.admin = User.objects.create_user(
            email='admin-validation@example.com',
            password='test-password',
            role=User.Role.ADMIN,
        )
        self.event = self._event('Evento de validación')
        self.other_event = self._event('Otro evento de validación')
        EventScanner.objects.create(event=self.event, scanner=self.scanner)
        reservation = create_reservation(
            self.owner,
            self.event,
            [{'attendee_name': 'Asistente', 'attendee_email': ''}],
        )
        self.ticket = reservation.tickets.get()
        self.token = sign_ticket(
            self.ticket.id,
            self.ticket.event_id,
            self.owner.id,
        )

    def _event(self, name):
        now = timezone.now()
        return Event.objects.create(
            organizer=self.organizer,
            name=name,
            description='Descripción suficientemente larga para pruebas.',
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=4),
            location='Sala de validación',
            capacity=10,
            available_tickets=10,
            is_free=True,
            price=Decimal('0.00'),
        )

    def _post(self, user, token, expected_event_id=None):
        self.client.force_login(user)
        payload = {'token': token}
        if expected_event_id is not None:
            payload['expected_event_id'] = str(expected_event_id)
        return self.client.post(
            reverse('tickets:validate'),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_malformed_token_returns_400_and_is_audited(self):
        response = self._post(self.scanner, '')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['result'], 'MALFORMED')
        self.assertTrue(
            TicketValidation.objects.filter(
                scanner=self.scanner,
                result=TicketValidation.Result.MALFORMED,
            ).exists()
        )

    def test_tampered_token_returns_422_and_is_audited(self):
        tampered = self.token[:-1] + ('A' if self.token[-1] != 'A' else 'B')

        response = self._post(self.scanner, tampered)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['result'], 'TAMPERED')
        self.assertTrue(
            TicketValidation.objects.filter(
                scanner=self.scanner,
                result=TicketValidation.Result.TAMPERED,
            ).exists()
        )

    def test_not_found_returns_404_and_is_audited(self):
        token = sign_ticket(uuid.uuid4(), self.event.id, self.owner.id)

        response = self._post(self.scanner, token)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['result'], 'NOT_FOUND')
        self.assertTrue(
            TicketValidation.objects.filter(
                scanner=self.scanner,
                result=TicketValidation.Result.NOT_FOUND,
            ).exists()
        )

    def test_unassigned_scanner_returns_403(self):
        response = self._post(self.other_scanner, self.token)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['result'], 'NOT_AUTHORIZED')

    def test_wrong_event_returns_409(self):
        response = self._post(
            self.scanner,
            self.token,
            expected_event_id=self.other_event.id,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['result'], 'WRONG_EVENT')

    def test_payload_event_mismatch_returns_422(self):
        token = sign_ticket(self.ticket.id, self.other_event.id, self.owner.id)

        response = self._post(self.scanner, token)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['result'], 'TAMPERED')

    def test_cancelled_ticket_returns_409(self):
        self.ticket.status = Ticket.Status.CANCELLED
        self.ticket.save(update_fields=['status'])

        response = self._post(self.scanner, self.token)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['result'], 'CANCELLED')

    def test_admin_can_validate_without_assignment(self):
        response = self._post(self.admin, self.token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], 'VALID')

    def test_valid_then_already_used_are_audited(self):
        first = self._post(self.scanner, self.token)
        second = self._post(self.scanner, self.token)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['result'], 'VALID')
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()['result'], 'ALREADY_USED')
        self.assertEqual(
            TicketValidation.objects.filter(ticket=self.ticket).count(),
            2,
        )

    def test_audit_stores_fingerprint_instead_of_token(self):
        response = self._post(self.scanner, self.token)
        validation = TicketValidation.objects.get(
            ticket=self.ticket,
            result=TicketValidation.Result.VALID,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(validation.token_fingerprint, self.token)
        self.assertEqual(len(validation.token_fingerprint), 64)

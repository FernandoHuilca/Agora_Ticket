from datetime import timedelta

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from config.asgi import application
from events.models import Event
from tickets.services.reservations import create_reservation
from users.models import User

from . import services
from .access import (
    ROLE_BUYER,
    ROLE_MODERATOR,
    ROLE_ORGANIZER,
    conversation_role,
    unread_summary,
)
from .models import MAX_MESSAGE_LENGTH, Conversation, Message, Presence

ORIGIN = b'http://localhost'


def make_user(email, role=User.Role.CLIENT, **extra):
    return User.objects.create_user(
        email=email, password='clave-de-prueba-123', role=role, **extra,
    )


def make_event(organizer, name='Concierto de prueba'):
    now = timezone.now()
    return Event.objects.create(
        organizer=organizer,
        name=name,
        description='Descripción suficientemente larga para pruebas.',
        start_date=now + timedelta(days=2),
        end_date=now + timedelta(days=2, hours=2),
        location='Sala principal',
        capacity=20,
        available_tickets=20,
        is_free=True,
    )


def give_ticket(user, event):
    """Un evento gratuito emite el ticket al instante: el usuario pasa a ser comprador."""
    return create_reservation(
        user, event, [{'attendee_name': 'Asistente', 'attendee_email': ''}],
    )


class ChatFixtureMixin:
    def create_fixture(self):
        self.organizer = make_user(
            'organizador@example.com', User.Role.ORGANIZER, first_name='Olga', last_name='Ruiz',
        )
        self.buyer = make_user('comprador@example.com', first_name='Ana', last_name='Pérez')
        self.other_buyer = make_user('otro@example.com', first_name='Luis')
        self.stranger = make_user('sinticket@example.com')
        self.admin = make_user('admin@example.com', User.Role.ADMIN)
        self.event = make_event(self.organizer)
        give_ticket(self.buyer, self.event)
        give_ticket(self.other_buyer, self.event)
        self.general = Conversation.objects.create(
            event=self.event, kind=Conversation.Kind.GENERAL,
        )
        self.private = Conversation.objects.create(
            event=self.event, kind=Conversation.Kind.PRIVATE, buyer=self.buyer,
        )


class CleanBodyTests(SimpleTestCase):
    """Validación y saneamiento en el servidor de los mensajes recibidos."""

    def test_rejects_empty_non_text_and_too_long_messages(self):
        for raw, code in (
            ('   \n  ', 'empty'),
            (None, 'invalid'),
            ({'html': '<b>'}, 'invalid'),
            ('x' * (MAX_MESSAGE_LENGTH + 1), 'too_long'),
        ):
            with self.subTest(code=code), self.assertRaises(services.InvalidMessage) as ctx:
                services.clean_body(raw)
            self.assertEqual(ctx.exception.code, code)

    def test_strips_control_characters_and_extra_blank_lines(self):
        cleaned = services.clean_body('  Hola\x00\x07 ‮mundo\r\n\r\n\r\n\r\nfin  ')
        self.assertEqual(cleaned, 'Hola mundo\n\nfin')

    def test_accepts_message_at_the_length_limit(self):
        self.assertEqual(len(services.clean_body('x' * MAX_MESSAGE_LENGTH)), MAX_MESSAGE_LENGTH)


class AccessRulesTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.create_fixture()

    def test_roles_by_conversation(self):
        self.assertEqual(conversation_role(self.organizer, self.private), ROLE_ORGANIZER)
        self.assertEqual(conversation_role(self.buyer, self.private), ROLE_BUYER)
        self.assertEqual(conversation_role(self.buyer, self.general), ROLE_BUYER)
        self.assertEqual(conversation_role(self.admin, self.private), ROLE_MODERATOR)
        # Otro comprador entra a la sala general, pero no al privado ajeno.
        self.assertEqual(conversation_role(self.other_buyer, self.general), ROLE_BUYER)
        self.assertIsNone(conversation_role(self.other_buyer, self.private))
        self.assertIsNone(conversation_role(self.stranger, self.general))

    def test_suspended_account_loses_access(self):
        self.buyer.is_active = False
        self.buyer.save()
        self.assertIsNone(conversation_role(self.buyer, self.private))

    def test_unread_counts_only_messages_from_others_after_last_read(self):
        services.create_message(self.private, self.buyer, 'Hola, ¿hay parqueadero?')
        services.create_message(self.private, self.buyer, '¿Y a qué hora abren?')
        summary = unread_summary(self.organizer)
        self.assertEqual(summary['unread_total'], 2)
        self.assertEqual(summary['by_conversation'], {str(self.private.pk): 2})
        # Quien envía no acumula no leídos de sus propios mensajes.
        self.assertEqual(unread_summary(self.buyer)['unread_total'], 0)

        services.mark_read(self.private, [self.organizer.id])
        self.assertEqual(unread_summary(self.organizer)['unread_total'], 0)


class ChatViewsTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.create_fixture()

    def test_inbox_requires_login(self):
        response = self.client.get(reverse('chat:inbox'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_inbox_lists_general_room_and_private_chat_for_a_buyer(self):
        Conversation.objects.all().delete()
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('chat:inbox'))
        self.assertEqual(response.status_code, 200)
        kinds = sorted(item['conversation'].kind for item in response.context['items'])
        self.assertEqual(kinds, [Conversation.Kind.GENERAL, Conversation.Kind.PRIVATE])

    def test_organizer_only_sees_private_chats_that_have_messages(self):
        self.client.force_login(self.organizer)
        items = self.client.get(reverse('chat:inbox')).context['items']
        self.assertEqual([item['conversation'].pk for item in items], [self.general.pk])

        services.create_message(self.private, self.buyer, 'Hola')
        items = self.client.get(reverse('chat:inbox')).context['items']
        self.assertEqual(items[0]['conversation'].pk, self.private.pk)
        self.assertEqual(items[0]['unread'], 1)

    def test_buyer_opens_private_chat_and_stranger_is_sent_back(self):
        self.client.force_login(self.other_buyer)
        response = self.client.get(reverse('chat:open_event', args=[self.event.pk]))
        conversation = Conversation.objects.get(buyer=self.other_buyer)
        self.assertRedirects(
            response, reverse('chat:conversation', args=[conversation.pk]),
        )

        self.client.force_login(self.stranger)
        response = self.client.get(reverse('chat:open_event', args=[self.event.pk]))
        self.assertRedirects(
            response, reverse('events:detail', args=[self.event.pk]),
        )
        self.assertFalse(Conversation.objects.filter(buyer=self.stranger).exists())

    def test_private_conversation_is_forbidden_to_other_users(self):
        for user in (self.other_buyer, self.stranger):
            self.client.force_login(user)
            for name in ('chat:conversation', 'chat:history'):
                with self.subTest(user=user.email, view=name):
                    response = self.client.get(reverse(name, args=[self.private.pk]))
                    self.assertEqual(response.status_code, 403)

    def test_opening_a_conversation_marks_it_as_read(self):
        services.create_message(self.private, self.buyer, 'Hola')
        self.client.force_login(self.organizer)
        self.client.get(reverse('chat:conversation', args=[self.private.pk]))
        self.assertEqual(unread_summary(self.organizer)['unread_total'], 0)

    def test_message_html_is_escaped_when_rendered(self):
        services.create_message(self.private, self.buyer, '<script>alert(1)</script>')
        self.client.force_login(self.organizer)
        response = self.client.get(reverse('chat:conversation', args=[self.private.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, 'alert(1)')

    def test_history_is_paginated(self):
        for number in range(services.HISTORY_PAGE_SIZE + 5):
            services.create_message(self.private, self.buyer, f'Mensaje {number}')
        self.client.force_login(self.organizer)
        url = reverse('chat:history', args=[self.private.pk])

        first = self.client.get(url).json()
        self.assertEqual(len(first['messages']), services.HISTORY_PAGE_SIZE)
        self.assertTrue(first['has_more'])

        older = self.client.get(url, {'before': first['messages'][0]['id']}).json()
        self.assertEqual(len(older['messages']), 5)
        self.assertFalse(older['has_more'])
        self.assertEqual(older['messages'][0]['body'], 'Mensaje 0')

        self.assertEqual(self.client.get(url, {'before': 'abc'}).status_code, 400)

    def test_only_the_organizer_can_open_a_chat_with_a_buyer(self):
        url = reverse('chat:open_with_buyer', args=[self.event.pk, self.other_buyer.pk])
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertTrue(Conversation.objects.filter(buyer=self.other_buyer).exists())

        no_ticket = reverse('chat:open_with_buyer', args=[self.event.pk, self.stranger.pk])
        self.assertEqual(self.client.get(no_ticket).status_code, 403)


class ChatWebSocketTests(ChatFixtureMixin, TransactionTestCase):
    """Pruebas de extremo a extremo contra la aplicación ASGI real (config.asgi)."""

    def setUp(self):
        self.create_fixture()

    def _headers(self, user):
        headers = [(b'origin', ORIGIN)]
        if user is not None:
            client = Client()
            client.force_login(user)
            cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
            headers.append((b'cookie', f'{settings.SESSION_COOKIE_NAME}={cookie}'.encode()))
        return headers

    async def _socket(self, path, user, headers=None):
        if headers is None:
            headers = await database_sync_to_async(self._headers)(user)
        communicator = WebsocketCommunicator(application, path, headers=headers)
        connected, _ = await communicator.connect()
        return communicator, connected

    async def _chat(self, conversation, user):
        communicator, connected = await self._socket(f'/ws/chat/{conversation.pk}/', user)
        self.assertTrue(connected)
        return communicator

    async def _receive(self, communicator, kind):
        """Devuelve el siguiente mensaje del tipo pedido (ignora los demás)."""
        while True:
            data = await communicator.receive_json_from(timeout=3)
            if data['type'] == kind:
                return data

    async def test_handshake_rejects_anonymous_users_and_users_without_access(self):
        path = f'/ws/chat/{self.private.pk}/'
        for user in (None, self.stranger, self.other_buyer):
            communicator, connected = await self._socket(path, user)
            self.assertFalse(connected)
            await communicator.disconnect()

        communicator, connected = await self._socket('/ws/notificaciones/', None)
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_handshake_rejects_foreign_origin(self):
        headers = await database_sync_to_async(self._headers)(self.buyer)
        headers[0] = (b'origin', b'https://sitio-malicioso.example')
        communicator, connected = await self._socket(
            f'/ws/chat/{self.private.pk}/', self.buyer, headers=headers,
        )
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_two_users_exchange_messages_in_real_time(self):
        buyer = await self._chat(self.private, self.buyer)
        organizer = await self._chat(self.private, self.organizer)

        presence = await self._receive(organizer, 'presence')
        self.assertEqual(
            {user['id'] for user in presence['users']},
            {self.buyer.id, self.organizer.id},
        )

        await buyer.send_json_to({'type': 'message', 'body': '  Hola, ¿hay parqueadero?  '})
        received = await self._receive(organizer, 'message')
        self.assertEqual(received['body'], 'Hola, ¿hay parqueadero?')
        self.assertEqual(received['sender_id'], self.buyer.id)
        self.assertEqual(received['sender_name'], 'Ana Pérez')
        self.assertFalse(received['is_organizer'])
        # El remitente recibe el eco de su propio mensaje como confirmación.
        self.assertEqual((await self._receive(buyer, 'message'))['id'], received['id'])

        await organizer.send_json_to({'type': 'message', 'body': 'Sí, en el subsuelo.'})
        reply = await self._receive(buyer, 'message')
        self.assertTrue(reply['is_organizer'])

        stored = await database_sync_to_async(
            lambda: list(self.private.messages.values_list('body', flat=True))
        )()
        self.assertEqual(stored, ['Hola, ¿hay parqueadero?', 'Sí, en el subsuelo.'])

        await buyer.disconnect()
        presence = await self._receive(organizer, 'presence')
        self.assertEqual([user['id'] for user in presence['users']], [self.organizer.id])
        await organizer.disconnect()
        self.assertEqual(await database_sync_to_async(Presence.objects.count)(), 0)

    async def test_invalid_messages_are_rejected_and_not_stored(self):
        buyer = await self._chat(self.private, self.buyer)
        for frame in (
            {'type': 'message', 'body': '   '},
            {'type': 'message', 'body': 'x' * (MAX_MESSAGE_LENGTH + 1)},
            {'type': 'message', 'body': {'no': 'texto'}},
            {'type': 'desconocido'},
        ):
            await buyer.send_json_to(frame)
            self.assertIn('code', await self._receive(buyer, 'error'))
        await buyer.send_to(text_data='esto no es JSON')
        self.assertEqual((await self._receive(buyer, 'error'))['code'], 'invalid')

        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
        await buyer.disconnect()

    async def test_admin_can_read_but_not_write(self):
        admin = await self._chat(self.private, self.admin)
        await admin.send_json_to({'type': 'message', 'body': 'Hola'})
        self.assertEqual((await self._receive(admin, 'error'))['code'], 'read_only')
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
        await admin.disconnect()

    async def test_suspended_user_is_disconnected_on_next_message(self):
        buyer = await self._chat(self.private, self.buyer)
        await database_sync_to_async(
            User.objects.filter(pk=self.buyer.pk).update
        )(is_active=False)
        await buyer.send_json_to({'type': 'message', 'body': 'Sigo aquí'})
        self.assertEqual((await self._receive(buyer, 'error'))['code'], 'forbidden')
        self.assertEqual((await buyer.receive_output(timeout=3))['type'], 'websocket.close')
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)

    async def test_suspending_an_account_closes_its_open_sockets(self):
        buyer = await self._chat(self.private, self.buyer)
        notifications, _ = await self._socket('/ws/notificaciones/', self.buyer)

        def suspend():
            # Igual que el panel de administración: cambia is_active y guarda.
            self.buyer.is_active = False
            self.buyer.save()

        await database_sync_to_async(suspend)()
        for communicator in (buyer, notifications):
            while True:
                output = await communicator.receive_output(timeout=3)
                if output['type'] == 'websocket.close':
                    break
            self.assertEqual(output['code'], 4401)

    async def test_unread_counter_notification_reaches_absent_recipient(self):
        notifications, connected = await self._socket('/ws/notificaciones/', self.organizer)
        self.assertTrue(connected)
        self.assertEqual((await self._receive(notifications, 'unread'))['unread_total'], 0)

        buyer = await self._chat(self.private, self.buyer)
        await buyer.send_json_to({'type': 'message', 'body': 'Hola organizador'})

        notice = await self._receive(notifications, 'chat')
        self.assertEqual(notice['unread_total'], 1)
        self.assertEqual(notice['conversation_id'], str(self.private.pk))
        self.assertEqual(notice['conversation_unread'], 1)
        self.assertEqual(notice['sender_name'], 'Ana Pérez')
        self.assertEqual(notice['preview'], 'Hola organizador')

        # Al abrir la conversación queda leída y el contador vuelve a cero.
        organizer = await self._chat(self.private, self.organizer)
        self.assertEqual((await self._receive(notifications, 'unread'))['unread_total'], 0)

        # Con la conversación abierta, un mensaje nuevo ya no genera aviso.
        await buyer.send_json_to({'type': 'message', 'body': '¿Sigues ahí?'})
        await self._receive(organizer, 'message')
        self.assertTrue(await notifications.receive_nothing(timeout=0.3))

        for communicator in (buyer, organizer, notifications):
            await communicator.disconnect()

    async def test_new_event_broadcast_reaches_connected_users(self):
        from events.views import _broadcast_new_event_notification

        notifications, _ = await self._socket('/ws/notificaciones/', self.buyer)
        await self._receive(notifications, 'unread')
        await database_sync_to_async(_broadcast_new_event_notification)(self.event)
        notice = await self._receive(notifications, 'event')
        self.assertEqual(notice['event_id'], str(self.event.pk))
        self.assertEqual(notice['name'], self.event.name)
        await notifications.disconnect()

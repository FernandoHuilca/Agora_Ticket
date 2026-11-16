"""Consumers WebSocket del chat (Django Channels).

- ChatConsumer: una conexión por conversación abierta en pantalla.
- NotificationConsumer: una conexión por página para el contador de no leídos
  y los avisos en tiempo real (mensaje nuevo, evento publicado).

La autenticación ocurre en el handshake: `AuthMiddlewareStack` (config/asgi.py)
lee la cookie de sesión de la petición de upgrade y deja al usuario en `scope`.
Si no hay sesión válida o no hay permiso, la conexión se rechaza antes de aceptarla.
"""
import json
import time
from collections import deque

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import services
from .access import can_write, display_name, unread_summary
from .models import Conversation

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403

MAX_FRAME_CHARS = 8000          # Un mensaje válido nunca se acerca a este tamaño.
RATE_LIMIT_MESSAGES = 8         # Máximo de mensajes...
RATE_LIMIT_WINDOW = 10          # ...por esta cantidad de segundos, por conexión.
TYPING_INTERVAL = 2             # Segundos mínimos entre avisos de "escribiendo".

# Grupo al que el módulo de eventos difunde las publicaciones nuevas.
BROADCAST_GROUP = 'notifications'


def chat_group(conversation_id):
    return f'chat.{conversation_id}'


def user_group(user_id):
    """Avisos personales (no leídos) de un usuario, en todas sus pestañas."""
    return f'user.{user_id}'


def session_group(user_id):
    """Permite cerrar todas las conexiones de un usuario (cuenta suspendida)."""
    return f'session.{user_id}'


class _SafeJsonConsumer(AsyncJsonWebsocketConsumer):
    """Base común: tolera JSON inválido en vez de tumbar la conexión."""

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if not text_data or len(text_data) > MAX_FRAME_CHARS:
            await self.send_error('invalid', 'Mensaje no válido.')
            return
        try:
            content = json.loads(text_data)
        except ValueError:
            await self.send_error('invalid', 'Mensaje no válido.')
            return
        if not isinstance(content, dict):
            await self.send_error('invalid', 'Mensaje no válido.')
            return
        await self.receive_json(content)

    async def send_error(self, code, message):
        await self.send_json({'type': 'error', 'code': code, 'message': message})

    async def session_terminate(self, event):
        await self.close(code=CLOSE_UNAUTHENTICATED)


class ChatConsumer(_SafeJsonConsumer):
    async def connect(self):
        self.joined = False
        scope_user = self.scope.get('user')
        if scope_user is None or not scope_user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.user_id = scope_user.pk
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        user, conversation, role = await database_sync_to_async(services.load_access)(
            self.user_id, self.conversation_id,
        )
        if role is None:
            await self.close(code=CLOSE_FORBIDDEN)
            return

        self.user_name = display_name(user)
        self.group = chat_group(self.conversation_id)
        self.sent_at = deque()
        self.last_typing = 0.0

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.channel_layer.group_add(session_group(self.user_id), self.channel_name)
        self.joined = True
        await self.accept()

        await database_sync_to_async(self._enter)(conversation, role)
        await self._broadcast_presence()
        # Abrir la conversación la deja leída: se refresca el contador del navbar.
        await self.channel_layer.group_send(
            user_group(self.user_id), {'type': 'unread.refresh'},
        )

    def _enter(self, conversation, role):
        services.presence_join(self.conversation_id, self.user_id, role, self.channel_name)
        services.mark_read(conversation, [self.user_id])

    async def disconnect(self, code):
        if not getattr(self, 'joined', False):
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)
        await self.channel_layer.group_discard(session_group(self.user_id), self.channel_name)
        await database_sync_to_async(services.presence_leave)(self.channel_name)
        await self._broadcast_presence()

    async def receive_json(self, content, **kwargs):
        kind = content.get('type')
        if kind == 'ping':
            await self._heartbeat()
        elif kind == 'typing':
            await self._typing()
        elif kind == 'message':
            await self._message(content.get('body'))
        else:
            await self.send_error('unknown_type', 'Tipo de mensaje no reconocido.')

    async def _current_access(self):
        """Vuelve a comprobar el permiso contra la base de datos; cierra si se perdió."""
        user, conversation, role = await database_sync_to_async(services.load_access)(
            self.user_id, self.conversation_id,
        )
        if role is None:
            await self.send_error('forbidden', 'Ya no tienes acceso a esta conversación.')
            await self.close(code=CLOSE_FORBIDDEN)
        return user, conversation, role

    async def _heartbeat(self):
        _, _, role = await self._current_access()
        if role is None:
            return
        await database_sync_to_async(services.presence_touch)(self.channel_name)
        await self.send_json({'type': 'pong'})

    async def _typing(self):
        now = time.monotonic()
        if now - self.last_typing < TYPING_INTERVAL:
            return
        self.last_typing = now
        await self.channel_layer.group_send(self.group, {
            'type': 'chat.typing',
            'user_id': self.user_id,
            'name': self.user_name,
        })

    def _rate_limited(self):
        now = time.monotonic()
        while self.sent_at and now - self.sent_at[0] > RATE_LIMIT_WINDOW:
            self.sent_at.popleft()
        if len(self.sent_at) >= RATE_LIMIT_MESSAGES:
            return True
        self.sent_at.append(now)
        return False

    async def _message(self, raw_body):
        try:
            body = services.clean_body(raw_body)
        except services.InvalidMessage as error:
            await self.send_error(error.code, error.message)
            return
        if self._rate_limited():
            await self.send_error(
                'rate_limited',
                'Estás enviando mensajes muy rápido. Espera unos segundos.',
            )
            return

        user, conversation, role = await self._current_access()
        if role is None:
            return
        if not can_write(role):
            await self.send_error('read_only', 'Solo puedes leer esta conversación.')
            return

        payload, recipients = await database_sync_to_async(services.create_message)(
            conversation, user, body,
        )
        await self.channel_layer.group_send(
            self.group, {'type': 'chat.message', 'message': payload},
        )
        notice = {
            'type': 'chat.notify',
            'conversation_id': str(conversation.pk),
            'is_general': conversation.kind == Conversation.Kind.GENERAL,
            'event_name': conversation.event.name,
            'sender_name': payload['sender_name'],
            'preview': services.preview(body),
        }
        for recipient_id in recipients:
            await self.channel_layer.group_send(user_group(recipient_id), notice)

    async def _broadcast_presence(self):
        users = await database_sync_to_async(services.present_users)(self.conversation_id)
        await self.channel_layer.group_send(
            self.group, {'type': 'chat.presence', 'users': users},
        )

    # ---- Eventos recibidos desde el channel layer ----

    async def chat_message(self, event):
        await self.send_json({'type': 'message', **event['message']})

    async def chat_presence(self, event):
        await self.send_json({'type': 'presence', 'users': event['users']})

    async def chat_typing(self, event):
        if event['user_id'] != self.user_id:
            await self.send_json({
                'type': 'typing', 'user_id': event['user_id'], 'name': event['name'],
            })


class NotificationConsumer(_SafeJsonConsumer):
    async def connect(self):
        self.joined = False
        user = self.scope.get('user')
        if user is None or not user.is_authenticated or not user.is_active:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.user = user
        self.groups_joined = (
            user_group(user.pk), session_group(user.pk), BROADCAST_GROUP,
        )
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        self.joined = True
        await self.accept()
        await self._send_unread()

    async def disconnect(self, code):
        if not getattr(self, 'joined', False):
            return
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # El cliente solo envía latidos para mantener viva la conexión.
        if content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def _send_unread(self, extra=None):
        summary = await database_sync_to_async(unread_summary)(self.user)
        await self.send_json({'type': 'unread', **summary, **(extra or {})})

    # ---- Eventos recibidos desde el channel layer ----

    async def unread_refresh(self, event):
        await self._send_unread()

    async def chat_notify(self, event):
        """Mensaje nuevo en una conversación que el usuario no tiene abierta."""
        summary = await database_sync_to_async(unread_summary)(self.user)
        await self.send_json({
            'type': 'chat',
            'conversation_id': event['conversation_id'],
            'is_general': event['is_general'],
            'event_name': event['event_name'],
            'sender_name': event['sender_name'],
            'preview': event['preview'],
            'conversation_unread': summary['by_conversation'].get(
                event['conversation_id'], 0,
            ),
            **summary,
        })

    async def event_notification(self, event):
        """Evento recién publicado en la cartelera (lo emite events.views)."""
        await self.send_json({
            'type': 'event',
            'event_id': event.get('event_id'),
            'name': event.get('name'),
            'category': event.get('category'),
            'start_date': event.get('start_date'),
            'message': event.get('message'),
        })

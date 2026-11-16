"""Operaciones del chat: validar y guardar mensajes, lecturas y presencia."""
import re
import unicodedata
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from users.models import User

from .access import ROLE_LABELS, conversation_role, display_name, participant_ids
from .models import MAX_MESSAGE_LENGTH, Conversation, ConversationRead, Message, Presence

HISTORY_PAGE_SIZE = 30
# El cliente envía un latido cada 25 s; pasado este margen la conexión se da por caída.
PRESENCE_TIMEOUT = timedelta(seconds=75)
PREVIEW_LENGTH = 90

_EXTRA_BLANK_LINES = re.compile(r'\n{3,}')
_BIDI_OVERRIDES = frozenset('‪‫‬‭‮⁦⁧⁨⁩')


class InvalidMessage(ValueError):
    """El texto recibido no puede guardarse. `code` identifica el motivo."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def clean_body(raw):
    """Valida y sanea el texto de un mensaje recibido por el WebSocket.

    Se guarda texto plano: el escape de HTML se hace al mostrarlo (plantillas de
    Django y `textContent` en el navegador), así no se almacena contenido doblemente
    escapado ni se confía en que el cliente lo haya limpiado.
    """
    if not isinstance(raw, str):
        raise InvalidMessage('invalid', 'El mensaje debe ser texto.')
    text = raw.replace('\r\n', '\n').replace('\r', '\n')
    # Fuera caracteres de control (p. ej. NUL) y los que invierten la dirección del texto.
    text = ''.join(
        char for char in text
        if char in '\n\t'
        or (unicodedata.category(char) != 'Cc' and char not in _BIDI_OVERRIDES)
    )
    text = _EXTRA_BLANK_LINES.sub('\n\n', text).strip()
    if not text:
        raise InvalidMessage('empty', 'Escribe un mensaje antes de enviarlo.')
    if len(text) > MAX_MESSAGE_LENGTH:
        raise InvalidMessage(
            'too_long',
            f'El mensaje no puede superar los {MAX_MESSAGE_LENGTH} caracteres.',
        )
    return text


def preview(body):
    text = ' '.join(body.split())
    return text if len(text) <= PREVIEW_LENGTH else text[:PREVIEW_LENGTH - 1] + '…'


def serialize_message(message, organizer_id):
    return {
        'id': message.id,
        'body': message.body,
        'sender_id': message.sender_id,
        'sender_name': display_name(message.sender),
        'is_organizer': message.sender_id == organizer_id,
        'created_at': message.created_at.isoformat(),
    }


def history(conversation, before=None, after=None, limit=HISTORY_PAGE_SIZE):
    """Página del historial en orden cronológico y si quedan mensajes más antiguos.

    `before` pagina hacia atrás; `after` recupera lo perdido tras una reconexión.
    """
    queryset = conversation.messages.select_related('sender')
    if after is not None:
        rows = list(queryset.filter(id__gt=after).order_by('id')[:limit])
        has_more = False
    else:
        if before is not None:
            queryset = queryset.filter(id__lt=before)
        rows = list(queryset.order_by('-id')[:limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit][::-1]
    organizer_id = conversation.event.organizer_id
    return [serialize_message(row, organizer_id) for row in rows], has_more


def mark_read(conversation, user_ids, at=None):
    """Registra que esos usuarios leyeron la conversación hasta `at` (ahora por defecto)."""
    user_ids = set(user_ids)
    if not user_ids:
        return
    at = at or timezone.now()
    ConversationRead.objects.bulk_create(
        [
            ConversationRead(conversation=conversation, user_id=user_id, last_read_at=at)
            for user_id in user_ids
        ],
        update_conflicts=True,
        unique_fields=['conversation', 'user'],
        update_fields=['last_read_at'],
    )


@transaction.atomic
def create_message(conversation, sender, body):
    """Guarda un mensaje ya validado.

    Devuelve el mensaje serializado y los usuarios a notificar: participantes que
    no lo enviaron y que no tienen la conversación abierta en este momento. A
    quienes sí la tienen abierta se les marca como leído al instante.
    """
    message = Message.objects.create(conversation=conversation, sender=sender, body=body)
    Conversation.objects.filter(pk=conversation.pk).update(
        last_message_at=message.created_at,
    )
    present = present_user_ids(conversation.pk) | {sender.id}
    mark_read(conversation, present, at=message.created_at)
    recipients = participant_ids(conversation) - present
    payload = serialize_message(message, conversation.event.organizer_id)
    return payload, recipients


# ---------- Presencia (usuarios conectados) ----------

def _presence_cutoff():
    return timezone.now() - PRESENCE_TIMEOUT


def presence_join(conversation_id, user_id, role, channel_name):
    Presence.objects.filter(
        conversation_id=conversation_id, last_seen__lt=_presence_cutoff(),
    ).delete()
    Presence.objects.update_or_create(
        channel_name=channel_name,
        defaults={
            'conversation_id': conversation_id,
            'user_id': user_id,
            'role': role,
            'last_seen': timezone.now(),
        },
    )


def presence_leave(channel_name):
    Presence.objects.filter(channel_name=channel_name).delete()


def presence_touch(channel_name):
    Presence.objects.filter(channel_name=channel_name).update(last_seen=timezone.now())


def present_user_ids(conversation_id):
    return set(
        Presence.objects.filter(
            conversation_id=conversation_id, last_seen__gte=_presence_cutoff(),
        ).values_list('user_id', flat=True)
    )


def present_users(conversation_id):
    """Usuarios conectados a la conversación, sin repetir a quien tiene varias pestañas."""
    rows = Presence.objects.filter(
        conversation_id=conversation_id, last_seen__gte=_presence_cutoff(),
    ).select_related('user').order_by('id')
    users = {}
    for row in rows:
        users.setdefault(row.user_id, {
            'id': row.user_id,
            'name': display_name(row.user),
            'role': row.role,
            'role_label': ROLE_LABELS.get(row.role, ''),
        })
    return list(users.values())


def load_access(user_id, conversation_id):
    """Relee de la base de datos al usuario y la conversación y devuelve (usuario, conversación, rol).

    Se usa al abrir el socket y antes de cada mensaje: así una cuenta suspendida o
    un ticket cancelado pierden el acceso aunque la conexión siga abierta.
    """
    user = User.objects.filter(pk=user_id).first()
    conversation = (
        Conversation.objects
        .select_related('event__organizer', 'buyer')
        .filter(pk=conversation_id)
        .first()
    )
    if user is None or conversation is None:
        return user, conversation, None
    return user, conversation, conversation_role(user, conversation)

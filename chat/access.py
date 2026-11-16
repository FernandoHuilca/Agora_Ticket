"""Reglas de acceso del chat y consultas de la bandeja.

Toda decisión de "quién puede ver o escribir" pasa por este módulo, tanto
desde las vistas HTTP como desde los consumers WebSocket.
"""
from datetime import datetime, timezone as dt_timezone

from django.db.models import Count, DateTimeField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from events.models import Event
from tickets.models import Ticket
from users.models import User

from .models import Conversation, ConversationRead, Message

ROLE_ORGANIZER = 'organizer'
ROLE_BUYER = 'buyer'
ROLE_MODERATOR = 'moderator'  # ADMIN ajeno al evento: solo lectura.

ROLE_LABELS = {
    ROLE_ORGANIZER: 'Organizador',
    ROLE_BUYER: 'Comprador',
    ROLE_MODERATOR: 'Administrador',
}

INBOX_LIMIT = 100
_EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


def display_name(user):
    """Nombre visible en el chat. Nunca expone el correo completo a otros usuarios."""
    return user.get_full_name().strip() or user.email.split('@')[0]


def has_ticket(user, event_id):
    """Un comprador es quien tiene al menos un ticket EMITIDO del evento."""
    return Ticket.objects.filter(
        reservation__user=user,
        event_id=event_id,
        status=Ticket.Status.ISSUED,
    ).exists()


def _is_usable(user):
    return bool(user and user.is_authenticated and user.is_active)


def event_role(user, event):
    """Rol del usuario frente al chat de un evento, o None si no tiene acceso."""
    if not _is_usable(user):
        return None
    if event.organizer_id == user.id:
        return ROLE_ORGANIZER
    if has_ticket(user, event.pk):
        return ROLE_BUYER
    if user.has_role(User.Role.ADMIN):
        return ROLE_MODERATOR
    return None


def conversation_role(user, conversation):
    """Rol del usuario dentro de una conversación concreta, o None si no puede entrar."""
    if not _is_usable(user):
        return None
    if conversation.event.organizer_id == user.id:
        return ROLE_ORGANIZER
    is_own_private = (
        conversation.kind == Conversation.Kind.PRIVATE
        and conversation.buyer_id == user.id
    )
    if (conversation.is_general or is_own_private) and has_ticket(user, conversation.event_id):
        return ROLE_BUYER
    if user.has_role(User.Role.ADMIN):
        return ROLE_MODERATOR
    return None


def can_write(role):
    return role in (ROLE_ORGANIZER, ROLE_BUYER)


def _buyer_event_ids(user):
    return Ticket.objects.filter(
        reservation__user=user,
        status=Ticket.Status.ISSUED,
    ).values('event_id')


def participant_ids(conversation):
    """Usuarios que deben recibir avisos de mensajes nuevos de la conversación."""
    ids = {conversation.event.organizer_id}
    if conversation.kind == Conversation.Kind.PRIVATE:
        ids.add(conversation.buyer_id)
    else:
        ids.update(
            Ticket.objects.filter(
                event_id=conversation.event_id,
                status=Ticket.Status.ISSUED,
            ).values_list('reservation__user_id', flat=True).distinct()
        )
    return ids


def ensure_conversations(user):
    """Crea las conversaciones que al usuario le corresponde ver en su bandeja.

    - Sala general de cada evento que organiza o del que tiene ticket.
    - Chat privado con el organizador de cada evento del que tiene ticket.
    Es idempotente: las restricciones únicas evitan duplicados.
    """
    bought = set(_buyer_event_ids(user).values_list('event_id', flat=True))
    organized = set(
        Event.objects.filter(organizer=user).values_list('pk', flat=True)
    )
    event_ids = bought | organized
    if not event_ids:
        return

    with_general = set(
        Conversation.objects.filter(
            event_id__in=event_ids, kind=Conversation.Kind.GENERAL,
        ).values_list('event_id', flat=True)
    )
    with_private = set(
        Conversation.objects.filter(
            event_id__in=bought, kind=Conversation.Kind.PRIVATE, buyer=user,
        ).values_list('event_id', flat=True)
    )
    missing = [
        Conversation(event_id=event_id, kind=Conversation.Kind.GENERAL)
        for event_id in event_ids - with_general
    ] + [
        Conversation(event_id=event_id, kind=Conversation.Kind.PRIVATE, buyer=user)
        # El organizador no abre un chat privado consigo mismo.
        for event_id in bought - organized - with_private
    ]
    if missing:
        Conversation.objects.bulk_create(missing, ignore_conflicts=True)


def conversations_for(user):
    """Conversaciones visibles en la bandeja, con no leídos y último mensaje."""
    bought = _buyer_event_ids(user)
    last_read = ConversationRead.objects.filter(
        conversation=OuterRef('pk'), user=user,
    ).values('last_read_at')[:1]
    unread = (
        Message.objects
        .filter(conversation=OuterRef('pk'), created_at__gt=OuterRef('last_read'))
        .exclude(sender=user)
        .order_by()
        .values('conversation')
        .annotate(total=Count('pk'))
        .values('total')
    )
    last_message = Message.objects.filter(conversation=OuterRef('pk')).order_by('-id')

    return (
        Conversation.objects
        .filter(
            Q(kind=Conversation.Kind.GENERAL, event__organizer=user)
            | Q(kind=Conversation.Kind.GENERAL, event_id__in=bought)
            | Q(kind=Conversation.Kind.PRIVATE, buyer=user, event_id__in=bought)
            # Al organizador solo le aparecen los privados donde ya hay mensajes.
            | Q(
                kind=Conversation.Kind.PRIVATE,
                event__organizer=user,
                last_message_at__isnull=False,
            )
        )
        .select_related('event__organizer', 'buyer')
        .annotate(
            last_read=Coalesce(
                Subquery(last_read), Value(_EPOCH), output_field=DateTimeField(),
            ),
        )
        .annotate(
            unread=Coalesce(Subquery(unread), 0),
            last_body=Subquery(last_message.values('body')[:1]),
        )
        .order_by(Coalesce('last_message_at', Value(_EPOCH)).desc(), '-created_at')
    )


def unread_summary(user):
    """Total de no leídos y desglose por conversación (solo las que tienen pendientes)."""
    rows = conversations_for(user).select_related(None).values_list('pk', 'unread')
    by_conversation = {str(pk): unread for pk, unread in rows[:INBOX_LIMIT] if unread}
    return {
        'unread_total': sum(by_conversation.values()),
        'by_conversation': by_conversation,
    }


def describe(conversation, user):
    """Título y subtítulo de una conversación desde el punto de vista de `user`."""
    event = conversation.event
    if conversation.is_general:
        return {'title': 'Sala general', 'subtitle': event.name, 'avatar': '#'}
    if conversation.buyer_id == user.id:
        name = display_name(event.organizer)
        return {'title': f'Organizador · {name}', 'subtitle': event.name, 'avatar': name[:1]}
    name = display_name(conversation.buyer)
    return {'title': name, 'subtitle': event.name, 'avatar': name[:1]}

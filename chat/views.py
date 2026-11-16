from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from events.models import Event
from users.models import User
from users.permissions import role_required

from . import services
from .access import (
    INBOX_LIMIT,
    ROLE_BUYER,
    ROLE_MODERATOR,
    ROLE_ORGANIZER,
    can_write,
    conversation_role,
    conversations_for,
    describe,
    ensure_conversations,
    event_role,
    has_ticket,
)
from .models import MAX_MESSAGE_LENGTH, Conversation

# El chat es para cualquier cuenta activa; el acceso real lo decide cada conversación.
chat_user_required = role_required(*User.Role.values)


def _conversation_or_403(user, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related('event__organizer', 'buyer'), pk=pk,
    )
    role = conversation_role(user, conversation)
    if role is None:
        raise PermissionDenied
    return conversation, role


@chat_user_required
@require_GET
def inbox(request, pk=None):
    """Bandeja 'Mensajes': lista de conversaciones y, si se eligió una, su chat."""
    user = request.user
    active = role = None
    if pk is not None:
        active, role = _conversation_or_403(user, pk)
        # Abrir una conversación la marca como leída antes de calcular los contadores.
        services.mark_read(active, [user.id])

    ensure_conversations(user)
    items = [
        {
            'conversation': conversation,
            'unread': conversation.unread,
            'preview': services.preview(conversation.last_body or ''),
            'is_active': active is not None and conversation.pk == active.pk,
            **describe(conversation, user),
        }
        for conversation in conversations_for(user)[:INBOX_LIMIT]
    ]

    context = {'items': items, 'active': active}
    if active is not None:
        history_page, has_more = services.history(active)
        context.update({
            'active_info': describe(active, user),
            'role': role,
            'can_write': can_write(role),
            'max_length': MAX_MESSAGE_LENGTH,
            'chat_config': {
                'conversationId': str(active.pk),
                'socketPath': f'/ws/chat/{active.pk}/',
                'historyUrl': reverse('chat:history', args=[active.pk]),
                'userId': user.id,
                'canWrite': can_write(role),
                'isGeneral': active.is_general,
                'maxLength': MAX_MESSAGE_LENGTH,
                'messages': history_page,
                'hasMore': has_more,
            },
        })
    return render(request, 'chat/inbox.html', context)


def _positive_int(value):
    if value is None:
        return None
    if not value.isascii() or not value.isdigit() or len(value) > 18:
        raise ValueError
    return int(value)


@chat_user_required
@require_GET
def history(request, pk):
    """Historial paginado en JSON: ?before=<id> (más antiguos) o ?after=<id> (reconexión)."""
    conversation, _ = _conversation_or_403(request.user, pk)
    try:
        before = _positive_int(request.GET.get('before'))
        after = _positive_int(request.GET.get('after'))
    except ValueError:
        return HttpResponseBadRequest('Parámetro de paginación no válido.')
    page, has_more = services.history(conversation, before=before, after=after)
    return JsonResponse({'messages': page, 'has_more': has_more})


def _open(event, kind, buyer=None):
    conversation, _ = Conversation.objects.get_or_create(
        event=event, kind=kind, buyer=buyer,
    )
    return redirect('chat:conversation', pk=conversation.pk)


def _no_ticket(request, event):
    messages.error(
        request,
        'Necesitas una entrada emitida de este evento para usar su chat.',
    )
    return redirect('events:detail', pk=event.pk)


@chat_user_required
@require_GET
def open_event(request, event_id):
    """Acceso directo desde un evento o ticket: el comprador va a su chat privado
    con el organizador; el organizador (o un administrador) va a la sala general."""
    event = get_object_or_404(Event, pk=event_id)
    role = event_role(request.user, event)
    if role is None:
        return _no_ticket(request, event)
    if role == ROLE_BUYER:
        return _open(event, Conversation.Kind.PRIVATE, buyer=request.user)
    return _open(event, Conversation.Kind.GENERAL)


@chat_user_required
@require_GET
def open_general(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if event_role(request.user, event) is None:
        return _no_ticket(request, event)
    return _open(event, Conversation.Kind.GENERAL)


@chat_user_required
@require_GET
def open_with_buyer(request, event_id, user_id):
    """El organizador abre el chat privado con uno de los compradores de su evento."""
    event = get_object_or_404(Event, pk=event_id)
    if event_role(request.user, event) not in (ROLE_ORGANIZER, ROLE_MODERATOR):
        raise PermissionDenied
    buyer = get_object_or_404(User, pk=user_id)
    if buyer.pk == event.organizer_id or not has_ticket(buyer, event.pk):
        raise PermissionDenied
    return _open(event, Conversation.Kind.PRIVATE, buyer=buyer)

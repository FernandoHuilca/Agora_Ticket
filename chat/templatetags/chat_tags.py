from django import template

from chat.access import event_role

register = template.Library()


@register.simple_tag(takes_context=True)
def chat_event_role(context, event):
    """Rol del usuario actual en el chat del evento ('organizer', 'buyer',
    'moderator') o cadena vacía si no tiene acceso. Uso:
    {% chat_event_role event as chat_role %}"""
    request = context.get('request')
    user = getattr(request, 'user', None)
    return event_role(user, event) or ''

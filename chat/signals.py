from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .consumers import session_group


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def close_sockets_of_suspended_user(sender, instance, created, **kwargs):
    """Al suspender una cuenta se cierran de inmediato sus WebSockets abiertos."""
    if created or instance.is_active:
        return
    try:
        async_to_sync(get_channel_layer().group_send)(
            session_group(instance.pk), {'type': 'session.terminate'},
        )
    except Exception:
        # Sin channel layer disponible, el acceso igual se revalida en cada mensaje.
        pass

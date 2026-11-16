import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_asgi_app = get_asgi_application()

# Se importa después de inicializar Django porque carga modelos.
from chat.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # AllowedHostsOriginValidator rechaza handshakes cuyo Origin no esté en
    # ALLOWED_HOSTS (evita el secuestro de WebSocket entre sitios) y
    # AuthMiddlewareStack autentica con la cookie de sesión durante el handshake.
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})

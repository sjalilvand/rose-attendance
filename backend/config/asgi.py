"""ASGI entrypoint — served by gunicorn + uvicorn worker (backend/Dockerfile).

Protocol routing (messaging increment; docs/REQUIREMENTS.md section 21):
- http       → Django (DRF API, admin, health)
- websocket  → /ws/notifications/ (live decision notifications, per-user group)

The PWA passes its JWT access token as ?token=… because the browser WebSocket
API cannot set custom headers — see apps.messaging.ws_auth.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.messaging.routing import websocket_urlpatterns  # noqa: E402
from apps.messaging.ws_auth import JWTQueryAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTQueryAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)

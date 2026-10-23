"""ASGI entrypoint — served by gunicorn + uvicorn worker (backend/Dockerfile).

Django Channels will be added in the messaging increment (docs/REQUIREMENTS.md
section 21: WebSocket for chat/notifications); the plain-ASGI protocol layer
is intentionally used until then.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_asgi_application()

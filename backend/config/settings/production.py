"""Production settings — single-host controlled deployment (compose.yml).

Reads secrets from files mounted by Docker secrets:
- DJANGO_SECRET_KEY_FILE  -> /run/secrets/django_secret
- DB_PASSWORD_FILE        -> /run/secrets/db_password

Environment contract matches compose.yml + .env.example: DB_HOST, DB_PORT,
DB_NAME, DB_USER, REDIS_URL, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS
and the approved thresholds of schema.sql executive note #1.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403


def _read_secret(var_name: str, default: str = "") -> str:
    path = os.environ.get(var_name, "")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return default


DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"

SECRET_KEY = _read_secret("DJANGO_SECRET_KEY_FILE") or os.environ.get(
    "DJANGO_SECRET_KEY", ""
)
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY_FILE must point to a mounted secret in production"
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "rose_attendance"),
        "USER": os.environ.get("DB_USER", "rose_app"),
        "PASSWORD": _read_secret("DB_PASSWORD_FILE")
        or os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "db"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
    }
}

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_BROKER_URL = REDIS_URL  # noqa: F405

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# PWA origin(s) allowed for cross-origin API calls (section 32 browsers)
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")).split(",")
    if o.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

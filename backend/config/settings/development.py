"""Development settings — local machine, SQLite for fast/portable tests.

The geofence distance check is computed in Python (haversine) exactly as in
production, so tests exercise the same business logic without PostGIS.
"""
import os

from .base import *  # noqa: F401,F403
from .base import _env_int

DEBUG = True
ALLOWED_HOSTS = ["*"]

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-only-insecure-key-do-not-use-in-production"
)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CORS_ALLOW_ALL_ORIGINS = True

CELERY_TASK_ALWAYS_EAGER = True

REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}

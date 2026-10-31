"""Base settings — shared by development and production.

Approved thresholds of REQUIREMENTS v2.1 are environment-driven (schema.sql
executive note #1) and validated in `apps.core.validation.check_thresholds`
which runs at startup:

- CLOCK_SKEW_MINUTES          default 5    (± minutes, decision #4 of §34)
- CLOCK_SKEW_REVIEW_MINUTES   default 60   (beyond this, ambiguity -> NEEDS_REVIEW)
- OFFLINE_MAX_DAYS            default 7    (decision #4 of §34)
- RETENTION_SUMMARY_MONTHS    default 24   (decision #1/#6 of §34)
- SYNC_MAX_BATCH              default 100
- UPLOAD_MAX_MB               default 10
- LOCATION_MAX_ACCURACY_M     default 100  (LOW_ACCURACY boundary, section 7)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = "django-insecure-change-me"  # overridden by development/production
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    # Project apps
    "apps.core",
    "apps.orgs",
    "apps.people",
    "apps.scheduling",
    "apps.attendance",
    "apps.leaves",
    "apps.messaging",
    "apps.rules",
    "apps.reports",
    "apps.ops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Channels — live WebSocket notifications (messaging increment, section 21).
# Redis DB 1 keeps the channel layer separate from the Celery broker (DB 0).
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("CHANNEL_REDIS_URL", "redis://redis:6379/1")],
        },
    }
}

AUTH_USER_MODEL = "people.User"

# ---------------------------------------------------------------------------
# Localization — Jalali-based organisation, Tehran time (decision #2 of §34)
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static (admin assets only)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF / JWT
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "punch": "60/minute",   # normal punch cadence per user
        "sync": "20/minute",    # offline batch sync per user
        "auth": "30/minute",    # token issuance (brute-force backstop)
        "import": "10/minute",  # bulk personnel import (HR/ADMIN)
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Argon2id first (section 6 of the requirements document)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# Enforced on explicit validate_password() calls (self-service password change)
# and on the admin site; existing passwords are never touched.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
]

# ---------------------------------------------------------------------------
# SSO — generic OpenID Connect provider (Keycloak / Azure AD / Google / ...).
# Empty defaults keep password login as the only path until the operator opts
# in; every value is environment-driven (docs/GUIDE.md §SSO).
# ---------------------------------------------------------------------------
SSO_ENABLED = os.environ.get("SSO_ENABLED", "0") == "1"
SSO_ISSUER = os.environ.get("SSO_ISSUER", "").strip()
SSO_CLIENT_ID = os.environ.get("SSO_CLIENT_ID", "").strip()
SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", "").strip()
SSO_LABEL = os.environ.get("SSO_LABEL", "سامانهٔ سازمانی").strip() or "سامانهٔ سازمانی"
SSO_SCOPES = os.environ.get("SSO_SCOPES", "openid profile email").strip()
SSO_AUTO_PROVISION = os.environ.get("SSO_AUTO_PROVISION", "1") == "1"
SSO_ADMIN_EMAILS = os.environ.get("SSO_ADMIN_EMAILS", "").strip()
# Public base URL of the API when it lives behind a different host than the
# request (reverse-proxy edge cases); normally empty.
SSO_PUBLIC_BASE_URL = os.environ.get("SSO_PUBLIC_BASE_URL", "").strip()
# Extra PWA origins allowed as post-login redirect targets (comma separated).
SSO_EXTRA_REDIRECT_ORIGINS = os.environ.get("SSO_EXTRA_REDIRECT_ORIGINS", "").strip()

# ---------------------------------------------------------------------------
# Rose Hub SSO (پروتکل BASIC رز هاب) — apps/people/rose_sso.py
# Secret را می‌توان با متغیر محیطی بازنویسی کرد؛ مقدار پیش‌فرض برای سازگاری
# با استقرار فعلی حفظ شده است (در مخزن عمومی نباید secret واقعی باشد).
# ---------------------------------------------------------------------------
ROSE_HUB_CLIENT_ID = os.environ.get("ROSE_HUB_CLIENT_ID", "rose-techno-8a4e1f").strip()
ROSE_HUB_CLIENT_SECRET = os.environ.get(
    "ROSE_HUB_CLIENT_SECRET",
    "4b8e2f6a0d1c5e93a7f3b9d1c0e6f428b5a9d3e1c7f5a0b2d8e4c6f0a2b7d139",
).strip()
ROSE_HUB_ISSUER = os.environ.get("ROSE_HUB_ISSUER", "rose-hub").strip()
# اعتبار توکن یک‌بارمصرف رز هاب (ثانیه) — مطابق سند پروتکل
try:
    ROSE_HUB_TOKEN_TTL_SECONDS = int(os.environ.get("ROSE_HUB_TOKEN_TTL_SECONDS", "300"))
except ValueError:
    ROSE_HUB_TOKEN_TTL_SECONDS = 300

# Account lockout (users.failed_attempts / locked_until, section 6)
LOCKOUT_MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# ---------------------------------------------------------------------------
# CORS — React PWA origin (section 32: Chrome/Edge last two + WebView)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = []
CORS_ALLOW_CREDENTIALS = False

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "Asia/Tehran"
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = None

# ---------------------------------------------------------------------------
# Approved operational thresholds (environment-overridable)
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    import os

    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


APP_THRESHOLDS = {
    "CLOCK_SKEW_MINUTES": _env_int("CLOCK_SKEW_MINUTES", 5),
    "CLOCK_SKEW_REVIEW_MINUTES": _env_int("CLOCK_SKEW_REVIEW_MINUTES", 60),
    "OFFLINE_MAX_DAYS": _env_int("OFFLINE_MAX_DAYS", 7),
    "RETENTION_SUMMARY_MONTHS": _env_int("RETENTION_SUMMARY_MONTHS", 24),
    "SYNC_MAX_BATCH": _env_int("SYNC_MAX_BATCH", 100),
    "UPLOAD_MAX_MB": _env_int("UPLOAD_MAX_MB", 10),
    "LOCATION_MAX_ACCURACY_M": _env_int("LOCATION_MAX_ACCURACY_M", 100),
}

# Default geofence radii (decision #3 of §34) — metres
GEOFENCE_RADIUS_DEFAULT_CITY = 150
GEOFENCE_RADIUS_DEFAULT_CLINIC = 300
GEOFENCE_RADIUS_MIN = 50
GEOFENCE_RADIUS_MAX = 1000

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "console"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

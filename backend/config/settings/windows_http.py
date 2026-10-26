"""Windows no-Docker deployment — HTTP phase (no TLS yet).

Inherits everything from config.settings.production and relaxes only the
three flags that make Django admin / sessions unusable over plain HTTP:

- SESSION_COOKIE_SECURE : sessionid cookie must be sent over http://
- CSRF_COOKIE_SECURE    : csrftoken cookie must be sent over http://
- SECURE_HSTS_SECONDS   : HSTS makes no sense before TLS exists

The PWA itself uses JWT (Authorization header) and is unaffected either way.

After a valid TLS certificate is provisioned (see docs/WINDOWS-DEPLOY-NODOCKER.md,
section "SSL"), switch DJANGO_SETTINGS_MODULE in C:\\rose-stack\\rose-backend.env
back to `config.settings.production` and restart the RoseApi service.
"""
from .production import *  # noqa: F401,F403

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

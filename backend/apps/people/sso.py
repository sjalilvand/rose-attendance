"""Generic OpenID Connect (SSO) client — authorization-code flow (section 6).

Provider-agnostic: any OIDC provider (Keycloak, Azure AD/Entra, Google,
Authentik, Zitadel, ...) works through its discovery document. Only the
issuer URL plus client credentials are configured via environment:

    SSO_ENABLED, SSO_ISSUER, SSO_CLIENT_ID, SSO_CLIENT_SECRET,
    SSO_LABEL, SSO_SCOPES, SSO_AUTO_PROVISION, SSO_ADMIN_EMAILS,
    SSO_PUBLIC_BASE_URL

Security notes
--------------
- The browser only ever talks to /auth/sso/login/ and /auth/sso/callback/;
  client_secret stays server-side.
- `state` is a random single-use value persisted in `sso_login_states`
  (DB-backed so all workers agree) with a 15-minute TTL.
- Tokens are handed back to the PWA through the URL *fragment* (#...), which
  browsers never send to any server and which the callback page clears.
- Code exchange + userinfo calls go directly to the token endpoint over TLS
  with our client credentials, so the returned claims are trusted per RFC
  6749 §4.1 without local id_token signature verification.
- Uses only the standard library (urllib) — no new dependency in the
  hash-locked requirements.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .models import DeviceSession, Employee, Role, RoleAssignment, SSOIdentity, SSOLoginState

STATE_TTL_MINUTES = 15


class SSOError(Exception):
    """Raised with a Persian, user-safe message."""


# ---------------------------------------------------------------------------
# Settings accessors (read at call time so tests can override_settings)
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    return bool(
        getattr(settings, "SSO_ENABLED", False)
        and getattr(settings, "SSO_ISSUER", "")
        and getattr(settings, "SSO_CLIENT_ID", "")
        and getattr(settings, "SSO_CLIENT_SECRET", "")
    )


def provider_label() -> str:
    return getattr(settings, "SSO_LABEL", "سامانهٔ سازمانی")


def _admin_emails() -> set[str]:
    raw = getattr(settings, "SSO_ADMIN_EMAILS", "") or ""
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------
def _http_json(url: str, data: dict[str, str] | None = None, headers: dict[str, str] | None = None,
               timeout: int = 10) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network, HTTP, JSON errors alike
        raise SSOError("ارتباط با سامانهٔ ورود یکپارچه برقرار نشد.") from exc


def discovery() -> dict[str, Any]:
    """Cached OpenID discovery document; cached 1h per process."""
    cache = getattr(settings, "SSO_DISCOVERY_CACHE", None)
    issuer: str = settings.SSO_ISSUER.rstrip("/")
    if isinstance(cache, dict) and cache.get("issuer") == issuer and \
            (timezone.now() - cache["at"]).total_seconds() < 3600:
        return cache["doc"]
    doc = _http_json(f"{issuer}/.well-known/openid-configuration")
    settings.SSO_DISCOVERY_CACHE = {"issuer": issuer, "at": timezone.now(), "doc": doc}
    return doc


# ---------------------------------------------------------------------------
# Redirect allow-list
# ---------------------------------------------------------------------------
def allowed_origins() -> set[str]:
    origins: set[str] = set()
    for group in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        origins.update(o.rstrip("/") for o in getattr(settings, group, []) or [])
    extra = getattr(settings, "SSO_EXTRA_REDIRECT_ORIGINS", "") or ""
    origins.update(o.strip().rstrip("/") for o in extra.split(",") if o.strip())
    return origins


def validate_redirect(redirect: str) -> str:
    """Accepts a PWA origin and returns it normalized; raises SSOError otherwise."""
    parsed = urllib.parse.urlparse(redirect or "")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if not origin or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SSOError("آدرس بازگشت نامعتبر است.")
    allowed = allowed_origins()
    if getattr(settings, "DEBUG", False):
        if parsed.scheme == "http" and parsed.netloc.split(":")[0] in {"localhost", "127.0.0.1"}:
            return origin
    if origin not in allowed:
        raise SSOError("آدرس بازگشت مجاز نیست.")
    return origin


# ---------------------------------------------------------------------------
# Flow steps
# ---------------------------------------------------------------------------
def start_login(request, redirect_origin: str) -> str:
    """Creates a single-use state row and returns the provider authorize URL."""
    SSOLoginState.sweep()
    doc = discovery()
    state = secrets.token_urlsafe(48)
    SSOLoginState.objects.create(
        state=state,
        redirect_to=redirect_origin,
        expires_at=timezone.now() + timezone.timedelta(minutes=STATE_TTL_MINUTES),
    )
    params = {
        "response_type": "code",
        "client_id": settings.SSO_CLIENT_ID,
        "redirect_uri": callback_uri(request),
        "scope": getattr(settings, "SSO_SCOPES", "openid profile email"),
        "state": state,
    }
    return f"{doc['authorization_endpoint']}?{urllib.parse.urlencode(params)}"


def callback_uri(request) -> str:
    base = getattr(settings, "SSO_PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/api/v1/auth/sso/callback/"
    return request.build_absolute_uri("/api/v1/auth/sso/callback/")


def consume_state(state: str) -> str:
    """Single-use consumption; returns the redirect origin or raises."""
    row = SSOLoginState.objects.filter(state=state).first()
    if row is None:
        raise SSOError("نشست ورود یکپارچه نامعتبر است.")
    redirect_to = row.redirect_to
    row.delete()
    if row.is_expired():
        raise SSOError("نشست ورود یکپارچه منقضی شده؛ دوباره تلاش کنید.")
    return redirect_to


def exchange_code(code: str, redirect_uri: str) -> str:
    doc = discovery()
    token = _http_json(
        doc["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.SSO_CLIENT_ID,
            "client_secret": settings.SSO_CLIENT_SECRET,
        },
    )
    access = token.get("access_token", "")
    if not access:
        raise SSOError("پاسخ نامعتبر از سامانهٔ ورود یکپارچه.")
    return access


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    doc = discovery()
    return _http_json(doc["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"})


def find_or_provision_user(claims: dict[str, Any]) -> tuple[Any, bool]:
    """Maps provider claims to a local user (links by email, provisions if allowed)."""
    subject = str(claims.get("sub", "")).strip()
    if not subject:
        raise SSOError("پاسخ سامانهٔ ورود فاقد شناسهٔ کاربر است.")
    email = str(claims.get("email", "") or "").strip()
    provider = settings.SSO_ISSUER.rstrip("/")

    identity = SSOIdentity.objects.filter(provider=provider, subject=subject).select_related("user").first()
    if identity is not None:
        if email and identity.email != email:
            identity.email = email
            identity.save(update_fields=["email", "updated_at"])
        return identity.user, False

    # Link to an existing local account whose username equals the email claim.
    user = None
    if email:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(username=email).first()
    if user is not None:
        SSOIdentity.objects.create(user=user, provider=provider, subject=subject, email=email)
        return user, False

    if not getattr(settings, "SSO_AUTO_PROVISION", True):
        raise SSOError("حساب شما در سامانه یافت نشد؛ با منابع انسانی تماس بگیرید.")

    user = _provision_user(claims, subject=subject, email=email, provider=provider)
    return user, True


def _provision_user(claims: dict[str, Any], subject: str, email: str, provider: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    base_username = email or f"sso_{subject}"
    username = base_username[:60]
    suffix = 0
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base_username[:55]}-{suffix}"
    is_admin = email.lower() in _admin_emails()
    user = User.objects.create_user(
        username=username,
        password=None,  # SSO users log in through the provider
        is_staff=is_admin,
        is_superuser=is_admin,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    SSOIdentity.objects.create(user=user, provider=provider, subject=subject, email=email)
    if not is_admin:
        # Default business role so messaging/leave endpoints work from day one.
        role = Role.objects.filter(code="EMPLOYEE").first()
        if role is not None:
            RoleAssignment.objects.create(
                user=user, role=role, valid_from=timezone.localdate()
            )
    return user


def issue_session(request, user) -> tuple[str, str]:
    """JWT pair + device session row, mirroring the password-login contract."""
    from rest_framework_simplejwt.settings import api_settings as jwt_settings

    refresh = RefreshToken.for_user(user)
    refresh["employee_id"] = user.employee_id
    refresh["roles"] = user.active_role_codes()
    refresh_str = str(refresh)
    DeviceSession.objects.create(
        user=user,
        refresh_token_hash=hashlib.sha256(refresh_str.encode()).hexdigest(),
        device_label=str(request.headers.get("User-Agent", ""))[:120],
        platform="PWA",
        expires_at=timezone.now() + jwt_settings.REFRESH_TOKEN_LIFETIME,
    )
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])
    return str(refresh.access_token), refresh_str

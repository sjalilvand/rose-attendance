"""ورود یکپارچه (SSO) با رز هاب — Rose Hub

پروتکل نسخه پایه (BASIC) طبق «docs/sso-integration-fa.md» در مخزن رز هاب:
رز هاب کاربرِ احرازهویت‌شده را با ``?sso_token=<JWT HS256>`` به این سامانه
برمی‌گرداند. توکن با clientSecret اختصاصی سامانه (rose-techno-8a4e1f) امضا
شده، اعتبار ۵ دقیقه دارد و فقط یک‌بار باید مصرف شود. پس از اعتبارسنجی،
حساب کاربر پیدا یا ساخته شده و جفت‌توکن SimpleJWT صادر می‌شود — یعنی کاربر
با همان هویت رز هاب و بدون گذرواژه جداگانه وارد سامانه حضور و غیاب می‌شود.

مسیر: ``GET/POST /api/v1/auth/rose-sso/``

نکته: حساب SSO بدون پرونده پرسنلی (employee) ساخته می‌شود — مانند کاربران
سیستمی؛ ورود و مشاهده پروفایل کار می‌کند و اتصال به پرونده پرسنلی توسط
مدیر سامانه از پنل مدیریت انجام می‌شود.
"""

from __future__ import annotations

import secrets

import jwt
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

ROSE_HUB_CLIENT_ID = "rose-techno-8a4e1f"
ROSE_HUB_CLIENT_SECRET = "4b8e2f6a0d1c5e93a7f3b9d1c0e6f428b5a9d3e1c7f5a0b2d8e4c6f0a2b7d139"
ROSE_HUB_ISSUER = "rose-hub"
CLOCK_LEEWAY_SECONDS = 60


class RoseHubTokenError(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "توکن ورود یکپارچه نامعتبر یا منقضی است؛ دوباره از رز هاب وارد شوید."


def _decode_rose_hub_token(raw: str) -> dict:
    """اعتبارسنجی امضا، مخاطب (aud)، صادرکننده (iss) و انقضای توکن رز هاب."""
    try:
        return jwt.decode(
            raw,
            ROSE_HUB_CLIENT_SECRET,
            algorithms=["HS256"],
            audience=ROSE_HUB_CLIENT_ID,
            issuer=ROSE_HUB_ISSUER,
            leeway=CLOCK_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError:
        raise RoseHubTokenError()


def _unique_username(base: str) -> str:
    User = get_user_model()
    base = base[:60] or "rosehub"
    candidate = base
    i = 1
    while User.objects.filter(username=candidate).exists():
        i += 1
        candidate = f"{base[:55]}{i}"
    return candidate


def _login_from_rose_hub(raw_token: str) -> dict:
    payload = _decode_rose_hub_token(raw_token)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise ValidationError({"detail": "توکن ورود یکپارچه فاقد ایمیل است."})

    User = get_user_model()
    # نگاشت پایدار هویت رز هاب به حساب محلی: بخش قبل از @ ایمیل
    base = email.split("@")[0].replace(" ", "") or "rosehub"
    user = User.objects.filter(username=base).first()
    if user is None:
        user = User.objects.create_user(
            username=_unique_username(base),
            password=secrets.token_hex(32),  # گذرواژه تصادفی غیرقابل حدس
        )
    if not user.is_active:
        raise ValidationError({"detail": "حساب کاربری شما غیرفعال است."})

    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "username": user.username,
        "via": "rose-hub",
    }


class RoseSSOView(APIView):
    """دریافت توکن یک‌بارمصرف رز هاب و صدور نشست سامانه حضور و غیاب."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        raw = request.query_params.get("sso_token", "")
        if not raw:
            return Response(
                {"detail": "پارامتر sso_token الزامی است.", "launch": "rose-hub"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_login_from_rose_hub(raw))

    def post(self, request: Request) -> Response:
        raw = (request.data or {}).get("token", "") if isinstance(request.data, dict) else ""
        if not raw:
            return Response(
                {"detail": "فیلد token الزامی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_login_from_rose_hub(raw))

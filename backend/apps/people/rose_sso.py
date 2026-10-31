"""ورود یکپارچه (SSO) با رز هاب — Rose Hub

پروتکل نسخه پایه (BASIC) طبق «docs/sso-integration-fa.md» در مخزن رز هاب:
رز هاب کاربرِ احرازهویت‌شده را با ``?sso_token=<JWT HS256>`` به این سامانه
برمی‌گرداند. توکن با clientSecret اختصاصی سامانه امضا شده، اعتبار محدود دارد
و فقط یک‌بار باید مصرف شود (الان سمت سرور هم تضمین می‌شود). پس از اعتبارسنجی،
حساب کاربر پیدا یا ساخته شده و جفت‌توکن SimpleJWT صادر می‌شود — یعنی کاربر
با همان هویت رز هاب و بدون گذرواژه جداگانه وارد سامانه حضور و غیاب می‌شود.

مسیر: ``GET/POST /api/v1/auth/rose-sso/``

بازبینی امنیتی (۱۴۰۵/۰۸):
- clientSecret از تنظیمات/متغیر محیطی خوانده می‌شود (ROSE_HUB_CLIENT_SECRET)
  و دیگر هاردکد نیست؛ مقدار پیش‌فرض برای سازگاری با استقرار فعلی حفظ شده.
- یک‌بارمصرف‌بودن توکن سمت سرور تضمین شده (جدول sso_used_tokens + هش SHA-256).
- نگاشت هویت پایدار شد: نخست جدول sso_identities (provider=rose-hub,
  subject=ایمیل) بررسی می‌شود؛ بعد نام‌کاربری برابر ایمیل کامل، بعد بخش قبل
  از @ (رفتار قبلی)؛ در نخستین ورود، هویت ثبت می‌شود تا وابسته به نام
  کاربریِ قابل تغییر نباشد.
- حساب‌های SSO تازه گذرواژهٔ غیرقابل‌استفاده می‌گیرند (نمیشود با گذرواژه وارد
  شد) و ثبت نشست دستگاه (sessions) و last_login هم انجام می‌شود.

نکته: حساب SSO بدون پرونده پرسنلی (employee) ساخته می‌شود — مانند کاربران
سیستمی؛ ورود و مشاهده پروفایل کار می‌کند و اتصال به پرونده پرسنلی توسط
مدیر سامانه از پنل مدیریت انجام می‌شود.
"""

from __future__ import annotations

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SSOIdentity, SSOUsedToken
from .sso import issue_session

CLOCK_LEEWAY_SECONDS = 60


class RoseHubTokenError(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "توکن ورود یکپارچه نامعتبر یا منقضی است؛ دوباره از رز هاب وارد شوید."


def _decode_rose_hub_token(raw: str) -> dict:
    """اعتبارسنجی امضا، مخاطب (aud)، صادرکننده (iss) و انقضای توکن رز هاب."""
    try:
        return jwt.decode(
            raw,
            settings.ROSE_HUB_CLIENT_SECRET,
            algorithms=["HS256"],
            audience=settings.ROSE_HUB_CLIENT_ID,
            issuer=settings.ROSE_HUB_ISSUER,
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


def _login_from_rose_hub(request: Request, raw_token: str) -> dict:
    if not SSOUsedToken.try_consume(raw_token, provider=settings.ROSE_HUB_ISSUER):
        # توکن یک‌بارمصرف است؛ استفادهٔ مجدد (حتی در پنجرهٔ اعتبار) رد می‌شود.
        raise RoseHubTokenError()

    payload = _decode_rose_hub_token(raw_token)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise ValidationError({"detail": "توکن ورود یکپارچه فاقد ایمیل است."})

    User = get_user_model()
    provider = settings.ROSE_HUB_ISSUER
    user = None

    # ۱) نگاشت پایدار از سابقهٔ ورودهای قبلی
    identity = (
        SSOIdentity.objects.filter(provider=provider, subject=email)
        .select_related("user")
        .first()
    )
    if identity is not None:
        user = identity.user
    if user is None:
        # ۲) نام‌کاربری برابر ایمیل کامل (قرارداد حساب‌های سازمانی)
        user = User.objects.filter(username=email).first()
    if user is None:
        # ۳) رفتار قبلی: بخش قبل از @ ایمیل
        base = email.split("@")[0].replace(" ", "") or "rosehub"
        user = User.objects.filter(username=base).first()
    if user is None:
        # ۴) ساخت حساب تازه — بدون گذرواژهٔ محلی قابل‌استفاده
        user = User.objects.create_user(username=_unique_username(base), password=None)
        user.set_unusable_password()
        user.save(update_fields=["password"])
    if not user.is_active:
        raise ValidationError({"detail": "حساب کاربری شما غیرفعال است."})

    # ثبت/به‌روزرسانی هویت پایدار برای ورودهای بعدی
    if identity is None:
        SSOIdentity.objects.get_or_create(
            provider=provider, subject=email,
            defaults={"user": user, "email": email},
        )

    access, refresh = issue_session(request, user)
    return {
        "access": access,
        "refresh": refresh,
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
        return Response(_login_from_rose_hub(request, raw))

    def post(self, request: Request) -> Response:
        raw = (request.data or {}).get("token", "") if isinstance(request.data, dict) else ""
        if not raw:
            return Response(
                {"detail": "فیلد token الزامی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_login_from_rose_hub(request, raw))

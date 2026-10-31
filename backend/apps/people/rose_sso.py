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

import json as _json
import logging
import urllib.error
import urllib.request

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

logger = logging.getLogger(__name__)


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


def _sync_sso_profile(user, payload: dict) -> dict:
    """فاز ۶۵ — بروزرسانی مشخصات کامل کاربر از توکن رز هاب.

    رز هاب منبع حقیقت است: نام و نام خانوادگی، موبایل، کد ملی، استان،
    کد استان و کلینک محل خدمت در هر ورود یکپارچه بروزرسانی می‌شوند؛
    مقدار خالی توکن یعنی در رز هاب ثبت نشده — مقدار محلی پاک نمی‌شود.
    """
    mapping = {
        "full_name": (payload.get("name") or "").strip()[:200],
        "mobile": (payload.get("mobile") or "").strip()[:20],
        "national_id": (payload.get("nationalId") or "").strip()[:15],
        "province": (payload.get("province") or "").strip()[:80],
        "province_code": (payload.get("provinceCode") or "").strip()[:10],
        "clinic": (payload.get("clinic") or "").strip()[:200],
    }
    changed = []
    for field, value in mapping.items():
        if value and getattr(user, field, "") != value:
            setattr(user, field, value)
            changed.append(field)
    if changed:
        user.save(update_fields=[*changed, "updated_at"])

    # فاز ۶۵ (تکمیل) — پروندهٔ پرسنلی پیوند‌شده نیز از منبع حقیقت رز هاب
    # بروزرسانی می‌شود؛ چون UI (نوار بالا و صفحهٔ پروفایل) نام و موبایل را
    # از employee می‌خواند و در غیر این صورت نام قدیمیِ پرونده نمایش
    # داده می‌شد. نام کامل به نام/نام خانوادگی شکسته می‌شود (نخستین
    # واژه = نام، باقی = نام خانوادگی) و مقدار خالی توکن مقدار محلی
    # پرونده را پاک نمی‌کند.
    employee = getattr(user, "employee", None)
    if employee is not None:
        emp_changed = []
        parts = mapping["full_name"].split()
        if parts:
            first_name = parts[0][:80]
            last_name = " ".join(parts[1:])[:80]
            if first_name and employee.first_name != first_name:
                employee.first_name = first_name
                emp_changed.append("first_name")
            if last_name and employee.last_name != last_name:
                employee.last_name = last_name
                emp_changed.append("last_name")
        if mapping["mobile"] and employee.mobile != mapping["mobile"]:
            employee.mobile = mapping["mobile"]
            emp_changed.append("mobile")
        if (
            mapping["national_id"]
            and employee.national_id != mapping["national_id"][:10]
        ):
            employee.national_id = mapping["national_id"][:10]
            emp_changed.append("national_id")
        if emp_changed:
            employee.save(update_fields=[*emp_changed, "updated_at"])
    return mapping


def _fetch_rose_hub_profile(username: str) -> dict | None:
    """استعلام مشخصات کاربر از رز هاب (سرویس‌به‌سرویس) — POST /api/sso/profile.

    با clientId/clientSecret اختصاصی همین سامانه احراز می‌شود؛ در صورت
    در دسترس نبودن رز هاب یا پیدا نشدن کاربر، None برمی‌گردد (هرگز خطا
    نمی‌اندازد تا ورود محلی به‌خوبی رز هاب کار نکند).
    """
    base = (getattr(settings, "ROSE_HUB_URL", "") or "").strip().rstrip("/")
    username = (username or "").strip()
    if not base or not username:
        return None
    body = _json.dumps(
        {
            "clientId": settings.ROSE_HUB_CLIENT_ID,
            "clientSecret": settings.ROSE_HUB_CLIENT_SECRET,
            "username": username,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/sso/profile",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec - آدرس از تنظیمات سرور
            payload = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # ۴۰۱ یعنی مسیر/اعتبارنامه رد شده (مثلاً میان‌افزار رز هاب مسیر را
        # نشناسد)؛ ۴۰۴ یعنی کاربر در رز هاب یافت نشد. برای عیب‌یابی ثبت می‌شود.
        logger.warning(
            "استعلام پروفایل از رز هاب ناموفق بود (username=%s, HTTP %s)",
            username, exc.code,
        )
        return None
    except Exception as exc:  # قطعی شبکه، timeout و…
        logger.warning(
            "استعلام پروفایل از رز هاب ناموفق بود (username=%s): %s", username, exc
        )
        return None
    if not isinstance(payload, dict) or not payload.get("found"):
        logger.info(
            "رز هاب کاربر را برای استعلام پروفایل نیافت (username=%s)", username
        )
        return None
    profile = payload.get("profile")
    return profile if isinstance(profile, dict) else None


def fetch_and_apply_hub_profile(user) -> dict | None:
    """استعلام و اعمال مشخصات رز هاب روی حساب کاربر.

    dict مشخصات اعمال‌شده برمی‌گردد؛ در دسترس نبودن رز هاب یا یافت نشدن
    کاربر → None (تماس‌گیرنده پیام مناسب نشان می‌دهد — خطا هرگز به بیرون
    نشت نمی‌کند).
    """
    try:
        profile = _fetch_rose_hub_profile(getattr(user, "username", "") or "")
    except Exception:  # pragma: no cover - محافظت کامل
        return None
    if not profile:
        return None
    try:
        _sync_sso_profile(user, profile)
    except Exception:  # pragma: no cover - همگام‌سازی هرگز نشکند
        return None
    return profile


def sync_rose_hub_profile_for_user(user) -> bool:
    """همگام‌سازی پروفایل کاربر از رز هاب برای ورودهای محلی (گذرواژه‌ای).

    رز هاب منبع حقیقت مشخصات است؛ با هر ورود موفق با گذرواژه، مشخصات کامل
    (نام، موبایل، کد ملی، استان، کد استان، کلینک) استعلام و روی حساب و
    پروندهٔ پرسنلی پیوند‌شده اعمال می‌شود. ناموفق بودن استعلام (قطعی شبکه
    و…) هرگز مانع ورود نمی‌شود.
    """
    return fetch_and_apply_hub_profile(user) is not None


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

    # فاز ۶۵: همگام‌سازی پروفایل کامل (نام، موبایل، کد ملی، استان، کلینک)
    profile = _sync_sso_profile(user, payload)

    access, refresh = issue_session(request, user)
    return {
        "access": access,
        "refresh": refresh,
        "username": user.username,
        "profile": profile,
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

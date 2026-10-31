"""Auth + profile API — JWT with account lockout (section 6)."""
from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .importer import ImportFormatError, build_template, import_employees
from .models import DeviceSession, User


class TokenObtainPairWithLockoutSerializer(TokenObtainPairSerializer):
    """Adds employee/role claims and enforces failed-attempt lockout."""

    platform = serializers.ChoiceField(choices=DeviceSession._meta.get_field("platform").choices, required=False)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["employee_id"] = user.employee_id
        token["roles"] = user.active_role_codes()
        return token

    def validate(self, attrs):
        username = attrs.get(self.username_field)
        try:
            user = User.objects.filter(username=username).first()
        except User.DoesNotExist:  # pragma: no cover
            user = None
        lock = (settings.LOCKOUT_MAX_ATTEMPTS, settings.LOCKOUT_MINUTES)
        if user is not None and user.is_locked():
            raise serializers.ValidationError(
                "حساب موقتاً قفل است؛ بعداً تلاش کنید.", code="ACCOUNT_LOCKED"
            )
        try:
            data = super().validate(attrs)
        except (serializers.ValidationError, AuthenticationFailed):
            # simplejwt raises AuthenticationFailed (401) for bad credentials
            if user is not None:
                user.register_failed_attempt(*lock)
            raise
        user.reset_failed_attempts()
        user.last_login = timezone.now()
        user.save(update_fields=["last_login", "updated_at"])

        # Session registry (schema table `sessions`) — refresh hash + device.
        platform = attrs.get("platform", "PWA")
        refresh = data.get("refresh", "")
        DeviceSession.objects.create(
            user=user,
            refresh_token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
            device_label=str(self.context["request"].headers.get("User-Agent", ""))[:120],
            platform=platform,
            expires_at=timezone.now() + settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"],
        )
        data.update(
            {
                "employee_id": user.employee_id,
                "personnel_code": (
                    user.employee.personnel_code if user.employee_id else None
                ),
                "full_name": (
                    user.employee.full_name if user.employee_id else user.username
                ),
                "roles": sorted(
                    set(user.active_role_codes()) | ({"ADMIN"} if user.is_superuser else set())
                ),
            }
        )
        return data


class TokenObtainPairWithLockoutView(TokenObtainPairView):
    serializer_class = TokenObtainPairWithLockoutSerializer
    throttle_scope = "auth"


class TokenRefreshWithDeviceView(TokenRefreshView):
    """Refresh that keeps the device session's last-seen fresh."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            refresh = request.data.get("refresh", "")
            if refresh:
                DeviceSession.objects.filter(
                    refresh_token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
                    revoked_at__isnull=True,
                ).update(last_seen_at=timezone.now())
        return response


class MeView(APIView):
    """GET /api/v1/me/ — profile + roles + branch geo (PWA bootstrapping)."""

    def get(self, request):
        from django.db.models import Q

        user: User = request.user
        employee = user.employee if user.employee_id else None
        today = timezone.localdate()
        branches: list[tuple[object, bool]] = []
        if employee is not None:
            if employee.home_branch is not None:
                branches.append((employee.home_branch, True))
            assigned = employee.branch_assignments.filter(
                is_allowed=True, valid_from__lte=today
            ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today)).select_related("branch")
            for assignment in assigned:
                branches.append((assignment.branch, False))
        employee_payload = (
            {
                "id": employee.id,
                "personnel_code": employee.personnel_code,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "full_name": employee.full_name,
                "employment_status": employee.employment_status,
                "home_branch_id": employee.home_branch_id,
                "home_branch_name": (
                    employee.home_branch.name if employee.home_branch_id else None
                ),
                "job_title": employee.job_title,
                "mobile": employee.mobile,
            }
            if employee is not None
            else None
        )
        return Response(
            {
                "username": user.username,
                "server_time": timezone.now(),
                "employee": employee_payload,
                "roles": sorted(
                    set(user.active_role_codes()) | ({"ADMIN"} if user.is_superuser else set())
                ),
                "auth_method": "SSO" if not user.has_usable_password() or user.sso_identities.exists() else "PASSWORD",
                "last_login_at": user.last_login,
                "branches": [
                    {
                        "id": branch.id,
                        "code": branch.code,
                        "name": branch.name,
                        "geo_latitude": branch.geo_latitude,
                        "geo_longitude": branch.geo_longitude,
                        "geo_radius_m": branch.geo_radius_m,
                        "is_home": is_home,
                    }
                    for branch, is_home in branches
                ],
            }
        )


MOBILE_RE = re.compile(r"^09\d{9}$")


class ProfileUpdateView(APIView):
    """POST /api/v1/auth/profile/ — an employee edits their own mobile number."""

    def post(self, request):
        user: User = request.user
        if user.employee_id is None:
            return Response(
                {"detail": "پروندهٔ پرسنلی برای این حساب وجود ندارد.", "code": "NO_EMPLOYEE"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mobile = str(request.data.get("mobile", "") or "").strip()
        if mobile and not MOBILE_RE.fullmatch(mobile):
            return Response(
                {"detail": "شمارهٔ موبایل باید ۱۱ رقم و با ۰۹ شروع شود.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        employee = user.employee
        employee.mobile = mobile
        employee.save(update_fields=["mobile", "updated_at"])
        return Response({"detail": "شمارهٔ موبایل به‌روزرسانی شد.", "mobile": mobile})


class PasswordChangeView(APIView):
    """POST /api/v1/auth/password/change/ — self-service password rotation."""

    throttle_scope = "auth"

    def post(self, request):
        user: User = request.user
        current = str(request.data.get("current_password", "") or "")
        new = str(request.data.get("new_password", "") or "")
        if not user.has_usable_password():
            return Response(
                {"detail": "ورود شما از طریق SSO است و گذرواژهٔ محلی ندارید.", "code": "SSO_ONLY"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not current or not user.check_password(current):
            return Response(
                {"detail": "گذرواژهٔ فعلی نادرست است.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if current == new:
            return Response(
                {"detail": "گذرواژهٔ جدید نباید با گذرواژهٔ فعلی یکسان باشد.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new, user=user)
        except Exception:
            return Response(
                {"detail": "گذرواژهٔ جدید مناسب نیست؛ حداقل ۸ نویسه و غیرقابل حدس باشد.", "code": "WEAK"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new)
        user.failed_attempts = 0
        user.locked_until = None
        user.save(update_fields=["password", "failed_attempts", "locked_until", "updated_at"])
        return Response({"detail": "گذرواژه با موفقیت تغییر کرد."})


# ---------------------------------------------------------------------------
# Bulk personnel import — HR/ADMIN only (phase-3 item: بارگذاری Excel)
# ---------------------------------------------------------------------------
class PersonnelImportView(APIView):
    """POST /api/v1/people/import/ — multipart xlsx; form field dry_run=true."""

    throttle_scope = "import"

    def post(self, request):
        user: User = request.user
        if not (user.is_superuser or user.has_role("HR") or user.has_role("ADMIN")):
            return Response(
                {"detail": "این عملیات مخصوص منابع انسانی است.", "code": "FORBIDDEN"},
                status=status.HTTP_403_FORBIDDEN,
            )
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "فایل xlsx الزامی است.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run = str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes"}
        try:
            report = import_employees(upload.read(), dry_run=dry_run)
        except ImportFormatError as exc:
            return Response(
                {"detail": str(exc), "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(report)


class PersonnelImportTemplateView(APIView):
    """GET /api/v1/people/import/template/ — xlsx template download."""

    def get(self, request):
        payload = build_template()
        response = HttpResponse(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="personnel-import-template.xlsx"'
        return response

"""Auth + profile API — JWT with account lockout (section 6)."""
from __future__ import annotations

import hashlib

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from django.conf import settings

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
                "personnel_code": user.employee.personnel_code,
                "full_name": user.employee.full_name,
                "roles": user.active_role_codes(),
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
        employee = user.employee
        today = timezone.localdate()
        branches = []
        if employee.home_branch is not None:
            branches.append((employee.home_branch, True))
        assigned = employee.branch_assignments.filter(
            is_allowed=True, valid_from__lte=today
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today)).select_related("branch")
        for assignment in assigned:
            branches.append((assignment.branch, False))
        return Response(
            {
                "username": user.username,
                "server_time": timezone.now(),
                "employee": {
                    "id": employee.id,
                    "personnel_code": employee.personnel_code,
                    "first_name": employee.first_name,
                    "last_name": employee.last_name,
                    "full_name": employee.full_name,
                    "employment_status": employee.employment_status,
                    "home_branch_id": employee.home_branch_id,
                },
                "roles": sorted(
                    set(user.active_role_codes()) | ({"ADMIN"} if user.is_superuser else set())
                ),
                "branches": [
                    {
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

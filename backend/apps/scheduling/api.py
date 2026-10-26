"""Shift management API — CRUD + bulk upsert by code (HR/ADMIN writes).

Completes the import cycle together with orgs/api.py: the personnel workbook
accepts an optional `shift_code` that must already exist here. Shifts are the
calculation engine's input (grace/rest/crossing-midnight semantics live in
apps.scheduling.models.ScheduledShift and the §5 rules), so the API only
maintains the catalog — no assignment logic.

Contract:
- GET    /api/v1/scheduling/shifts/     list (branch, scope, search, page)
- POST   /api/v1/scheduling/shifts/     create               (HR/ADMIN)
- PATCH  /api/v1/scheduling/shifts/{id}/ merge-patch update   (HR/ADMIN)
- POST   /api/v1/scheduling/shifts/bulk/ {items, dry_run} upsert by code

`crosses_midnight` may be omitted — it auto-derives from end ≤ start so the
common night-shift paste (22:00 → 06:00) needs no extra column.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api_utils import (
    hr_write_guard,
    page_params,
    paginated_response,
    serializer_errors,
)
from apps.core.enums import RestMode
from apps.orgs.models import Branch
from apps.scheduling.models import Shift

SHIFT_UPDATE_FIELDS = (
    "name", "starts_at", "ends_at", "crosses_midnight",
    "rest_minutes", "rest_mode", "grace_minutes", "scope_branch",
)
REST_MODE_VALUES = [value for value, _label in RestMode.choices]
MAX_BULK_ITEMS = 5000


class ShiftUpsertSerializer(serializers.Serializer):
    code = serializers.SlugField(max_length=20)
    name = serializers.CharField(max_length=120)
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()
    crosses_midnight = serializers.BooleanField(required=False, allow_null=True, default=None)
    rest_minutes = serializers.IntegerField(required=False, min_value=0, default=0)
    rest_mode = serializers.ChoiceField(choices=REST_MODE_VALUES, required=False, default=RestMode.FIXED)
    grace_minutes = serializers.IntegerField(required=False, min_value=0, default=0)
    scope_branch_code = serializers.SlugField(
        max_length=20, required=False, allow_blank=True, allow_null=True, default=None
    )

    def validate_scope_branch_code(self, value):
        if not value:
            return None
        try:
            return Branch.objects.get(code=value)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError(f"شعبهٔ «{value}» یافت نشد.") from exc

    def validate(self, attrs):
        if attrs.get("crosses_midnight") is None:
            # Night-shift friendly default: end ≤ start ⇒ crossing midnight.
            attrs["crosses_midnight"] = attrs["ends_at"] <= attrs["starts_at"]
        return attrs


def _shift_kwargs(v: dict) -> dict:
    return {
        "name": v["name"],
        "starts_at": v["starts_at"],
        "ends_at": v["ends_at"],
        "crosses_midnight": v.get("crosses_midnight") or False,
        "rest_minutes": v.get("rest_minutes", 0),
        "rest_mode": v.get("rest_mode", RestMode.FIXED),
        "grace_minutes": v.get("grace_minutes", 0),
        "scope_branch": v.get("scope_branch_code"),
    }


def _serialize_shift(shift: Shift) -> dict:
    return {
        "id": shift.id,
        "code": shift.code,
        "name": shift.name,
        "starts_at": f"{shift.starts_at:%H:%M}",
        "ends_at": f"{shift.ends_at:%H:%M}",
        "crosses_midnight": shift.crosses_midnight,
        "rest_minutes": shift.rest_minutes,
        "rest_mode": shift.rest_mode,
        "grace_minutes": shift.grace_minutes,
        "scope_branch": shift.scope_branch.code if shift.scope_branch_id else None,
        "scope_branch_name": shift.scope_branch.name if shift.scope_branch_id else None,
    }


class ShiftViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = ShiftUpsertSerializer

    def get_queryset(self):
        qs = Shift.objects.select_related("scope_branch")
        params = self.request.query_params
        branch = (params.get("branch") or "").strip()
        if branch:
            qs = qs.filter(scope_branch__code=branch)
        scope = (params.get("scope") or "").strip().upper()
        if scope == "GLOBAL":
            qs = qs.filter(scope_branch__isnull=True)
        elif scope == "BRANCH":
            qs = qs.filter(scope_branch__isnull=False)
        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return qs.order_by("code")

    def list(self, request, *args, **kwargs):
        page, size = page_params(request)
        return paginated_response(self.get_queryset(), page, size, _serialize_shift)

    def create(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        ser = ShiftUpsertSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            shift = Shift.objects.create(code=ser.validated_data["code"], **_shift_kwargs(ser.validated_data))
        except IntegrityError:
            return Response(
                {"detail": f"شیغی با کد «{ser.validated_data['code']}» از قبل وجود دارد.",
                 "code": "DUPLICATE"},
                status=400,
            )
        return Response(_serialize_shift(shift), status=201)

    def partial_update(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        shift = self.get_object()
        current = {
            "code": shift.code,
            "name": shift.name,
            "starts_at": f"{shift.starts_at:%H:%M}",
            "ends_at": f"{shift.ends_at:%H:%M}",
            "crosses_midnight": shift.crosses_midnight,
            "rest_minutes": shift.rest_minutes,
            "rest_mode": shift.rest_mode,
            "grace_minutes": shift.grace_minutes,
            "scope_branch_code": shift.scope_branch.code if shift.scope_branch_id else None,
        }
        payload = {k: v for k, v in (request.data or {}).items()}
        ser = ShiftUpsertSerializer(data={**current, **payload})
        ser.is_valid(raise_exception=True)
        for field, value in _shift_kwargs(ser.validated_data).items():
            setattr(shift, field, value)
        try:
            shift.save()
        except IntegrityError:
            return Response({"detail": "کد شیفت تکراری است.", "code": "DUPLICATE"}, status=400)
        return Response(_serialize_shift(shift))

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        payload = request.data if isinstance(request.data, dict) else {}
        items = payload.get("items") if isinstance(payload, dict) else request.data
        if not isinstance(items, list):
            return Response({"detail": "آرایهٔ items الزامی است.", "code": "INVALID"}, status=400)
        if len(items) > MAX_BULK_ITEMS:
            return Response(
                {"detail": f"حداکثر {MAX_BULK_ITEMS} ردیف در هر درخواست.", "code": "INVALID"},
                status=400,
            )
        dry_run = isinstance(payload, dict) and str(payload.get("dry_run", "")).lower() in {"1", "true", "yes"}

        errors: list[dict] = []
        to_create: list[Shift] = []
        to_update: list[Shift] = []
        created = updated = 0
        shift_map = {s.code: s for s in Shift.objects.select_related("scope_branch")}
        seen: set[str] = set()

        for n, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                errors.append({"row": n, "code": "", "message": "هر ردیف باید آبجکت باشد."})
                continue
            code = str(raw.get("code") or "").strip()
            if not code:
                errors.append({"row": n, "code": "", "message": "کد شیفت الزامی است."})
                continue
            if code in seen:
                errors.append({"row": n, "code": code, "message": "کد شیفت در فایل تکراری است."})
                continue
            seen.add(code)
            ser = ShiftUpsertSerializer(data=raw)
            if not ser.is_valid():
                errors.append({"row": n, "code": code, "message": serializer_errors(ser.errors)})
                continue
            current = shift_map.get(code)
            if current is None:
                created += 1
                if not dry_run:
                    to_create.append(Shift(code=code, **_shift_kwargs(ser.validated_data)))
            else:
                updated += 1
                if not dry_run:
                    for field, value in _shift_kwargs(ser.validated_data).items():
                        setattr(current, field, value)
                    to_update.append(current)

        if not dry_run and (to_create or to_update):
            with transaction.atomic():
                if to_create:
                    Shift.objects.bulk_create(to_create, batch_size=200)
                if to_update:
                    Shift.objects.bulk_update(to_update, fields=list(SHIFT_UPDATE_FIELDS), batch_size=200)

        return Response(
            {
                "total": len(items),
                "created": created,
                "updated": updated,
                "skipped": len(errors),
                "errors": errors[:50],
                "dry_run": dry_run,
            }
        )

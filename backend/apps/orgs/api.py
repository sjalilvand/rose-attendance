"""HR management API — regions & branches (CRUD + bulk upsert by code).

Closes the bulk-import cycle: the personnel workbook references *existing*
branch codes (importer guide: «سامانه شعبه را نمی‌سازد»), so HR must be able
to create and maintain ~850 branches first — one-by-one or pasted in bulk.

Contract (section 5 of the document):
- GET    /api/v1/org/regions/          list (filters: is_active, search)
- POST   /api/v1/org/regions/          create                 (HR/ADMIN)
- PATCH  /api/v1/org/regions/{id}/     merge-patch update      (HR/ADMIN)
- GET    /api/v1/org/branches/         list (region, is_active, search, page)
- POST   /api/v1/org/branches/         create                 (HR/ADMIN)
- PATCH  /api/v1/org/branches/{id}/    merge-patch update      (HR/ADMIN)
- POST   /api/v1/org/branches/bulk/    {items, dry_run} upsert by code

Read access stays open to every authenticated user (form dropdowns, manager
boards); writes are HR/ADMIN only. Branch deletion is deliberately not
exposed — branches are PROTECT-linked to personnel and history, deactivate
with is_active=false instead.
"""
from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
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
from apps.orgs.models import Branch, Region

BRANCH_UPDATE_FIELDS = (
    "name", "region", "province", "city", "address", "phone",
    "geo_latitude", "geo_longitude", "geo_radius_m", "is_active",
)
MAX_BULK_ITEMS = 5000


class RegionUpsertSerializer(serializers.Serializer):
    code = serializers.SlugField(max_length=20)
    name = serializers.CharField(max_length=120)
    is_active = serializers.BooleanField(required=False, default=True)


class BranchUpsertSerializer(serializers.Serializer):
    """Natural-key input (region_code) resolved to objects in validated_data."""

    code = serializers.SlugField(max_length=20)
    name = serializers.CharField(max_length=160)
    region_code = serializers.SlugField(max_length=20)
    province = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    geo_latitude = serializers.FloatField(
        required=False, allow_null=True, min_value=-90, max_value=90
    )
    geo_longitude = serializers.FloatField(
        required=False, allow_null=True, min_value=-180, max_value=180
    )
    geo_radius_m = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=settings.GEOFENCE_RADIUS_MIN,
        max_value=settings.GEOFENCE_RADIUS_MAX,
    )
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_region_code(self, value: str) -> Region:
        try:
            return Region.objects.get(code=value)
        except Region.DoesNotExist as exc:
            raise serializers.ValidationError(
                f"منطقهٔ «{value}» یافت نشد؛ ابتدا منطقه را بسازید."
            ) from exc

    def validate(self, attrs):
        lat = attrs.get("geo_latitude")
        lng = attrs.get("geo_longitude")
        if (lat is None) != (lng is None):
            raise serializers.ValidationError(
                "عرض و طول جغرافیایی باید با هم ارسال شوند یا هر دو خالی باشند."
            )
        return attrs


def _branch_kwargs(v: dict) -> dict:
    """validated_data → Branch constructor/update kwargs (radius default #3)."""
    return {
        "name": v["name"],
        "region": v["region_code"],
        "province": v.get("province", ""),
        "city": v.get("city", ""),
        "address": v.get("address", ""),
        "phone": v.get("phone", ""),
        "geo_latitude": v.get("geo_latitude"),
        "geo_longitude": v.get("geo_longitude"),
        "geo_radius_m": v.get("geo_radius_m") or settings.GEOFENCE_RADIUS_DEFAULT_CITY,
        "is_active": v.get("is_active", True),
    }


def _serialize_region(region: Region) -> dict:
    return {
        "id": region.id,
        "code": region.code,
        "name": region.name,
        "is_active": region.is_active,
        "branches_count": getattr(region, "branches_count", region.branches.count()),
    }


def _serialize_branch(branch: Branch) -> dict:
    return {
        "id": branch.id,
        "code": branch.code,
        "name": branch.name,
        "region_code": branch.region.code,
        "region_name": branch.region.name,
        "province": branch.province,
        "city": branch.city,
        "address": branch.address,
        "phone": branch.phone,
        "geo_latitude": branch.geo_latitude,
        "geo_longitude": branch.geo_longitude,
        "geo_radius_m": branch.geo_radius_m,
        "is_active": branch.is_active,
        "employee_count": getattr(branch, "employee_count", 0),
    }


class RegionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = RegionUpsertSerializer

    def get_queryset(self):
        qs = Region.objects.annotate(branches_count=Count("branches", distinct=True))
        params = self.request.query_params
        is_active = params.get("is_active")
        if is_active in ("true", "1"):
            qs = qs.filter(is_active=True)
        elif is_active in ("false", "0"):
            qs = qs.filter(is_active=False)
        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return qs.order_by("code")

    def list(self, request, *args, **kwargs):
        page, size = page_params(request, default_size=200)
        return paginated_response(self.get_queryset(), page, size, _serialize_region)

    def create(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        ser = RegionUpsertSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            region = Region.objects.create(**ser.validated_data)
        except IntegrityError:
            return Response(
                {"detail": f"منطقه‌ای با کد «{ser.validated_data['code']}» از قبل وجود دارد.",
                 "code": "DUPLICATE"},
                status=400,
            )
        return Response(_serialize_region(region), status=201)

    def partial_update(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        region = self.get_object()
        current = {"code": region.code, "name": region.name, "is_active": region.is_active}
        payload = {k: v for k, v in (request.data or {}).items()}
        ser = RegionUpsertSerializer(data={**current, **payload})
        ser.is_valid(raise_exception=True)
        for field, value in ser.validated_data.items():
            setattr(region, field, value)
        try:
            region.save()
        except IntegrityError:
            return Response({"detail": "کد منطقه تکراری است.", "code": "DUPLICATE"}, status=400)
        return Response(_serialize_region(region))


class BranchViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchUpsertSerializer

    def get_queryset(self):
        qs = Branch.objects.select_related("region").annotate(
            employee_count=Count("home_employees", distinct=True)
        )
        params = self.request.query_params
        region = (params.get("region") or "").strip()
        if region:
            qs = qs.filter(region__code=region)
        is_active = params.get("is_active")
        if is_active in ("true", "1"):
            qs = qs.filter(is_active=True)
        elif is_active in ("false", "0"):
            qs = qs.filter(is_active=False)
        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(city__icontains=search)
            )
        return qs.order_by("code")

    def list(self, request, *args, **kwargs):
        page, size = page_params(request)
        return paginated_response(self.get_queryset(), page, size, _serialize_branch)

    def create(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        ser = BranchUpsertSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            branch = Branch.objects.create(code=ser.validated_data["code"], **_branch_kwargs(ser.validated_data))
        except IntegrityError:
            return Response(
                {"detail": f"شعبه‌ای با کد «{ser.validated_data['code']}» از قبل وجود دارد.",
                 "code": "DUPLICATE"},
                status=400,
            )
        return Response(_serialize_branch(branch), status=201)

    def partial_update(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        branch = self.get_object()
        current = {
            "code": branch.code,
            "name": branch.name,
            "region_code": branch.region.code,
            "province": branch.province,
            "city": branch.city,
            "address": branch.address,
            "phone": branch.phone,
            "geo_latitude": branch.geo_latitude,
            "geo_longitude": branch.geo_longitude,
            "geo_radius_m": branch.geo_radius_m,
            "is_active": branch.is_active,
        }
        payload = {k: v for k, v in (request.data or {}).items()}
        ser = BranchUpsertSerializer(data={**current, **payload})
        ser.is_valid(raise_exception=True)
        for field, value in _branch_kwargs(ser.validated_data).items():
            setattr(branch, field, value)
        try:
            branch.save()
        except IntegrityError:
            return Response({"detail": "کد شعبه تکراری است.", "code": "DUPLICATE"}, status=400)
        return Response(_serialize_branch(branch))

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        """Upsert branches by code — good rows land, bad rows are reported."""
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
        to_create: list[Branch] = []
        to_update: list[Branch] = []
        created = updated = 0
        branch_map = {b.code: b for b in Branch.objects.select_related("region")}
        seen: set[str] = set()

        for n, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                errors.append({"row": n, "code": "", "message": "هر ردیف باید آبجکت باشد."})
                continue
            code = str(raw.get("code") or "").strip()
            if not code:
                errors.append({"row": n, "code": "", "message": "کد شعبه الزامی است."})
                continue
            if code in seen:
                errors.append({"row": n, "code": code, "message": "کد شعبه در فایل تکراری است."})
                continue
            seen.add(code)
            ser = BranchUpsertSerializer(data=raw)
            if not ser.is_valid():
                errors.append({"row": n, "code": code, "message": serializer_errors(ser.errors)})
                continue
            current = branch_map.get(code)
            if current is None:
                created += 1
                if not dry_run:
                    to_create.append(Branch(code=code, **_branch_kwargs(ser.validated_data)))
            else:
                updated += 1
                if not dry_run:
                    for field, value in _branch_kwargs(ser.validated_data).items():
                        setattr(current, field, value)
                    to_update.append(current)

        if not dry_run and (to_create or to_update):
            with transaction.atomic():
                if to_create:
                    Branch.objects.bulk_create(to_create, batch_size=200)
                if to_update:
                    Branch.objects.bulk_update(to_update, fields=list(BRANCH_UPDATE_FIELDS), batch_size=200)

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

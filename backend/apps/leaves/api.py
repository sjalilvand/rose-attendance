"""Requests API — employee submissions + manager decision queue.

Contract (section 11 + decision #5):
- POST /requests/leave/         submit hourly/daily leave  (auto branch split)
- POST /requests/mission/       submit mission
- POST /requests/cancel/        cancel own PENDING request
- GET  /requests/               my requests with per-branch segment status
- GET  /requests/queue/         PENDING segments in the caller's scope
- POST /requests/queue/decide/  APPROVE / REJECT one segment
- GET  /leave-types/            active leave types (form dropdown)

LeaveLedger API (HR increment):
- GET  /leaves/ledger/balances/?employee=   per-type balances (self or HR)
- GET  /leaves/ledger/?employee=            raw ledger rows (HR/ADMIN)
- POST /leaves/ledger/seed/                 bulk OPENING/ACCRUAL/ADJUST + dry-run
- POST /leaves/ledger/adjust/               single ADJUST entry
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api_utils import hr_write_guard
from apps.core.enums import ApprovalAction, LeaveEntryKind, RequestStatus, SegmentStatus
from apps.core.rbac import is_manager, scoped_branch_ids
from apps.orgs.models import Branch
from apps.people.models import Employee, User
from rest_framework.throttling import ScopedRateThrottle

from . import ledger as ledger_svc
from .models import LeaveLedger, LeaveRequest, LeaveType, MissionRequest, RequestSegment
from .services import (
    RequestError,
    cancel_request,
    decide_segment,
    submit_leave,
    submit_mission,
)


def _status_chip(status_value: str) -> str:
    return status_value


def _serialize_segment(segment: RequestSegment) -> dict:
    return {
        "id": segment.id,
        "branch": segment.branch.code,
        "branch_name": segment.branch.name,
        "starts_at": segment.starts_at,
        "ends_at": segment.ends_at,
        "computed_minutes": segment.computed_minutes,
        "status": segment.segment_status,
    }


def _serialize_request(kind: str, request_obj) -> dict:
    if kind == "LEAVE":
        head = {
            "kind": "LEAVE",
            "id": request_obj.id,
            "leave_type": request_obj.leave_type.code,
            "leave_type_name": request_obj.leave_type.name,
            "description": request_obj.description,
        }
    else:
        head = {
            "kind": "MISSION",
            "id": request_obj.id,
            "subject": request_obj.subject,
            "destination": (
                request_obj.destination_branch.name
                if request_obj.destination_branch
                else request_obj.destination_text
            ),
        }
    head.update(
        {
            "status": request_obj.overall_status,
            "starts_at": request_obj.starts_at,
            "ends_at": request_obj.ends_at,
            "computed_minutes": request_obj.computed_minutes,
            "created_at": request_obj.created_at,
            "segments": [_serialize_segment(s) for s in request_obj.segments.all()],
        }
    )
    return head


class LeaveTypeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        data = [
            {
                "code": lt.code,
                "name": lt.name,
                "is_hourly": lt.is_hourly,
                "is_paid": lt.is_paid,
                "requires_attachment": lt.requires_attachment,
            }
            for lt in LeaveType.objects.filter(is_active=True).order_by("id")
        ]
        return Response({"count": len(data), "results": data})


class _WindowSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class LeaveSubmitSerializer(_WindowSerializer):
    leave_type = serializers.SlugField(max_length=30)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_leave_type(self, value: str) -> LeaveType:
        try:
            return LeaveType.objects.get(code=value, is_active=True)
        except LeaveType.DoesNotExist as exc:
            raise serializers.ValidationError("نوع مرخصی فعال با این کد یافت نشد.") from exc


class MissionSubmitSerializer(_WindowSerializer):
    subject = serializers.CharField(max_length=200)
    destination_branch_code = serializers.SlugField(max_length=20, required=False, allow_blank=True)
    destination_text = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_destination_branch_code(self, value: str):
        if not value:
            return None
        try:
            return Branch.objects.get(code=value, is_active=True)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError("شعبهٔ مقصد فعال با این کد یافت نشد.") from exc


class RequestsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Employee-facing request list + submissions + cancel."""

    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        employee = request.user.employee
        leaves = (
            LeaveRequest.objects.filter(employee=employee)
            .prefetch_related("segments__branch")
            .order_by("-created_at")
        )
        missions = (
            MissionRequest.objects.filter(employee=employee)
            .prefetch_related("segments__branch")
            .order_by("-created_at")
        )
        items = [_serialize_request("LEAVE", r) for r in leaves]
        items += [_serialize_request("MISSION", r) for r in missions]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return Response({"count": len(items), "results": items[:100]})

    @action(detail=False, methods=["post"], url_path="leave")
    def submit_leave_request(self, request):
        ser = LeaveSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            request_obj = submit_leave(
                employee=request.user.employee,
                leave_type=data["leave_type"],
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                description=data.get("description", ""),
            )
        except RequestError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)
        return Response(_serialize_request("LEAVE", request_obj), status=201)

    @action(detail=False, methods=["post"], url_path="mission")
    def submit_mission_request(self, request):
        ser = MissionSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            request_obj = submit_mission(
                employee=request.user.employee,
                subject=data["subject"],
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                destination_branch=data.get("destination_branch_code"),
                destination_text=data.get("destination_text", ""),
            )
        except RequestError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)
        return Response(_serialize_request("MISSION", request_obj), status=201)

    @action(detail=False, methods=["post"], url_path="cancel")
    def cancel(self, request):
        kind = request.data.get("kind")
        request_id = request.data.get("id")
        if kind not in ("LEAVE", "MISSION") or not request_id:
            return Response({"detail": "kind و id الزامی است.", "code": "INVALID"}, status=400)
        try:
            request_obj = cancel_request(kind, int(request_id), by=request.user)
        except (TypeError, ValueError):
            return Response({"detail": "id نامعتبر است.", "code": "INVALID"}, status=400)
        except RequestError as exc:
            status = 404 if exc.code == "NOT_FOUND" else 409
            return Response({"detail": exc.message, "code": exc.code}, status=status)
        return Response(_serialize_request(kind, request_obj))


class RequestQueueViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """PENDING segments for BRANCH_MANAGER / REGION_MANAGER / HR / ADMIN."""

    permission_classes = [IsAuthenticated]

    def _scoped_segments(self, pending_only: bool = True):
        user: User = self.request.user
        branch_ids = scoped_branch_ids(user)
        qs = RequestSegment.objects.all()
        if pending_only:
            qs = qs.filter(segment_status=SegmentStatus.PENDING)
        if branch_ids is not None:
            qs = qs.filter(branch_id__in=branch_ids)
        return qs

    def list(self, request, *args, **kwargs):
        if not is_manager(request.user):
            return Response(
                {"detail": "دسترسی رسیدگی ندارید.", "code": "FORBIDDEN"}, status=403
            )
        segments = self._scoped_segments().select_related(
            "branch",
            "leave_request__leave_type",
            "leave_request__employee",
            "mission_request__employee",
        ).order_by("starts_at", "id")[:200]
        # One grouped query for every LEAVE row's tracked balance — the
        # approver sees «مانده» next to each request (None = untracked).
        balance_map: dict[tuple[int, int], int] = {}
        leave_pairs = [
            (segment.leave_request.employee_id, segment.leave_request.leave_type_id)
            for segment in segments
            if segment.leave_request_id
        ]
        if leave_pairs:
            emp_ids = {pair[0] for pair in leave_pairs}
            type_ids = {pair[1] for pair in leave_pairs}
            sums = (
                LeaveLedger.objects.filter(employee_id__in=emp_ids, leave_type_id__in=type_ids)
                .values("employee_id", "leave_type_id")
                .annotate(total=Sum("minutes"))
            )
            balance_map = {(s["employee_id"], s["leave_type_id"]): int(s["total"] or 0) for s in sums}
        items = []
        for segment in segments:
            if segment.leave_request_id:
                request_obj = segment.leave_request
                employee = request_obj.employee
                head = {
                    "kind": "LEAVE",
                    "request_id": request_obj.id,
                    "leave_type": request_obj.leave_type.code,
                    "leave_type_name": request_obj.leave_type.name,
                    "description": request_obj.description,
                    "employee_balance_minutes": balance_map.get(
                        (employee.id, request_obj.leave_type_id)
                    ),
                }
            else:
                request_obj = segment.mission_request
                employee = request_obj.employee
                head = {
                    "kind": "MISSION",
                    "request_id": request_obj.id,
                    "subject": request_obj.subject,
                    "destination": (
                        request_obj.destination_branch.name
                        if request_obj.destination_branch
                        else request_obj.destination_text
                    ),
                }
            head.update(
                {
                    "segment_id": segment.id,
                    "employee": {
                        "id": employee.id,
                        "personnel_code": employee.personnel_code,
                        "full_name": employee.full_name,
                    },
                    "branch": segment.branch.code,
                    "branch_name": segment.branch.name,
                    "starts_at": segment.starts_at,
                    "ends_at": segment.ends_at,
                    "computed_minutes": segment.computed_minutes,
                }
            )
            items.append(head)
        return Response({"count": len(items), "results": items})

    @action(detail=False, methods=["post"], url_path="decide")
    def decide(self, request):
        if not is_manager(request.user):
            return Response(
                {"detail": "دسترسی رسیدگی ندارید.", "code": "FORBIDDEN"}, status=403
            )
        segment_id = request.data.get("segment_id")
        action_value = request.data.get("action")
        comment = request.data.get("comment", "")
        if not segment_id or action_value not in (ApprovalAction.APPROVE, ApprovalAction.REJECT):
            return Response(
                {"detail": "segment_id و action (APPROVE/REJECT) الزامی است.", "code": "INVALID"},
                status=400,
            )
        try:
            segment = self._scoped_segments(pending_only=False).get(id=segment_id)
        except RequestSegment.DoesNotExist:
            return Response({"detail": "بخش درخواست یافت نشد.", "code": "NOT_FOUND"}, status=404)
        try:
            segment = decide_segment(segment, decided_by=request.user, action=action_value, comment=comment)
        except RequestError as exc:
            status = 409 if exc.code == "ALREADY_DECIDED" else 400
            return Response({"detail": exc.message, "code": exc.code}, status=status)
        request_obj = segment.leave_request or segment.mission_request
        return Response(
            {
                "segment_id": segment.id,
                "segment_status": segment.segment_status,
                "overall_status": request_obj.overall_status,
            }
        )


def _serialize_ledger_entry(entry: LeaveLedger) -> dict:
    return {
        "id": entry.id,
        "leave_type": entry.leave_type.code,
        "leave_type_name": entry.leave_type.name,
        "entry_kind": entry.entry_kind,
        "minutes": entry.minutes,
        "balance_after_minutes": entry.balance_after_minutes,
        "basis_date": entry.basis_date,
        "source_type": entry.source_type,
        "source_id": entry.source_id,
        "created_at": entry.created_at,
    }


class LeaveLedgerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """LeaveLedger API — balances for everyone, stream + seeding for HR.

    - GET  ?employee=PERSONNEL_CODE  raw rows, newest first (HR/ADMIN only)
    - GET  .../balances/ ?employee=  per-type balances; employees see their
      own, managers/HR may query anyone via ?employee=
    - POST .../seed/                 bulk append {personnel_code, leave_type,
      minutes, entry_kind?, basis_date?} rows with dry_run — 1404/01/01 style
      Jalali dates accepted; per-row errors, good rows still land
    - POST .../adjust/               single ADJUST (signed minutes)
    """

    permission_classes = [IsAuthenticated]
    # Bulk seeding shares the personnel-import bucket (10/min per user);
    # other actions of this viewset stay unthrottled like the rest of /api/v1.
    throttle_scope = "import"

    def get_throttles(self):
        if self.action == "seed":
            return [ScopedRateThrottle()]
        return []

    def _employee_or_response(self, personnel_code: str):
        employee = Employee.objects.filter(personnel_code=personnel_code).first()
        if employee is None:
            return None, Response(
                {"detail": f"پرسنلی با کد «{personnel_code}» یافت نشد.", "code": "NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return employee, None

    def _self_employee_or_response(self, user: User):
        if not user.employee_id:
            return None, Response(
                {
                    "detail": "این حساب پروندهٔ پرسنلی ندارد؛ پارامتر employee را بدهید.",
                    "code": "NO_EMPLOYEE",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return user.employee, None

    def list(self, request, *args, **kwargs):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        personnel_code = (request.query_params.get("employee") or "").strip()
        if not personnel_code:
            return Response(
                {"detail": "پارامتر employee (کد پرسنلی) الزامی است.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        employee, err = self._employee_or_response(personnel_code)
        if err:
            return err
        entries = (
            LeaveLedger.objects.filter(employee=employee)
            .select_related("leave_type")
            .order_by("-id")[:200]
        )
        return Response(
            {
                "employee": {
                    "id": employee.id,
                    "personnel_code": employee.personnel_code,
                    "full_name": employee.full_name,
                },
                "count": len(entries),
                "results": [_serialize_ledger_entry(entry) for entry in entries],
            }
        )

    @action(detail=False, methods=["get"], url_path="balances")
    def balances(self, request):
        user: User = request.user
        personnel_code = (request.query_params.get("employee") or "").strip()
        if personnel_code:
            # Global roles may look anyone up; BRANCH_MANAGER sees balances
            # through the decision-queue embed instead (branch-scoped there).
            is_global = user.is_superuser or any(
                user.has_role(role) for role in ("REGION_MANAGER", "HR", "ADMIN")
            )
            if not is_global:
                return Response(
                    {"detail": "برای استعلام غیر از خودتان دسترسی کافی ندارید.", "code": "FORBIDDEN"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            employee, err = self._employee_or_response(personnel_code)
            if err:
                return err
        else:
            employee, err = self._self_employee_or_response(user)
            if err:
                return err
        return Response(
            {
                "employee": {
                    "id": employee.id,
                    "personnel_code": employee.personnel_code,
                    "full_name": employee.full_name,
                },
                "balances": ledger_svc.balances_for(employee),
            }
        )

    @action(detail=False, methods=["post"], url_path="seed")
    def seed(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        payload = request.data if isinstance(request.data, dict) else {}
        items = payload.get("items") if isinstance(payload, dict) else request.data
        if not isinstance(items, list):
            return Response({"detail": "آرایهٔ items الزامی است.", "code": "INVALID"}, status=400)
        if len(items) > ledger_svc.MAX_SEED_ROWS:
            return Response(
                {"detail": f"حداکثر {ledger_svc.MAX_SEED_ROWS} ردیف در هر درخواست.", "code": "INVALID"},
                status=400,
            )
        dry_run = isinstance(payload, dict) and str(payload.get("dry_run", "")).lower() in {"1", "true", "yes"}

        errors: list[dict] = []
        wanted_codes = {
            str(raw.get("personnel_code") or "").strip()
            for raw in items
            if isinstance(raw, dict) and str(raw.get("personnel_code") or "").strip()
        }
        employee_map = {e.personnel_code: e for e in Employee.objects.filter(personnel_code__in=wanted_codes)}
        type_map = {t.code: t for t in LeaveType.objects.filter(is_active=True)}

        rows: list[dict] = []  # validated rows in order
        for n, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                errors.append({"row": n, "personnel_code": "", "message": "هر ردیف باید آبجکت باشد."})
                continue
            personnel_code = str(raw.get("personnel_code") or "").strip()
            employee = employee_map.get(personnel_code)
            if employee is None:
                errors.append(
                    {"row": n, "personnel_code": personnel_code, "message": "کد پرسنلی یافت نشد."}
                )
                continue
            type_code = str(raw.get("leave_type") or "").strip()
            leave_type = type_map.get(type_code)
            if leave_type is None:
                errors.append(
                    {"row": n, "personnel_code": personnel_code,
                     "message": f"نوع مرخصی فعال «{type_code}» یافت نشد."}
                )
                continue
            entry_kind = str(raw.get("entry_kind") or LeaveEntryKind.OPENING).strip().upper()
            if entry_kind not in ledger_svc.SEED_KINDS:
                errors.append(
                    {"row": n, "personnel_code": personnel_code,
                     "message": f"نوع گردش باید یکی از {', '.join(ledger_svc.SEED_KINDS)} باشد."}
                )
                continue
            try:
                minutes = int(raw.get("minutes"))
            except (TypeError, ValueError):
                errors.append(
                    {"row": n, "personnel_code": personnel_code, "message": "minutes عدد صحیح الزامی است."}
                )
                continue
            if minutes == 0 or (minutes < 0 and entry_kind != LeaveEntryKind.ADJUST):
                errors.append(
                    {"row": n, "personnel_code": personnel_code,
                     "message": "minutes باید مخالف صفر باشد؛ مقدار منفی فقط برای ADJUST."}
                )
                continue
            try:
                basis_date = ledger_svc.parse_basis_date(raw.get("basis_date")) or timezone.localdate()
            except ledger_svc.LedgerError as exc:
                errors.append({"row": n, "personnel_code": personnel_code, "message": exc.message})
                continue
            rows.append(
                {"row": n, "employee": employee, "leave_type": leave_type,
                 "entry_kind": entry_kind, "minutes": minutes, "basis_date": basis_date}
            )

        # Running balances per (employee, type) — one grouped query, then in-memory.
        running: dict[tuple[int, int], int] = {}
        if rows:
            emp_ids = {r["employee"].id for r in rows}
            type_ids = {r["leave_type"].id for r in rows}
            sums = (
                LeaveLedger.objects.filter(employee_id__in=emp_ids, leave_type_id__in=type_ids)
                .values("employee_id", "leave_type_id")
                .annotate(total=Sum("minutes"))
            )
            running = {(s["employee_id"], s["leave_type_id"]): int(s["total"] or 0) for s in sums}

        to_create: list[LeaveLedger] = []
        for r in rows:
            key = (r["employee"].id, r["leave_type"].id)
            running[key] = running.get(key, 0) + r["minutes"]
            if not dry_run:
                to_create.append(
                    LeaveLedger(
                        employee=r["employee"],
                        leave_type=r["leave_type"],
                        entry_kind=r["entry_kind"],
                        minutes=r["minutes"],
                        balance_after_minutes=running[key],
                        basis_date=r["basis_date"],
                        source_type="HR_SEED",
                    )
                )
        if not dry_run and to_create:
            with transaction.atomic():
                LeaveLedger.objects.bulk_create(to_create, batch_size=500)

        return Response(
            {
                "total": len(items),
                "created": len(to_create) if not dry_run else len(rows),
                "updated": 0,
                "skipped": len(errors),
                "errors": errors[:50],
                "dry_run": dry_run,
            }
        )

    @action(detail=False, methods=["post"], url_path="adjust")
    def adjust(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        personnel_code = str(request.data.get("personnel_code") or "").strip()
        type_code = str(request.data.get("leave_type") or "").strip()
        try:
            minutes = int(request.data.get("minutes"))
        except (TypeError, ValueError):
            return Response({"detail": "minutes عدد صحیح الزامی است.", "code": "INVALID"}, status=400)
        if not personnel_code or not type_code or minutes == 0:
            return Response(
                {"detail": "personnel_code، leave_type و minutes (≠۰) الزامی است.", "code": "INVALID"},
                status=400,
            )
        employee, err = self._employee_or_response(personnel_code)
        if err:
            return err
        leave_type = LeaveType.objects.filter(code=type_code, is_active=True).first()
        if leave_type is None:
            return Response(
                {"detail": f"نوع مرخصی فعال «{type_code}» یافت نشد.", "code": "NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            basis_date = ledger_svc.parse_basis_date(request.data.get("basis_date")) or timezone.localdate()
        except ledger_svc.LedgerError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)
        entry = ledger_svc.append_entry(
            employee=employee,
            leave_type=leave_type,
            entry_kind=LeaveEntryKind.ADJUST,
            minutes=minutes,
            basis_date=basis_date,
            source_type="HR_ADJUST",
        )
        return Response(_serialize_ledger_entry(entry), status=201)


class LedgerTemplateView(APIView):
    """GET /leaves/ledger/template/ — dedicated xlsx template (HR/ADMIN).

    Sheet «انواع مرخصی» is generated from live active types so HR copies
    codes instead of typing them; unknown codes are the #1 import error.
    """

    def get(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        payload = ledger_svc.build_balance_template()
        response = HttpResponse(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="leave-balance-template.xlsx"'
        return response


class LedgerImportView(APIView):
    """POST /leaves/ledger/import/ — multipart xlsx; form field dry_run=true.

    Same report shape as the JSON seed and the personnel import:
    {total, created, updated, skipped, errors[], dry_run}.
    """

    throttle_scope = "import"

    def post(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return forbidden
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "فایل xlsx الزامی است.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > 5 * 1024 * 1024:
            return Response(
                {"detail": "حجم فایل بیش از ۵ مگابایت است.", "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run = str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes"}
        try:
            report = ledger_svc.import_balances(upload.read(), dry_run=dry_run)
        except ledger_svc.WorkbookError as exc:
            return Response(
                {"detail": str(exc), "code": "INVALID"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(report)

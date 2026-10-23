"""Requests API — employee submissions + manager decision queue.

Contract (section 11 + decision #5):
- POST /requests/leave/         submit hourly/daily leave  (auto branch split)
- POST /requests/mission/       submit mission
- POST /requests/cancel/        cancel own PENDING request
- GET  /requests/               my requests with per-branch segment status
- GET  /requests/queue/         PENDING segments in the caller's scope
- POST /requests/queue/decide/  APPROVE / REJECT one segment
- GET  /leave-types/            active leave types (form dropdown)

Leave balances are not mutated yet (pending HR opening balances); see
leaves/services docstring.
"""
from __future__ import annotations

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.enums import ApprovalAction, RequestStatus, SegmentStatus
from apps.core.rbac import is_manager, scoped_branch_ids
from apps.orgs.models import Branch
from apps.people.models import User

from .models import LeaveRequest, LeaveType, MissionRequest, RequestSegment
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

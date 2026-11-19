"""مانیتورینگ وب — دید زندهٔ عملیاتی برای تیم مدیریت (نسخهٔ دسکتاپ).

GET /api/v1/monitoring/dashboard/?branch=CODE&region=CODE
دسترسی: superuser / HR / ADMIN / REGION_MANAGER / AUDITOR / BRANCH_MANAGER —
مدیرِ شعبه فقط شعبه‌های تخصیص فعال خودش را می‌بیند (هم‌الگوی OvertimeProposalViewSet).

داده‌ها همهٔ «امروزِ محلی» است: KPI ها، فهرست حاضرانِ الان (بازهٔ باز)، جریان زندهٔ
ترددها، انحراف‌های GPS امروز (OUT_OF_RANGE / LOW_ACCURACY با متر) و غایبانِ
بدون هیچ ترددی.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance.models import AttendanceEvent, AttendanceSession
from apps.orgs.models import Branch
from apps.people.models import Employee, User

SCOPE_ROLES = ("HR", "ADMIN", "REGION_MANAGER", "AUDITOR")


def _fmt_m(value) -> float | None:
    return round(value, 1) if value is not None else None


def visible_branch_ids(user: User) -> list[int] | None:
    """None = همهٔ سازمان؛ فهرست = فقط این شعبه‌ها (مدیر شعبه)."""
    if user.is_superuser or any(user.has_role(r) for r in SCOPE_ROLES):
        return None
    if user.has_role("BRANCH_MANAGER"):
        return list(
            user.role_assignments.filter(
                role__code="BRANCH_MANAGER", branch__isnull=False
            ).values_list("branch_id", flat=True)
        )
    return []


class MonitoringDashboardView(APIView):
    """GET /api/v1/monitoring/dashboard/ — همهٔ داده‌های مانیتورینگ در یک پاس."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user: User = request.user
        scope = visible_branch_ids(user)
        if scope is not None and not scope:
            return Response({"detail": "دسترسی مانیتورینگ ندارید.", "code": "FORBIDDEN"}, status=403)

        branch_qs = Branch.objects.filter(is_active=True)
        if scope is not None:
            branch_qs = branch_qs.filter(id__in=scope)
        region_code = (request.query_params.get("region") or "").strip()
        if region_code:
            branch_qs = branch_qs.filter(region__code=region_code)
        branch_code = (request.query_params.get("branch") or "").strip()
        if branch_code:
            # scope قبلاً اعمال شده؛ فیلتر کد فقط تنگ‌تر می‌کند
            branch_qs = branch_qs.filter(code=branch_code)
        branch_ids = list(branch_qs.values_list("id", flat=True))

        today = timezone.localdate()
        events = AttendanceEvent.objects.filter(
            branch_id__in=branch_ids, effective_time__date=today
        )

        location_counts = dict(
            events.values_list("location_status").annotate(n=Count("id"))
        )
        review_count = events.filter(event_status="NEEDS_REVIEW").count()

        employees_active = Employee.objects.filter(
            employment_status="ACTIVE", home_branch_id__in=branch_ids
        )
        with_events = set(events.values_list("employee_id", flat=True))

        open_sessions = (
            AttendanceSession.objects.filter(
                branch_id__in=branch_ids, session_state="OPEN", is_purged=False
            )
            .select_related("employee", "branch", "check_in_event")
            .order_by("check_in_event__effective_time")
        )

        recent = (
            AttendanceEvent.objects.filter(branch_id__in=branch_ids)
            .select_related("employee", "branch")
            .order_by("-effective_time", "-id")[:50]
        )

        deviations = (
            events.filter(location_status__in=("OUT_OF_RANGE", "LOW_ACCURACY"))
            .select_related("employee", "branch")
            .order_by("-effective_time")[:100]
        )

        absent = [
            e
            for e in employees_active.select_related("home_branch").order_by("personnel_code")
            if e.id not in with_events
        ][:100]

        now = timezone.now()
        return Response(
            {
                "today": today.isoformat(),
                "branches_in_scope": len(branch_ids),
                "kpis": {
                    "employees_active": employees_active.count(),
                    "events_today": events.count(),
                    "with_events_today": len(with_events),
                    "present_now": open_sessions.count(),
                    "out_of_range_today": location_counts.get("OUT_OF_RANGE", 0),
                    "no_gps_today": location_counts.get("UNAVAILABLE", 0),
                    "low_accuracy_today": location_counts.get("LOW_ACCURACY", 0),
                    "in_range_today": location_counts.get("IN_RANGE", 0),
                    "needs_review_today": review_count,
                },
                "present_now": [
                    {
                        "employee": e.employee.full_name,
                        "personnel_code": e.employee.personnel_code,
                        "branch": e.branch.code,
                        "branch_name": e.branch.name,
                        "check_in_at": e.check_in_event.effective_time if e.check_in_event else None,
                        "minutes_so_far": (
                            int((now - e.check_in_event.effective_time).total_seconds() // 60)
                            if e.check_in_event
                            else None
                        ),
                    }
                    for e in open_sessions[:200]
                ],
                "live_events": [
                    {
                        "event_uuid": str(e.event_uuid),
                        "employee": e.employee.full_name,
                        "personnel_code": e.employee.personnel_code,
                        "branch": e.branch.code,
                        "branch_name": e.branch.name,
                        "event_type": e.event_type,
                        "effective_time": e.effective_time,
                        "connection_mode": e.connection_mode,
                        "event_status": e.event_status,
                        "location_status": e.location_status,
                        "location_distance_m": _fmt_m(e.location_distance_m),
                        "location_accuracy_m": _fmt_m(e.location_accuracy_m),
                    }
                    for e in recent
                ],
                "deviations_today": [
                    {
                        "event_uuid": str(e.event_uuid),
                        "employee": e.employee.full_name,
                        "personnel_code": e.employee.personnel_code,
                        "branch": e.branch.code,
                        "event_type": e.event_type,
                        "effective_time": e.effective_time,
                        "location_status": e.location_status,
                        "location_distance_m": _fmt_m(e.location_distance_m),
                        "location_accuracy_m": _fmt_m(e.location_accuracy_m),
                        "location_reason": e.location_reason,
                    }
                    for e in deviations
                ],
                "absent_today": [
                    {
                        "employee": e.full_name,
                        "personnel_code": e.personnel_code,
                        "home_branch": e.home_branch.code,
                        "home_branch_name": e.home_branch.name,
                    }
                    for e in absent
                ],
                "absent_total": max(0, employees_active.count() - len(with_events)),
            }
        )

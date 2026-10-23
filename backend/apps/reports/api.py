"""Monthly summaries read API — own records; >= 24-month retention window.

Step 6 increment — HR Excel reporting:
- GET /reports/monthly/preview/?year=1404&month=7&branch=  → per-branch totals
- GET /reports/monthly/excel/?year=1404&month=7&branch=    → xlsx download
Both are HR/ADMIN/superuser-only and share the rollup engine (§7.4).
"""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api_utils import hr_write_guard
from apps.core.jalali import current_jalali_period
from apps.orgs.models import Branch

from . import excel_export
from .models import MonthlySummary


def _parse_period(request) -> tuple[int, int] | None:
    """?year=&month= in Jalali — defaults to the current Tehran period."""
    jy, jm = current_jalali_period()
    raw_year = request.query_params.get("year")
    raw_month = request.query_params.get("month")
    try:
        if raw_year:
            jy = int(raw_year)
        if raw_month:
            jm = int(raw_month)
    except (TypeError, ValueError):
        return None
    if not (1300 <= jy <= 1500 and 1 <= jm <= 12):
        return None
    return jy, jm


def _parse_branch(request):
    """?branch=CODE optional — unknown codes are a 404, not silent scope drops."""
    code = (request.query_params.get("branch") or "").strip()
    if not code:
        return None
    branch = Branch.objects.filter(code=code).first()
    if branch is None:
        raise Branch.DoesNotExist(code)
    return branch


class _MonthlyReportBaseView(APIView):
    """Shared guard/param plumbing of the two HR report endpoints."""

    permission_classes = [IsAuthenticated]

    def _context(self, request):
        forbidden = hr_write_guard(request.user)
        if forbidden:
            return None, forbidden
        period = _parse_period(request)
        if period is None:
            return None, Response(
                {"detail": "سال/ماه شمسی نامعتبر است (?year=1404&month=7).", "code": "INVALID"},
                status=400,
            )
        try:
            branch = _parse_branch(request)
        except Branch.DoesNotExist:
            return None, Response(
                {"detail": "شعبه با این کد یافت نشد.", "code": "NOT_FOUND"}, status=404
            )
        return (period, branch), None


class MonthlySummaryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.has_role("HR") or user.has_role("ADMIN"):
            qs = MonthlySummary.objects.all()
        else:
            qs = MonthlySummary.objects.filter(employee=user.employee)
        return qs.select_related("branch", "employee")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().order_by("-period_year", "-period_month")
        page = self.paginate_queryset(qs)
        data = [
            {
                "id": s.id,
                "branch": s.branch.code,
                "personnel_code": s.employee.personnel_code,
                "period_year": s.period_year,
                "period_month": s.period_month,
                "required_minutes": s.required_minutes,
                "accepted_work_minutes": s.accepted_work_minutes,
                "late_minutes": s.late_minutes,
                "early_leave_minutes": s.early_leave_minutes,
                "absence_minutes": s.absence_minutes,
                "shortage_minutes": s.shortage_minutes,
                "overtime_minutes": s.overtime_minutes,
                "mission_minutes": s.mission_minutes,
                "leave_minutes_by_type": s.leave_minutes_by_type,
                "incomplete_session_count": s.incomplete_session_count,
                "no_location_count": s.no_location_count,
                "out_of_range_count": s.out_of_range_count,
                "summary_state": s.summary_state,
                "rule_set_ids": s.rule_set_ids,
                "finalized_at": s.finalized_at,
            }
            for s in page
        ]
        return self.get_paginated_response(data)


class ManagerBoardViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Branch daily board for managers — GET /reports/manager-board/?date=YYYY-MM-DD[&branch=CODE]

    One row per (employee × managed branch) for the requested Jalali day,
    derived on the fly from compute_days_for_month (no extra persistence,
    same derived-data contract as the employee daily board).
    """

    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        import datetime as dt

        from django.db.models import Q
        from django.utils import timezone

        from apps.attendance.api import _serialize_day
        from apps.core.jalali import jalali_period_of
        from apps.core.rbac import is_manager, scoped_branch_ids
        from apps.people.models import Employee
        from apps.orgs.models import Branch
        from .services import compute_days_for_month

        user = request.user
        if not is_manager(user):
            return Response(
                {"detail": "دسترسی تابلوی مدیران ندارید.", "code": "FORBIDDEN"}, status=403
            )
        raw_date = request.query_params.get("date")
        try:
            board_date = dt.date.fromisoformat(raw_date) if raw_date else timezone.localdate()
        except ValueError:
            return Response({"detail": "تاریخ نامعتبر است.", "code": "INVALID"}, status=400)

        branch_ids = scoped_branch_ids(user)
        if branch_ids is not None:
            branch_qs = Branch.objects.filter(id__in=branch_ids, is_active=True)
        else:
            branch_qs = Branch.objects.filter(is_active=True)
        branch_code = request.query_params.get("branch")
        if branch_code:
            branch_qs = branch_qs.filter(code=branch_code)
        branches = list(branch_qs.order_by("code"))
        if not branches:
            return Response({"date": board_date, "count": 0, "results": []})

        branch_by_id = {b.id: b for b in branches}
        today = timezone.localdate()
        employees = (
            Employee.objects.filter(employment_status="ACTIVE")
            .filter(
                Q(home_branch_id__in=branch_by_id)
                | Q(
                    branch_assignments__branch_id__in=branch_by_id,
                    branch_assignments__is_allowed=True,
                    branch_assignments__valid_from__lte=board_date,
                )
                & (
                    Q(branch_assignments__valid_to__isnull=True)
                    | Q(branch_assignments__valid_to__gte=board_date)
                )
            )
            .select_related("home_branch")
            .distinct()
        )

        jy, jm = jalali_period_of(board_date)
        rows = []
        for employee in employees:
            covered = set()
            for branch in branches:
                is_home = employee.home_branch_id == branch.id
                if not is_home:
                    has_assignment = employee.branch_assignments.filter(
                        branch_id=branch.id,
                        is_allowed=True,
                        valid_from__lte=board_date,
                    ).filter(
                        Q(valid_to__isnull=True) | Q(valid_to__gte=board_date)
                    ).exists()
                    if not has_assignment:
                        continue
                if branch.id in covered:
                    continue
                covered.add(branch.id)
                results, _resolver = compute_days_for_month(employee.id, branch.id, jy, jm)
                day = next((d for d in results if d.shift_date == board_date), None)
                rows.append(
                    {
                        "employee": {
                            "id": employee.id,
                            "personnel_code": employee.personnel_code,
                            "full_name": employee.full_name,
                            "is_home": is_home,
                        },
                        "branch": branch.code,
                        "branch_name": branch.name,
                        "day": _serialize_day(day) if day else None,
                    }
                )
        rows.sort(key=lambda r: (r["branch"], r["employee"]["personnel_code"]))
        return Response({"date": board_date, "count": len(rows), "results": rows[:400]})


class MonthlyReportPreviewView(_MonthlyReportBaseView):
    """GET /reports/monthly/preview/?year=1404&month=7[&branch=CODE][&refresh=0]

    Per-branch totals of the Jalali period for the PWA page. By default the
    period is re-rolled first (?refresh=0 reads persisted summaries as-is,
    e.g. right after a closure where recompute would be wasted work).
    """

    def get(self, request):
        context, err = self._context(request)
        if err:
            return err
        (jy, jm), branch = context
        refresh = request.query_params.get("refresh", "1").lower() not in {"0", "false", "no"}
        excel_export.ensure_refreshed(jy, jm, branch, refresh=refresh)
        return Response(excel_export.month_preview(jy, jm, branch))


class MonthlyReportExcelView(_MonthlyReportBaseView):
    """GET /reports/monthly/excel/?year=1404&month=7[&branch=CODE]

    The workbook is always built from a freshly recomputed period — HR gets a
    live snapshot, repeatable down to the same rule_set_ids (§2, §7.4).
    """

    def get(self, request):
        context, err = self._context(request)
        if err:
            return err
        (jy, jm), branch = context
        excel_export.ensure_refreshed(jy, jm, branch, refresh=True)
        payload = excel_export.build_monthly_report(
            jy, jm, branch,
            generated_by=request.user.username,
        )
        response = HttpResponse(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="rose-monthly-report-{jy}-{jm:02d}.xlsx"'
        )
        return response

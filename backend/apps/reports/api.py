"""Monthly summaries read API — own records; >= 24-month retention window."""
from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from .models import MonthlySummary


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

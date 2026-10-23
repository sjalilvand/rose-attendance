"""Monthly summaries (person × branch × Jalali month) and period closures.

Retention: summaries and request records are kept >= 24 months (approved
decisions #1 and #6 of §34). The two conditional unique constraints on
closures reproduce the functional index COALESCE(scope_id, 0) of schema.sql
in a portable way.
"""
from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.enums import SummaryState
from apps.core.models import TimeStampedModel


class MonthlySummary(TimeStampedModel):
    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="monthly_summaries"
    )
    branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="monthly_summaries"
    )
    period_year = models.SmallIntegerField(help_text="سال شمسی")
    period_month = models.SmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    required_minutes = models.PositiveIntegerField(default=0)
    valid_presence_minutes = models.PositiveIntegerField(default=0)
    accepted_work_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)
    absence_minutes = models.PositiveIntegerField(default=0)
    shortage_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    leave_minutes_by_type = models.JSONField(default=dict, blank=True)
    mission_minutes = models.PositiveIntegerField(default=0)
    incomplete_session_count = models.PositiveIntegerField(default=0)
    no_location_count = models.PositiveIntegerField(default=0)
    out_of_range_count = models.PositiveIntegerField(default=0)
    rule_set_ids = models.JSONField(default=list, blank=True)
    summary_state = models.CharField(
        max_length=12, choices=SummaryState.choices, default=SummaryState.PROVISIONAL
    )
    closure = models.ForeignKey(
        "MonthlyClosure", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="summaries",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "monthly_summaries"
        verbose_name = "خلاصه ماهانه"
        verbose_name_plural = "خلاصه‌های ماهانه"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "branch", "period_year", "period_month"],
                name="uq_monthly_summary",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.employee_id}@{self.branch_id}:{self.period_year}/{self.period_month:02d}"


class MonthlyClosure(models.Model):
    period_year = models.SmallIntegerField()
    period_month = models.SmallIntegerField()
    scope = models.CharField(max_length=10, default="GLOBAL")  # GLOBAL / BRANCH
    scope_branch = models.ForeignKey(
        "orgs.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="closures"
    )
    state = models.CharField(max_length=12, default="IN_PROGRESS")  # IN_PROGRESS / CLOSED
    closed_by = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="closures"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monthly_closures"
        verbose_name = "بستن دوره"
        verbose_name_plural = "بستن دوره‌ها"
        constraints = [
            # uq_closure: COALESCE(scope_id, 0) ported as two conditional constraints
            models.UniqueConstraint(
                fields=["period_year", "period_month", "scope"],
                condition=models.Q(scope_branch__isnull=True),
                name="uq_closure_global",
            ),
            models.UniqueConstraint(
                fields=["period_year", "period_month", "scope", "scope_branch"],
                condition=models.Q(scope_branch__isnull=False),
                name="uq_closure_branch",
            ),
        ]

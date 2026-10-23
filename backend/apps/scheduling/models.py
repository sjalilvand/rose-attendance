"""Scheduling domain — calendars, shifts, rotating patterns, scheduled shifts.

Schema.sql "حوزه زمان‌بندی" + section 10. Night shifts are anchored to the
shift START date (work_date); planned_start/planned_end are absolute
timestamps computed from that anchor (calculation-rules §5).
"""
from __future__ import annotations

import datetime as dt

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.enums import RestMode, ShiftSource
from apps.core.models import TimeStampedModel


class WorkCalendar(models.Model):
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "work_calendars"
        verbose_name = "تقویم کاری"
        verbose_name_plural = "تقویم‌های کاری"

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class CalendarHoliday(models.Model):
    calendar = models.ForeignKey(
        WorkCalendar, on_delete=models.CASCADE, related_name="holidays"
    )
    holiday_date = models.DateField()
    title = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=10, default="FULL")  # FULL / HALF

    class Meta:
        db_table = "calendar_holidays"
        verbose_name = "تعطیلی"
        verbose_name_plural = "تعطیلات"
        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "holiday_date"], name="uq_calendar_holiday"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.holiday_date} ({self.kind})"


class Shift(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    crosses_midnight = models.BooleanField(default=False, help_text="شیفت شب")
    rest_minutes = models.PositiveIntegerField(default=0)
    rest_mode = models.CharField(max_length=20, choices=RestMode.choices, default=RestMode.FIXED)
    grace_minutes = models.PositiveIntegerField(default=0)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    scope_branch = models.ForeignKey(
        "orgs.Branch", null=True, blank=True, on_delete=models.CASCADE,
        related_name="shifts",
    )  # NULL = دامنه عمومی

    class Meta:
        db_table = "shifts"
        verbose_name = "شیفت"
        verbose_name_plural = "شیفت‌ها"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rest_minutes__gte=0), name="chk_shift_rest_nonneg"
            ),
            models.CheckConstraint(
                condition=models.Q(grace_minutes__gte=0), name="chk_shift_grace_nonneg"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} ({self.starts_at:%H:%M}–{self.ends_at:%H:%M})"


class ShiftPattern(models.Model):
    """Rotating pattern; cycle day n = (date - start_on_date) mod cycle_length."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    cycle_length_days = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(60)]
    )
    start_on_date = models.DateField()
    branch = models.ForeignKey(
        "orgs.Branch", null=True, blank=True, on_delete=models.CASCADE,
        related_name="shift_patterns",
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "shift_patterns"
        verbose_name = "الگوی چرخشی"
        verbose_name_plural = "الگوهای چرخشی"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cycle_length_days__gte=1, cycle_length_days__lte=60),
                name="chk_pattern_cycle",
            ),
        ]

    def cycle_index_for(self, date: dt.date) -> int:
        """0-based day index in the cycle for a given date."""
        delta = (date - self.start_on_date).days
        if delta < 0:
            # Pattern predates the query date; step backwards into the cycle.
            return delta % self.cycle_length_days
        return delta % self.cycle_length_days


class ShiftPatternItem(models.Model):
    pattern = models.ForeignKey(ShiftPattern, on_delete=models.CASCADE, related_name="items")
    day_index = models.PositiveSmallIntegerField()  # 1-based
    shift = models.ForeignKey(
        Shift, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )  # NULL = روز استراحت

    class Meta:
        db_table = "shift_pattern_items"
        verbose_name = "آیتم الگو"
        verbose_name_plural = "آیتم‌های الگو"
        constraints = [
            models.UniqueConstraint(
                fields=["pattern", "day_index"], name="uq_pattern_day"
            ),
            models.CheckConstraint(
                condition=models.Q(day_index__gte=1), name="chk_pattern_day_index"
            ),
        ]


class ScheduledShift(TimeStampedModel):
    """Effective shift of (employee, branch, work_date) — the day anchor."""

    employee = models.ForeignKey(
        "people.Employee", on_delete=models.CASCADE, related_name="scheduled_shifts"
    )
    branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="scheduled_shifts"
    )
    work_date = models.DateField(help_text="تاریخ شروع شیفت (پایه شیفت شب)")
    shift = models.ForeignKey(
        Shift, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # NULL = استراحت/برنامه‌ریزی‌نشده
    source = models.CharField(max_length=10, choices=ShiftSource.choices, default=ShiftSource.PATTERN)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    pattern = models.ForeignKey(
        ShiftPattern, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "scheduled_shifts"
        verbose_name = "شیفت برنامه‌ریزی‌شده"
        verbose_name_plural = "شیفت‌های برنامه‌ریزی‌شده"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "branch", "work_date"], name="uq_scheduled_shift"
            ),
        ]
        indexes = [
            models.Index(fields=["branch", "work_date"]),
            models.Index(fields=["employee", "work_date"]),
        ]

    def save(self, *args, **kwargs):
        # Absolute planned window from the work_date anchor (night shifts
        # cross midnight; end is always after start).
        if self.shift is not None:
            start_dt = dt.datetime.combine(self.work_date, self.shift.starts_at)
            end_time = self.shift.ends_at
            end_dt = dt.datetime.combine(self.work_date, end_time)
            if self.shift.crosses_midnight and end_dt <= start_dt:
                end_dt += dt.timedelta(days=1)
            elif not self.shift.crosses_midnight and end_dt < start_dt:
                end_dt += dt.timedelta(days=1)
            tz = timezone.get_current_timezone()
            self.planned_start = timezone.make_aware(start_dt, tz)
            self.planned_end = timezone.make_aware(end_dt, tz)
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.employee_id}@{self.branch_id}:{self.work_date}"

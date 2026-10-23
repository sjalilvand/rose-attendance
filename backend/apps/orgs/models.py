"""Organisational domain — regions, branches, dated employee assignments.

Faithful translation of schema.sql "حوزه سازمانی" plus sections 4/5 of the
requirements document. Geofence radius default is the approved decision #3:
150 m (city) / 300 m (clinic & station), adjustable per branch within 50–1000.
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class Region(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "regions"
        verbose_name = "منطقه"
        verbose_name_plural = "مناطق"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} — {self.name}"


class Branch(TimeStampedModel):
    """Branch/clinic with its own geofence configuration (approved #3)."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=160)
    region = models.ForeignKey(
        Region, on_delete=models.PROTECT, related_name="branches"
    )
    province = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    # FKs to people.Employee resolve lazily (no import cycle).
    manager_employee = models.ForeignKey(
        "people.Employee", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="managed_branches", db_column="manager_employee_id",
    )
    delegate_employee = models.ForeignKey(
        "people.Employee", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="delegated_branches", db_column="delegate_employee_id",
    )
    geo_latitude = models.FloatField(null=True, blank=True)
    geo_longitude = models.FloatField(null=True, blank=True)
    geo_radius_m = models.PositiveIntegerField(
        default=settings.GEOFENCE_RADIUS_DEFAULT_CITY,
        validators=[
            MinValueValidator(settings.GEOFENCE_RADIUS_MIN),
            MaxValueValidator(settings.GEOFENCE_RADIUS_MAX),
        ],
        help_text="شعاع مجاز تردد به متر؛ پیش‌فرض ۱۵۰ شهری / ۳۰۰ کلینیک (مصوب ۲٫۱)",
    )
    work_calendar = models.ForeignKey(
        "scheduling.WorkCalendar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="branches",
    )
    is_active = models.BooleanField(default=True)
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "branches"
        verbose_name = "شعبه"
        verbose_name_plural = "شعب"
        constraints = [
            # chk_branch_geo: both coordinates present or both absent
            models.CheckConstraint(
                condition=(
                    models.Q(geo_latitude__isnull=True, geo_longitude__isnull=True)
                    | models.Q(geo_latitude__isnull=False, geo_longitude__isnull=False)
                ),
                name="chk_branch_geo",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    geo_radius_m__gte=settings.GEOFENCE_RADIUS_MIN,
                    geo_radius_m__lte=settings.GEOFENCE_RADIUS_MAX,
                ),
                name="chk_branch_radius_range",
            ),
        ]
        indexes = [
            models.Index(fields=["region", "is_active"]),
        ]

    def clean(self) -> None:
        # Clinic/station default of 300 m applied at creation time when the
        # caller does not choose an explicit radius; see Branch.save().
        return super().clean()

    def save(self, *args, **kwargs):
        if self.geo_radius_m is None:
            self.geo_radius_m = settings.GEOFENCE_RADIUS_DEFAULT_CITY
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} — {self.name}"


class EmployeeBranchAssignment(TimeStampedModel):
    """Dated person↔branch permission (section 5)."""

    employee = models.ForeignKey(
        "people.Employee", on_delete=models.CASCADE, related_name="branch_assignments"
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="assignments")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)  # NULL = بدون پایان
    is_allowed = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "employee_branch_assignments"
        verbose_name = "تخصیص پرسنل به شعبه"
        verbose_name_plural = "تخصیص‌های پرسنل به شعب"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="chk_assignment_period",
            ),
            models.UniqueConstraint(
                fields=["employee", "branch", "valid_from"], name="uq_assignment"
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "valid_from", "valid_to"]),
            models.Index(fields=["branch", "valid_from", "valid_to"]),
        ]

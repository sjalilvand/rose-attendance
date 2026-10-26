"""Operations domain — Excel imports, audit trail, cleanup runs.

Schema.sql "عملیات". Audit logs never contain message bodies or full
coordinates (section 27 of the requirements document).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class ImportJob(models.Model):
    job_kind = models.CharField(max_length=20)  # BRANCHES/EMPLOYEES/…/LEAVE_OPENING
    uploaded_by = models.ForeignKey("people.User", on_delete=models.PROTECT, related_name="import_jobs")
    file_name = models.CharField(max_length=255)
    mode = models.CharField(max_length=10, default="ADD")  # ADD / UPSERT
    status = models.CharField(max_length=10, default="PENDING")  # PENDING/RUNNING/DONE/FAILED
    total_rows = models.PositiveIntegerField(default=0)
    ok_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_jobs"
        verbose_name = "بارگذاری"
        verbose_name_plural = "بارگذاری‌ها"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=["ADD", "UPSERT"]), name="chk_import_mode"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["PENDING", "RUNNING", "DONE", "FAILED"]),
                name="chk_import_status",
            ),
        ]

    @classmethod
    def max_upload_mb(cls) -> int:
        return settings.APP_THRESHOLDS["UPLOAD_MAX_MB"]


class ImportError(models.Model):
    import_job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="errors")
    row_number = models.PositiveIntegerField()
    column_name = models.CharField(max_length=60, blank=True)
    error_code = models.CharField(max_length=40)
    raw_value = models.TextField(blank=True)
    message = models.TextField()

    class Meta:
        db_table = "import_errors"
        verbose_name = "خطای بارگذاری"
        verbose_name_plural = "خطاهای بارگذاری"
        indexes = [models.Index(fields=["import_job", "row_number"], name="idx_import_errors_job")]


class AuditLog(models.Model):
    actor = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs",
        db_column="actor_user_id",
    )
    actor_role = models.CharField(max_length=30, blank=True)
    action_code = models.CharField(max_length=60)
    entity_type = models.CharField(max_length=60)
    entity_id = models.BigIntegerField(null=True, blank=True)
    before_value = models.JSONField(null=True, blank=True)
    after_value = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        verbose_name = "رکورد حسابرسی"
        verbose_name_plural = "حسابرسی"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "created_at"], name="idx_audit_entity"),
            models.Index(fields=["actor", "created_at"], name="idx_audit_actor"),
        ]


class CleanupRun(models.Model):
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    dry_run = models.BooleanField(default=False)
    scoped_periods = models.JSONField(default=list, blank=True)
    deleted_events = models.PositiveIntegerField(default=0)
    deleted_messages = models.PositiveIntegerField(default=0)
    deleted_notifications = models.PositiveIntegerField(default=0)
    skipped_sessions = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, default="RUNNING")  # RUNNING/DONE/FAILED
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cleanup_runs"
        verbose_name = "اجرای پاکسازی"
        verbose_name_plural = "اجرای پاکسازی‌ها"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["RUNNING", "DONE", "FAILED"]),
                name="chk_cleanup_status",
            ),
        ]

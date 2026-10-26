"""Celery application — asynchronous and scheduled work of Rose Attendance.

Queues and periodic tasks mirror docs/analysis/02-calculation-rules.md §10:
pairing after every punch/sync happens inline in the request path (same
transaction); nightly recomputation and retention cleanup run here.

Beat schedule times are Asia/Tehran (approved Jalali-based calendar).
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("rose_attendance")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "recompute-nightly": {
        # Recompute yesterday + today for all active employees (step 1 of pipeline)
        # + refresh current Jalali month summaries of recently active streams.
        "task": "apps.attendance.tasks.recompute_nightly",
        "schedule": crontab(hour=1, minute=30),
    },
    "monthly-recompute-guard": {
        # On the first days of each Jalali month, refresh the previous month
        # for late offline events; closing the period stays an HR action.
        "task": "apps.reports.tasks.monthly_recompute_guard",
        "schedule": crontab(hour=2, minute=15),
    },
    "retention-cleanup-dry-run": {
        # Retention sweep (dry run by default; deletion only on closed periods).
        "task": "apps.ops.tasks.retention_cleanup",
        "schedule": crontab(hour=3, minute=30, day_of_week=6),  # Saturdays 03:30
    },
}

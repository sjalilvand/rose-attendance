"""Operational Celery tasks — retention sweep (dry run by default).

Approved policy (§34 decisions #1/#2/#6 and section 15): details (events,
messages, notifications) older than three Jalali months are candidates for
deletion ONLY after their period is closed; summaries and request records are
kept >= 24 months. Increment 1 records candidate counts in cleanup_runs with
dry_run=True; actual deletion lands with the reports/closing increment.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)


@shared_task(name="apps.ops.tasks.retention_cleanup")
def retention_cleanup(dry_run: bool = True) -> dict:
    from apps.core.jalali import subtract_jalali_months
    from apps.attendance.models import AttendanceEvent
    from apps.messaging.models import Message, Notification
    from .models import CleanupRun

    run = CleanupRun.objects.create(started_at=timezone.now(), dry_run=dry_run)
    cutoff = subtract_jalali_months(timezone.now(), 3)

    counts = {
        "events": AttendanceEvent.objects.filter(effective_time__lt=cutoff).count(),
        "messages": Message.objects.filter(created_at__lt=cutoff).count(),
        "notifications": Notification.objects.filter(created_at__lt=cutoff).count(),
    }
    run.deleted_events = counts["events"] if not dry_run else 0
    run.deleted_messages = counts["messages"] if not dry_run else 0
    run.deleted_notifications = counts["notifications"] if not dry_run else 0
    run.scoped_periods = [{"cutoff": cutoff.isoformat()}]
    run.details = {"candidates": counts, "mode": "dry-run" if dry_run else "purge"}
    run.finished_at = timezone.now()
    run.status = "DONE"
    run.save()
    log.info("retention_cleanup mode=%s candidates=%s", "dry-run" if dry_run else "purge", counts)
    return {"run_id": run.id, "candidates": counts}

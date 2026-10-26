"""Celery tasks — attendance pipeline activation points (calculation §10)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)


@shared_task(name="apps.attendance.tasks.recompute_nightly")
def recompute_nightly() -> dict:
    """Step 1 of the pipeline: refresh yesterday + today for active employees.

    Pairing after each event happens inline (same transaction); this task is
    the safety net that re-pairs anything missed (e.g., late corrections) —
    recomputation is repeatable by design.

    It also refreshes the CURRENT Jalali month summary for every
    (employee, branch) stream touched in the last three days, so
    monthly_summaries stay fresh without a per-request rollup storm.
    """
    from apps.core.enums import EmploymentStatus
    from apps.core.jalali import current_jalali_period
    from apps.people.models import Employee
    from apps.reports.services import recompute_month_summary
    from .models import AttendanceSession
    from .services import rebuild_pairings

    employees = Employee.objects.filter(employment_status=EmploymentStatus.ACTIVE).only("id", "home_branch_id")
    rebuilt = 0
    rolled_up = 0
    jy, jm = current_jalali_period()
    recent_cutoff = timezone.now() - timezone.timedelta(days=3)
    recent_pairs = set(
        AttendanceSession.objects.exclude(updated_at__lt=recent_cutoff)
        .values_list("employee_id", "branch_id")
    )
    for emp in employees.iterator():
        for branch_id in set(
            list(
                emp.branch_assignments.filter(is_allowed=True).values_list("branch_id", flat=True)
            )
            + [emp.home_branch_id]
        ):
            rebuild_pairings(emp.id, branch_id)
            rebuilt += 1
            if (emp.id, branch_id) in recent_pairs:
                try:
                    recompute_month_summary(emp.id, branch_id, jy, jm)
                    rolled_up += 1
                except Exception:  # pragma: no cover — nightly must not die midway
                    log.exception("monthly rollup failed for emp=%s branch=%s", emp.id, branch_id)
    log.info("recompute_nightly rebuilt %d streams, rolled up %d summaries", rebuilt, rolled_up)
    return {"rebuilt": rebuilt, "rolled_up": rolled_up, "ran_at": timezone.now().isoformat()}

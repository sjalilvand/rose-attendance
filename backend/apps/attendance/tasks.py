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
    """
    from apps.core.enums import EmploymentStatus
    from apps.people.models import Employee
    from .services import rebuild_pairings

    employees = Employee.objects.filter(employment_status=EmploymentStatus.ACTIVE).only("id", "home_branch_id")
    rebuilt = 0
    for emp in employees.iterator():
        for branch_id in set(
            list(
                emp.branch_assignments.filter(is_allowed=True).values_list("branch_id", flat=True)
            )
            + [emp.home_branch_id]
        ):
            rebuild_pairings(emp.id, branch_id)
            rebuilt += 1
    log.info("recompute_nightly rebuilt %d (employee, branch) streams", rebuilt)
    return {"rebuilt": rebuilt, "ran_at": timezone.now().isoformat()}

"""Reports Celery tasks — monthly pipeline activation points (calculation §10)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)


@shared_task(name="apps.reports.tasks.monthly_recompute_guard")
def monthly_recompute_guard() -> dict:
    """On Jalali day 1, fully recompute the PREVIOUS Jalali month.

    Beat runs this daily; it exits immediately on other days. The previous
    month may still receive late offline events during its first days, so
    the final refresh happens one month later; period closing remains an
    explicit HR action (close_month command / API).
    """
    from apps.core.jalali import current_jalali_period
    from apps.reports.services import recompute_month

    jy, jm = current_jalali_period()
    if timezone.localtime().day != 1:
        return {"skipped": "not first Gregorian-day of month window", "period": f"{jy}/{jm:02d}"}

    # On Gregorian day 1 the Jalali month has usually just turned over only if
    # we are within the first days of the Jalali month; compute previous Jalali
    # month deterministically instead of guessing.
    import jdatetime

    today_j = jdatetime.date.fromgregorian(date=timezone.localdate())
    if today_j.day > 3:
        return {"skipped": f"jalali day {today_j.day} > 3", "period": f"{jy}/{jm:02d}"}
    prev_month = today_j.month - 1 or 12
    prev_year = today_j.year - 1 if today_j.month == 1 else today_j.year
    summaries = recompute_month(prev_year, prev_month)
    log.info("monthly guard recomputed %d summaries for %d/%02d", len(summaries), prev_year, prev_month)
    return {"recomputed": len(summaries), "period": f"{prev_year}/{prev_month:02d}"}

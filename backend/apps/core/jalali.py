"""Jalali (Solar Hijri) calendar helpers — approved decision #2 of §34.

The organisation's calendar is Jalali: the 3-month detail retention window,
monthly summary periods (period_year/period_month) and month closures are all
computed on Jalali month boundaries, not Gregorian ones.
"""
from __future__ import annotations

import datetime as dt

import jdatetime
import django.utils.timezone as djtz


def _to_local(moment: dt.datetime) -> dt.datetime:
    if djtz.is_aware(moment):
        return djtz.localtime(moment)
    return djtz.make_aware(moment)


def to_jalali(value: dt.datetime | dt.date) -> jdatetime.date:
    """Convert an aware datetime (Tehran local) or date to a Jalali date."""
    if isinstance(value, dt.datetime):
        return jdatetime.date.fromgregorian(date=_to_local(value).date())
    return jdatetime.date.fromgregorian(date=value)


def jalali_period_of(moment: dt.datetime) -> tuple[int, int]:
    """Return (period_year, period_month) — Jalali — of an aware datetime."""
    j = to_jalali(moment)
    return j.year, j.month


def _jalali_days_in_month(jy: int, jm: int) -> int:
    """Length of a Jalali month (29/30/31) — bugfix: the previous version
    returned the Gregorian day-of-month of the month's last day instead of
    the Jalali day count (caught by tests when 1405/07 returned 22 not 30)."""
    if jm < 12:
        nxt = jdatetime.date(jy, jm + 1, 1)
    else:
        nxt = jdatetime.date(jy + 1, 1, 1)
    last_day = nxt.togregorian() - dt.timedelta(days=1)
    return jdatetime.date.fromgregorian(date=last_day).day


def jalali_month_range(jy: int, jm: int) -> tuple[dt.date, dt.date]:
    """Gregorian (first_day, last_day) of a Jalali month (decision #2 of §34).

    Monthly summary periods, month closures and day iteration all use these
    boundaries — e.g. 1405/07 spans 2026-09-23 .. 2026-10-22.
    """
    first = jdatetime.date(jy, jm, 1).togregorian()
    last = jdatetime.date(jy, jm, _jalali_days_in_month(jy, jm)).togregorian()
    return first, last


def current_jalali_period(moment: dt.datetime | None = None) -> tuple[int, int]:
    """(period_year, period_month) of «now» in Tehran local time."""
    return jalali_period_of(moment or djtz.now())


def subtract_jalali_months(moment: dt.datetime, months: int) -> dt.datetime:
    """Aware datetime minus N Jalali months (day clamped to target month).

    Used for the 3-month detail window (approved decision #2 of §34): the
    window boundary follows the organisation's Jalali calendar, so e.g. the
    window of 1404/05/01 spans exactly Jalali months, not 92 Gregorian days.
    """
    local = _to_local(moment)
    j = jdatetime.date.fromgregorian(date=local.date())
    year, month = j.year, j.month
    for _ in range(months):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    day = min(j.day, _jalali_days_in_month(year, month))
    target_local_date = jdatetime.date(year, month, day).togregorian()
    target_local = dt.datetime.combine(target_local_date, local.time())
    return djtz.make_aware(target_local).astimezone(dt.timezone.utc)

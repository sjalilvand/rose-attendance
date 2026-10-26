"""Startup validation of approved operational thresholds (schema.sql note #1)."""
from django.conf import settings
from django.core.checks import register, Error


@register()
def check_thresholds(app_configs=None, **kwargs) -> list[Error]:
    t = settings.APP_THRESHOLDS  # noqa: F405
    errors: list[Error] = []
    if t["CLOCK_SKEW_MINUTES"] < 1:
        errors.append(Error("CLOCK_SKEW_MINUTES must be >= 1"))
    if t["CLOCK_SKEW_REVIEW_MINUTES"] <= t["CLOCK_SKEW_MINUTES"]:
        errors.append(
            Error("CLOCK_SKEW_REVIEW_MINUTES must be greater than CLOCK_SKEW_MINUTES")
        )
    if t["OFFLINE_MAX_DAYS"] < 1:
        errors.append(Error("OFFLINE_MAX_DAYS must be >= 1"))
    if t["RETENTION_SUMMARY_MONTHS"] < 24:
        # Approved minimum of §34 decision #1/#6 — hard floor.
        errors.append(Error("RETENTION_SUMMARY_MONTHS must be >= 24 (مصوب نسخه ۲٫۱)"))
    if t["SYNC_MAX_BATCH"] < 1:
        errors.append(Error("SYNC_MAX_BATCH must be >= 1"))
    if not (50 <= getattr(settings, "GEOFENCE_RADIUS_MIN", 50) <= 1000):
        errors.append(Error("GEOFENCE_RADIUS_MIN must be within 50..1000"))
    if not (50 <= getattr(settings, "GEOFENCE_RADIUS_MAX", 1000) <= 1000):
        errors.append(Error("GEOFENCE_RADIUS_MAX must be within 50..1000"))
    if getattr(settings, "GEOFENCE_RADIUS_MIN", 50) > getattr(
        settings, "GEOFENCE_RADIUS_MAX", 1000
    ):
        errors.append(Error("GEOFENCE_RADIUS_MIN must be <= GEOFENCE_RADIUS_MAX"))
    return errors

"""Shared API helpers — HR guard, list pagination, error formatting.

Kept dependency-free (no model imports) so any app can import it without
circular-import risk; mirrors the hand-rolled {"count", "results"} response
shape the PWA already consumes.
"""
from __future__ import annotations

from rest_framework.response import Response


def hr_write_guard(user) -> Response | None:
    """Write access to org/scheduling/ledger data — HR / ADMIN / superuser.

    Returns a 403 Response to raise, or None when the caller may proceed.
    """
    if user.is_superuser or user.has_role("HR") or user.has_role("ADMIN"):
        return None
    return Response(
        {"detail": "این عملیات مخصوص منابع انسانی است.", "code": "FORBIDDEN"},
        status=403,
    )


def page_params(request, default_size: int = 50, max_size: int = 200) -> tuple[int, int]:
    """Sanitised ?page / ?page_size for hand-rolled list endpoints."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(request.query_params.get("page_size", default_size))
    except (TypeError, ValueError):
        size = default_size
    return page, max(1, min(max_size, size))


def paginated_response(queryset, page: int, size: int, serialize) -> Response:
    total = queryset.count()
    rows = queryset[(page - 1) * size : page * size]
    return Response(
        {
            "count": total,
            "page": page,
            "page_size": size,
            "results": [serialize(row) for row in rows],
        }
    )


def serializer_errors(errors) -> str:
    """DRF error dict → one Persian one-liner for row-level bulk reports."""
    parts: list[str] = []
    for field, field_errors in errors.items():
        if isinstance(field_errors, list):
            flat = "؛ ".join(str(e) for e in field_errors)
        else:
            flat = str(field_errors)
        parts.append(f"{field}: {flat}")
    return " | ".join(parts)


def hm_minutes(total_minutes: int) -> str:
    """Signed hours:minutes for ledger messages — -150 → «‎-2:30»."""
    minutes = int(total_minutes)
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}:{minutes % 60:02d}"

"""Health endpoint — DB + Redis readiness for the reverse proxy."""
from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        checks = {}
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            checks["database"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            cache.set("health-probe", "1", 5)
            checks["cache"] = "ok" if cache.get("health-probe") == "1" else "error"
        except Exception as exc:  # pragma: no cover
            checks["cache"] = f"error: {type(exc).__name__}"
        healthy = all(v == "ok" for v in checks.values())
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )

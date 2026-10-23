"""Geodesy helpers — branch geofence evaluation (section 7 + decision #3).

Distance is computed in Python with the haversine formula. Rationale: the
punch flow validates a single point against a single branch centre with a
50–1000 m radius; O(1) haversine is precise to ~0.1 % at these scales,
deterministic in tests on any database backend, and avoids per-request GIS
queries. PostGIS spatial predicates remain available for area analytics.
"""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

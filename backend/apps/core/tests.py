"""Core unit tests — haversine geodesy + Jalali arithmetic (decision #2)."""
import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.core.geodesy import haversine_m
from apps.core.jalali import jalali_period_of, subtract_jalali_months, to_jalali


class GeodesyTests(TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_m(35.7, 51.4, 35.7, 51.4), 0.0, places=3)

    def test_known_distance_tehran(self):
        # ~1 arc-minute of latitude is about 1852 m (one nautical mile).
        d = haversine_m(35.7, 51.4, 35.7 + 1 / 60, 51.4)
        self.assertTrue(1800 < d < 1900, d)


class JalaliTests(TestCase):
    def test_period_of_mehr(self):
        # 2026-09-23 Tehran == 1405/07/01 ( Mehr begins)
        moment = timezone.make_aware(dt.datetime(2026, 9, 23, 12, 0))
        year, month = jalali_period_of(moment)
        self.assertEqual((year, month), (1405, 7))

    def test_subtract_three_jalali_months(self):
        # 1405/07/15 minus 3 months must be 1405/04/15 (not 92 Gregorian days)
        moment = timezone.make_aware(dt.datetime(2026, 10, 7, 10, 0))  # ~1405/07/15
        result = subtract_jalali_months(moment, 3)
        jy, jm = jalali_period_of(result)
        self.assertEqual((jy, jm), (1405, 4))
        self.assertEqual(to_jalali(result).day, 15)  # ۱۵ تیر شمسی

    def test_subtract_handles_esfand_29(self):
        # Esfand 29 (leap 1403) minus 1 month -> Bahman 30 clamped to 29
        moment = timezone.make_aware(dt.datetime(2025, 3, 20, 12, 0))  # 1403/12/29
        result = subtract_jalali_months(moment, 1)
        jy, jm = jalali_period_of(result)
        self.assertEqual((jy, jm), (1403, 11))

"""Seed ۳۱ کلینیک مرکزی رز دکتر — ایده‌مپوتنسی، مختصات/نشانی/شعاع ۳۰۰ متر."""

from django.test import TestCase

from apps.orgs.models import Branch, Region
from apps.orgs.seed_clinics import CLINICS, seed_clinic_branches

TEHRAN = next(c for c in CLINICS if c["code"] == "RD-TEHRAN")


class SeedClinicBranchesTests(TestCase):
    def setUp(self):
        # مهاجرت 0003 در ساخت دیتابیسِ تست از قبل کلینیک‌ها را می‌کارد؛
        # این تست‌ها رفتار تابع seed را از صفر می‌سنجند.
        Branch.objects.all().delete()
        Region.objects.all().delete()

    def test_seed_creates_all_clinics_and_provinces(self):
        report = seed_clinic_branches(Region, Branch)
        self.assertEqual(len(report["branches_created"]), len(CLINICS))
        self.assertEqual(len(report["regions_created"]), len(CLINICS))
        self.assertEqual(Branch.objects.count(), len(CLINICS))
        self.assertEqual(Region.objects.count(), len(CLINICS))

    def test_seed_is_idempotent(self):
        seed_clinic_branches(Region, Branch)
        report = seed_clinic_branches(Region, Branch)
        self.assertEqual(report["branches_created"], [])
        self.assertEqual(report["regions_created"], [])
        self.assertEqual(len(report["skipped"]), len(CLINICS))
        self.assertEqual(Branch.objects.count(), len(CLINICS))
        self.assertEqual(Region.objects.count(), len(CLINICS))

    def test_branch_fields_match_employer_table(self):
        seed_clinic_branches(Region, Branch)
        b = Branch.objects.select_related("region").get(code="RD-TEHRAN")
        self.assertEqual(b.name, TEHRAN["name"])
        self.assertEqual(b.region.name, "تهران")
        self.assertEqual(b.region.code, "PRV-TEHRAN")
        self.assertEqual(b.province, "تهران")
        self.assertEqual(b.city, "تهران")
        self.assertEqual(b.address, TEHRAN["address"])
        self.assertAlmostEqual(b.geo_latitude, 35.6892)
        self.assertAlmostEqual(b.geo_longitude, 51.3890)
        self.assertEqual(b.geo_radius_m, 300)  # شعاع کلینیک مصوب ۲٫۱
        self.assertTrue(b.is_active)

    def test_existing_branch_with_same_name_is_not_duplicated(self):
        region = Region.objects.create(code="R1", name="تهران")
        Branch.objects.create(code="B-OLD", name=TEHRAN["name"], region=region)
        report = seed_clinic_branches(Region, Branch)
        self.assertIn(("RD-TEHRAN", "شعبه‌ای با همین نام موجود است"), report["skipped"])
        self.assertNotIn("RD-TEHRAN", report["branches_created"])
        self.assertFalse(Branch.objects.filter(code="RD-TEHRAN").exists())

    def test_existing_region_name_is_reused(self):
        Region.objects.create(code="R9", name="تهران", is_active=True)
        seed_clinic_branches(Region, Branch)
        b = Branch.objects.get(code="RD-TEHRAN")
        self.assertEqual(b.region.code, "R9")  # منطقهٔ دستی کارفرما بازمصرف شد
        self.assertFalse(Region.objects.filter(code="PRV-TEHRAN").exists())

"""اولین اجرای واقعی گزارش انتظامی برای یک شعبه — «شعبهٔ ونک»، مهر ۱۴۰۵.

سناریوی یکپارچه: یک شعبه، پنج پرسنل و شش روز کاری زمان‌بندی‌شده؛ ترددها از
جفت‌سازی واقعی عبور می‌کنند، رول‌آپ تکرارپذیر در مسیر خودِ endpoint اجرا
می‌شود و کارنامهٔ نهایی سلول‌به‌سلول با سناریوی چیده‌شده مقایسه می‌شود.

الگوهای سناریو (شیفت اداری ۹ تا ۱۷ با ۶۰ دقیقه استراحت → ۴۲۰ دقیقه در روز):
- 5001 علی رضایی   — هر ۶ روز سرِ وقت (مرجع تمیز)
- 5002 سارا کریمی  — ۳ روز تأخیر: ۱۵+۳۰+۴۵ = ۹۰ دقیقه
- 5003 رضا محمدی   — ۲ تأخیر (۱۰+۲۰)، ۱ روز غیبت، ۱ خروج زودهنگام
- 5004 مینا احمدی  — ۴ تأخیر (۲۰+۲۵+۳۵+۵۰ = ۱۳۰)، ۲ روز غیبت
- 5005 حسین قاضی  — ۱ جلسهٔ ناقص (ورود بدون خروج در آخرین روز کاری) + ۵ روز سالم
- 6001 کامران موسوی — شعبهٔ شهرک (B200) با ۱ تأخیر؛ نباید در گزارش ونک بیاید

دسترسی: گزارش انتظامی HR-level است — حتی مدیر شعبه ۴۰۳ می‌گیرد (تابلوی
مدیران جایگزین مدیران است؛ §دسترسی گزارش‌ها).

خروجی نمونه: اگر ROSE_DISCIPLINARY_DEMO=/path/file.xlsx ست شود، کارنامهٔ
شعبهٔ ونک در همان مسیر ذخیره می‌شود (نمونهٔ دستی HR / پیش‌نمایش سندباکس).
"""
from __future__ import annotations

import datetime as dt
import io
import os
import uuid

from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.attendance.models import AttendanceEvent
from apps.attendance.services import apply_event_to_pairing
from apps.core.enums import LocationStatus, RestMode
from apps.core.jalali import jalali_month_range
from apps.orgs.models import Branch, Region
from apps.scheduling.models import ScheduledShift, Shift

from .excel_export import DISCIPLINARY_HEADERS, SHEET_DISCIPLINARY, SHEET_GUIDE
from .tests_excel import grant, make_employee, tehran

JY, JM = 1405, 7
VANAK_LAT, VANAK_LON = 35.7597, 51.4100
URL = f"/api/v1/reports/disciplinary/excel/?year={JY}&month={JM}"

# انتظار سناریو به‌ازای هر پرسنل ونک: (روز تأخیر، دقیقه تأخیر، روز غیبت،
# دقیقه غیبت، کسری، جلسهٔ ناقص) — از خودِ موتور رول‌آپ منشأ می‌گیرد نه
# محاسبهٔ دستی؛ اعداد سناریو بالا دقیقاً همین‌ها را تولید می‌کنند.
EXPECTED = {
    "5001": dict(late_days=0, late=0, absence_days=0, absence=0, shortage=0, incomplete=0),
    "5002": dict(late_days=3, late=90, absence_days=0, absence=0, shortage=90, incomplete=0),
    "5003": dict(late_days=2, late=30, absence_days=1, absence=420, shortage=105, incomplete=0),
    "5004": dict(late_days=4, late=130, absence_days=2, absence=840, shortage=130, incomplete=0),
    "5005": dict(late_days=0, late=0, absence_days=1, absence=420, shortage=0, incomplete=1),
}


class BranchDisciplinaryScenarioTests(TestCase):
    """یک شعبه، یک ماه واقعی، پنج الگوی رفتاری متفاوت."""

    @classmethod
    def setUpTestData(cls):
        region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
        cls.vanak = Branch.objects.create(
            code="B300", name="شعبهٔ ونک", region=region,
            geo_latitude=VANAK_LAT, geo_longitude=VANAK_LON,
            geo_radius_m=150, city="تهران",
        )
        cls.shahrak = Branch.objects.create(
            code="B200", name="شعبهٔ شهرک", region=region,
            geo_latitude=35.7600, geo_longitude=51.3700,
            geo_radius_m=150, city="تهران",
        )
        cls.shift = Shift.objects.create(
            code="D1", name="اداری", starts_at=dt.time(9, 0), ends_at=dt.time(17, 0),
            rest_minutes=60, rest_mode=RestMode.FIXED,
        )
        cls.ali, cls.ali_user = make_employee(cls.vanak, "5001", "علی", "رضایی")
        cls.sara, _ = make_employee(cls.vanak, "5002", "سارا", "کریمی")
        cls.reza, _ = make_employee(cls.vanak, "5003", "رضا", "محمدی")
        cls.mina, _ = make_employee(cls.vanak, "5004", "مینا", "احمدی")
        cls.hossein, _ = make_employee(cls.vanak, "5005", "حسین", "قاضی")
        cls.kamran, _ = make_employee(cls.shahrak, "6001", "کامران", "موسوی")
        _, cls.hr_user = make_employee(cls.vanak, "HR-8", "مریم", "ناظم")
        grant(cls.hr_user, "HR")
        _, cls.mgr_user = make_employee(cls.vanak, "MGR-1", "بهرام", "سرپرست")
        grant(cls.mgr_user, "BRANCH_MANAGER", branch=cls.vanak)

        first_day, _last = jalali_month_range(JY, JM)
        cls.workdays = {
            off: first_day + dt.timedelta(days=off)  # مهر ۴..۸ و ۱۱ (شنبه تا چهارشنبه)
            for off in (3, 4, 5, 6, 7, 10)
        }
        cls._seed_attendance()
        cls.api = APIClient()

    # --- seeding helpers ---------------------------------------------------
    @classmethod
    def _punch(cls, emp, branch, day, hour, minute, kind):
        """پانچ GPS-دار پذیرفته‌شده (همان مسیر PWA/اپ، مستقیم در مدل)."""
        when = tehran(day, hour, minute)
        event = AttendanceEvent.objects.create(
            event_uuid=uuid.uuid4(), employee=emp, branch=branch,
            event_type=kind, device_time=when, effective_time=when,
            channel="ANDROID", connection_mode="ONLINE",
            latitude=VANAK_LAT + 0.0005, longitude=VANAK_LON + 0.0005,
            location_accuracy_m=12.0, location_fixed_at=when,
            location_status=LocationStatus.IN_RANGE,
            event_status="ACCEPTED",
        )
        apply_event_to_pairing(event)

    @classmethod
    def _workday(cls, emp, branch, day, in_hm, out_hm):
        """یک روز کاری زمان‌بندی‌شده + ترددهای اختیاری (None = غیبت/ناقص)."""
        ScheduledShift.objects.create(
            employee=emp, branch=branch, work_date=day, shift=cls.shift,
        )
        if in_hm is not None:
            cls._punch(emp, branch, day, in_hm[0], in_hm[1], "CHECK_IN")
        if out_hm is not None:
            cls._punch(emp, branch, day, out_hm[0], out_hm[1], "CHECK_OUT")

    @classmethod
    def _seed_attendance(cls):
        wd = cls.workdays
        for day in wd.values():  # علی — ۶ روز سرِ وقت
            cls._workday(cls.ali, cls.vanak, day, (9, 0), (17, 0))
        sara_late = {3: 15, 5: 30, 10: 45}  # سارا — ۹۰ دقیقه در ۳ روز
        for off, day in wd.items():
            cls._workday(cls.sara, cls.vanak, day, (9, sara_late.get(off, 0)), (17, 0))
        reza_days = {  # رضا — ۲ تأخیر، ۱ خروج زودهنگام، مهر ۱۱ غیبت
            3: ((9, 10), (17, 0)),
            4: ((9, 0), (17, 0)),
            5: ((9, 20), (17, 0)),
            6: ((9, 0), (17, 0)),
            7: ((9, 0), (15, 45)),
        }
        for off, (i, o) in reza_days.items():
            cls._workday(cls.reza, cls.vanak, wd[off], i, o)
        cls._workday(cls.reza, cls.vanak, wd[10], None, None)
        mina_late = {3: 20, 4: 25, 5: 35, 6: 50}  # مینا — مهر ۷ و ۱۱ غیبت
        for off, late in mina_late.items():
            cls._workday(cls.mina, cls.vanak, wd[off], (9, late), (17, 0))
        cls._workday(cls.mina, cls.vanak, wd[7], None, None)
        cls._workday(cls.mina, cls.vanak, wd[10], None, None)
        # حسین — جلسهٔ ناقص در آخرین روز کاری (ورود بدون خروج مهر ۱۱؛ جفت‌سازی
        # بین‌روز است، پس ورود ناقص فقط در انتهای جریان OPEN می‌ماند)
        for off in (3, 4, 5, 6, 7):
            cls._workday(cls.hossein, cls.vanak, wd[off], (9, 0), (17, 0))
        cls._workday(cls.hossein, cls.vanak, wd[10], (9, 0), None)
        # کامران — شعبهٔ شهرک؛ نباید در گزارش ونک بیاید
        for off, late in {3: 25, 4: 0}.items():
            cls._workday(cls.kamran, cls.shahrak, wd[off], (9, late), (17, 0))

    # --- helpers ------------------------------------------------------------
    def _download(self, query: str = "&branch=B300"):
        self.api.force_authenticate(self.hr_user)
        return self.api.get(URL + query)

    @staticmethod
    def _disciplinary_rows(content: bytes) -> list[tuple]:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            rows = list(wb[SHEET_DISCIPLINARY].iter_rows(values_only=True))
        finally:
            wb.close()
        return [r for r in rows[1:] if r[0] is not None]

    # --- tests ---------------------------------------------------------------
    def test_scoped_workbook_matches_scenario(self):
        res = self._download()
        self.assertEqual(res.status_code, 200, getattr(res, "data", res))
        self.assertIn(f"rose-disciplinary-{JY}-{JM:02d}.xlsx", res["Content-Disposition"])
        wb = load_workbook(io.BytesIO(res.content), read_only=True, data_only=True)
        self.assertEqual(wb.sheetnames, [SHEET_DISCIPLINARY, SHEET_GUIDE])
        rows = list(wb[SHEET_DISCIPLINARY].iter_rows(values_only=True))
        self.assertEqual(list(rows[0]), DISCIPLINARY_HEADERS)
        data = [r for r in rows[1:] if r[0] is not None]
        self.assertEqual([r[0] for r in data], ["5001", "5002", "5003", "5004", "5005"])
        self.assertEqual(data[1][1], "سارا کریمی")
        for row in data:
            exp = EXPECTED[row[0]]
            self.assertEqual(row[2], "B300", row)
            self.assertEqual(row[3], f"{JY}/{JM:02d}", row)
            self.assertEqual(row[4], exp["late_days"], row)
            self.assertEqual(row[5], exp["late"], row)
            self.assertEqual(row[6], exp["absence_days"], row)
            self.assertEqual(row[7], exp["absence"], row)
            self.assertEqual(row[8], exp["shortage"], row)
            self.assertEqual(row[9], exp["incomplete"], row)
            self.assertEqual(row[10], 0, row)  # بدون موقعیت مکانی
            self.assertEqual(row[11], 0, row)  # خارج از محدوده
        guide_cells = {str(c) for r in wb[SHEET_GUIDE].iter_rows(values_only=True) for c in r if c}
        self.assertIn("شعبهٔ ونک", guide_cells)
        wb.close()

    def test_unscoped_workbook_spans_all_branches(self):
        res = self._download("")
        self.assertEqual(res.status_code, 200)
        data = self._disciplinary_rows(res.content)
        self.assertEqual(len(data), 6)
        self.assertEqual({r[2] for r in data}, {"B300", "B200"})
        kamran = next(r for r in data if r[0] == "6001")
        self.assertEqual(kamran[4], 1)    # یک روز تأخیر
        self.assertEqual(kamran[5], 25)   # ۲۵ دقیقه
        self.assertEqual(kamran[6], 0)    # بدون غیبت

    def test_reports_are_hr_level_even_for_branch_manager(self):
        self.api.force_authenticate(self.ali_user)
        res = self.api.get(URL + "&branch=B300")
        self.assertEqual(res.status_code, 403)  # کارمند ساده
        self.api.force_authenticate(self.mgr_user)
        res = self.api.get(URL + "&branch=B300")
        self.assertEqual(res.status_code, 403)  # مدیر شعبه هم HR-level است

    def test_unknown_branch_404_and_invalid_month_400(self):
        self.api.force_authenticate(self.hr_user)
        self.assertEqual(self.api.get(URL + "&branch=NOPE").status_code, 404)
        self.assertEqual(
            self.api.get(f"/api/v1/reports/disciplinary/excel/?year={JY}&month=13").status_code,
            400,
        )

    def test_repeat_download_is_repeatable(self):
        first = self._download()
        second = self._download()
        self.assertEqual(self._disciplinary_rows(first.content), self._disciplinary_rows(second.content))

    def test_demo_artifact_dump(self):
        res = self._download()
        self.assertEqual(res.status_code, 200)
        path = os.environ.get("ROSE_DISCIPLINARY_DEMO")
        if path:
            with open(path, "wb") as fh:
                fh.write(res.content)
            print(f"[demo] disciplinary workbook -> {path} ({len(res.content)} bytes)")

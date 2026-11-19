"""ثبت گروهی ۳۱ کلینیک مرکزی رز دکتر در مراکز استان‌ها.

ایده‌مپوتنت — اجرای مکرر امن است:
  python manage.py seed_clinic_branches            # ثبت
  python manage.py seed_clinic_branches --dry-run  # فقط گزارش

نکته: در استقرار بومی، مهاجرت 0003 همین کار را هنگام update-rose.ps1 خودکار
انجام می‌دهد؛ این دستور برای بررسی/بازاجرا و محیط‌های دیگر است.
"""

from django.core.management.base import BaseCommand

from apps.orgs.models import Branch, Region
from apps.orgs.seed_clinics import CLINICS, seed_clinic_branches


class Command(BaseCommand):
    help = f"ثبت {len(CLINICS)} کلینیک مرکزی رز دکتر در مراکز استان‌ها (کد RD-*) — ایده‌مپوتنت"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="فقط گزارش؛ چیزی ثبت نمی‌شود",
        )

    def handle(self, *args, **options):
        report = seed_clinic_branches(Region, Branch, dry_run=options["dry_run"])
        mode = "بررسی بدون ثبت (dry-run)" if report["dry_run"] else "ثبت"
        self.stdout.write(f"== کلینیک‌های مرکزی رز دکتر — {mode} ==")
        self.stdout.write(f"مناطق جدید: {len(report['regions_created'])}")
        for code in report["regions_created"]:
            self.stdout.write(self.style.MIGRATE_HEADING(f"  + منطقه {code}"))
        self.stdout.write(f"شعب ساخته‌شده: {len(report['branches_created'])}")
        for code in report["branches_created"]:
            self.stdout.write(self.style.SUCCESS(f"  + شعبه {code}"))
        if report["skipped"]:
            self.stdout.write(f"ردشده (از قبل موجود): {len(report['skipped'])}")
            for code, reason in report["skipped"]:
                self.stdout.write(f"  - {code}: {reason}")
        self.stdout.write(
            self.style.SUCCESS("کامل شد ✓") if not report["dry_run"]
            else self.style.WARNING("بررسی کامل شد — برای ثبت، پرچم --dry-run را بردارید")
        )

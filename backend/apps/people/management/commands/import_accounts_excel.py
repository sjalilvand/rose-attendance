"""ورود گروهی پرسنل + حساب کاربری از فایل اکسل (خط فرمان).

استفاده:
    python manage.py import_accounts_excel "C:\\path\\to\\asami.xlsx"
    python manage.py import_accounts_excel asami.xlsx --dry-run
    python manage.py import_accounts_excel asami.xlsx --job-title "مشاور"

نام کاربری = کد ملی، گذرواژه = شماره موبایل. اجرای دوباره امن است
(ردیف‌های ازقبل‌ثبت‌شده «تکراری» گزارش می‌شوند و دست نمی‌خورند).
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.people.account_importer import AccountImportFormatError, import_accounts


class Command(BaseCommand):
    help = "ساخت گروهی پروندهٔ پرسنلی و حساب کاربری از فایل اکسل (نام کاربری = کد ملی، گذرواژه = موبایل)"

    def add_arguments(self, parser):
        parser.add_argument("file", help="مسیر فایل اکسل (xlsx)")
        parser.add_argument("--dry-run", action="store_true", help="فقط اعتبارسنجی، بدون ثبت")
        parser.add_argument("--job-title", default="مشاور", help="عنوان شغلی ردیف‌های جدید (پیش‌فرض: مشاور)")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"فایل یافت نشد: {path}")
        dry_run = bool(options["dry_run"])
        try:
            report = import_accounts(
                path.read_bytes(), dry_run=dry_run, job_title=str(options["job_title"])
            )
        except AccountImportFormatError as exc:
            raise CommandError(str(exc)) from exc

        mode = "بررسی اولیه (بدون ثبت)" if dry_run else "ثبت"
        self.stdout.write(f"گزارش {mode}:")
        self.stdout.write(f"  مجموع ردیف‌ها: {report['total']}")
        self.stdout.write(f"  ساخته‌شده: {report['created']}")
        self.stdout.write(f"  تکراری (دست نخورده): {report['duplicates']}")
        self.stdout.write(f"  خطادار: {report['errors']}")
        self.stdout.write(f"  شعبه: {report['branch']['code']} — {report['branch']['name']}")
        for row in report["duplicates_detail"]:
            self.stdout.write(self.style.WARNING(f"  تکراری سطر {row['row']}: {row['name']} — {row['message']}"))
        for row in report["errors_detail"]:
            self.stdout.write(self.style.ERROR(f"  خطا سطر {row['row']}: {row['name']} — {row['message']}"))
        if dry_run and report["created"]:
            self.stdout.write("برای ثبت نهایی، همان دستور را بدون --dry-run اجرا کنید.")

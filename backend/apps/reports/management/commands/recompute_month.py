"""Recompute Jalali-month summaries — pipeline step 1 (calculation-rules §9).

Examples:
    python manage.py recompute_month --jyear 1405 --jmonth 7
    python manage.py recompute_month --jyear 1405 --jmonth 7 --branch B100
    python manage.py recompute_month --jyear 1405 --jmonth 7 --employee 12345
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.orgs.models import Branch
from apps.people.models import Employee
from apps.reports.services import month_scope_pairs, recompute_month, recompute_month_summary


class Command(BaseCommand):
    help = "بازمحاسبه خلاصه‌های ماهانه (پرسنل × شعبه × ماه شمسی) — تکرارپذیر"

    def add_arguments(self, parser):
        parser.add_argument("--jyear", type=int, required=True, help="سال شمسی، مثل ۱۴۰۵")
        parser.add_argument("--jmonth", type=int, required=True, help="ماه شمسی ۱ تا ۱۲")
        parser.add_argument("--branch", type=str, default=None, help="فقط این کد شعبه")
        parser.add_argument("--employee", type=str, default=None, help="فقط این کد پرسنلی")
        parser.add_argument(
            "--force", action="store_true",
            help="بازمحاسبه حتی دوره‌های بسته‌شده (فقط با مجوز منابع انسانی)",
        )

    def handle(self, *args, **opts):
        jy, jm = opts["jyear"], opts["jmonth"]
        if not (1 <= jm <= 12):
            raise CommandError("jmonth باید بین ۱ و ۱۲ باشد.")

        branch_id = None
        if opts["branch"]:
            branch = Branch.objects.filter(code=opts["branch"]).first()
            if branch is None:
                raise CommandError(f"شعبه {opts['branch']} یافت نشد.")
            branch_id = branch.id

        if opts["employee"]:
            emp = Employee.objects.filter(personnel_code=opts["employee"]).first()
            if emp is None:
                raise CommandError(f"پرسنل {opts['employee']} یافت نشد.")
            pairs = {
                p for p in month_scope_pairs(jy, jm, branch_id) if p[0] == emp.id
            }
            count = 0
            for employee_id, b_id in sorted(pairs):
                recompute_month_summary(employee_id, b_id, jy, jm, force=opts["force"])
                count += 1
        else:
            summaries = recompute_month(jy, jm, branch_id=branch_id, force=opts["force"])
            count = len(summaries)

        self.stdout.write(
            self.style.SUCCESS(f"بازمحاسبه ماه {jy}/{jm:02d} برای {count} ردیف انجام شد.")
        )

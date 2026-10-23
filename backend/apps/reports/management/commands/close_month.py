"""Close a Jalali period — six-step flow of calculation-rules §9.

Examples:
    python manage.py close_month --jyear 1405 --jmonth 7
    python manage.py close_month --jyear 1405 --jmonth 7 --branch B100 --notes "..."
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.orgs.models import Branch
from apps.reports.services import close_month


class Command(BaseCommand):
    help = "بستن دوره ماهانه با کنترل‌های شش‌مرحله‌ای (تردد ناقص، درخواست‌ها، رسیدگی‌ها)"

    def add_arguments(self, parser):
        parser.add_argument("--jyear", type=int, required=True)
        parser.add_argument("--jmonth", type=int, required=True)
        parser.add_argument("--branch", type=str, default=None, help="بستن فقط یک شعبه")
        parser.add_argument("--username", type=str, default=None, help="کاربر بستن‌دهنده")
        parser.add_argument("--notes", type=str, default="")

    def handle(self, *args, **opts):
        jy, jm = opts["jyear"], opts["jmonth"]
        branch = None
        if opts["branch"]:
            branch = Branch.objects.filter(code=opts["branch"]).first()
            if branch is None:
                raise CommandError(f"شعبه {opts['branch']} یافت نشد.")

        closed_by = None
        if opts["username"]:
            from apps.people.models import User

            closed_by = User.objects.filter(username=opts["username"]).first()
            if closed_by is None:
                raise CommandError(f"کاربر {opts['username']} یافت نشد.")

        try:
            closure = close_month(
                jy=jy, jm=jm, closed_by=closed_by, branch=branch, notes=opts["notes"]
            )
        except ValidationError as exc:
            raise CommandError(f"بستن دوره متوقف شد: {exc.messages[0]}")
        self.stdout.write(
            self.style.SUCCESS(
                f"دوره {jy}/{jm:02d} بسته شد (closure#{closure.id} — {closure.scope})."
            )
        )

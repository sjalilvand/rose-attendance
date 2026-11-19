"""۳۱ کلینیک مرکزی رز دکتر در مراکز استان‌ها — جدول کارفرما (۱۴۰۵/۰۸/۰۹).

ثبت ایده‌مپوتنت: با کد RD-* موجود یا نام شعبهٔ تکراری دوباره نمی‌سازد.
شعاع مجاز هر کلینیک ۳۰۰ متر (پیش‌فرض کلینیک مصوب ۲٫۱)؛ مختصات/نشانی عیناً
از جدول کارفرما. با update-rose.ps1 خودکار اجرا می‌شود — کارفرما کاری ندارد.
"""

from django.db import migrations

from apps.orgs.seed_clinics import (
    CLINIC_BRANCH_CODES,
    CLINIC_REGION_CODES,
    CLINICS,
    seed_clinic_branches,
)


def forwards(apps, schema_editor):
    seed_clinic_branches(
        apps.get_model("orgs", "Region"),
        apps.get_model("orgs", "Branch"),
    )


def backwards(apps, schema_editor):
    Branch = apps.get_model("orgs", "Branch")
    Region = apps.get_model("orgs", "Region")
    Branch.objects.filter(code__in=CLINIC_BRANCH_CODES).delete()
    # مناطق فقط اگر خالی باشند حذف می‌شوند (PROTECT شعبه‌ها را نگه می‌دارد)
    for region in Region.objects.filter(code__in=CLINIC_REGION_CODES):
        if not region.branches.exists():
            region.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("orgs", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

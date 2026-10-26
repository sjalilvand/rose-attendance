"""Seed the default leave-type catalog.

These are editable catalog rows (HR can rename/deactivate via admin) — not
versioned calculation rules (section 10), so a sensible default seed is safe.
Leave balances/accrual policies remain an HR workbook input (phase-2 list).
"""
from django.db import migrations


ROWS = [
    ("ANNUAL", "استحقاقی", True, True, False),
    ("SICK", "استعلاجی", True, True, True),
    ("MARRIAGE", "ازدواج", False, True, False),
    ("BEREAVEMENT", "فوت بستگان", False, True, False),
    ("MATERNITY", "زایمان", False, True, False),
    ("UNPAID", "بدون حقوق", True, False, False),
]


def seed(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    for code, name, is_hourly, is_paid, requires_attachment in ROWS:
        LeaveType.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "is_hourly": is_hourly,
                "is_paid": is_paid,
                "requires_attachment": requires_attachment,
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.filter(code__in=[r[0] for r in ROWS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("leaves", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

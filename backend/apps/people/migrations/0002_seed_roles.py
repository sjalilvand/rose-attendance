"""Seed the six canonical roles (schema.sql roles comment / section 3)."""
from django.db import migrations

ROLES = [
    ("EMPLOYEE", "پرسنل"),
    ("BRANCH_MANAGER", "مدیر شعبه"),
    ("REGION_MANAGER", "مدیر منطقه"),
    ("HR", "منابع انسانی"),
    ("ADMIN", "ادمین سامانه"),
    ("AUDITOR", "حسابرس"),
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("people", "Role")
    for code, name in ROLES:
        Role.objects.get_or_create(code=code, defaults={"name": name})


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("people", "Role")
    Role.objects.filter(code__in=[c for c, _ in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]

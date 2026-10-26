"""Make users.employee nullable — system admin accounts have no personnel file.

Production incident on deployment 711f63a: `createsuperuser --noinput` failed
with NotNullViolation on users.employee_id, because the OneToOneField was NOT
NULL. Admin accounts (superuser without employee) must be able to exist; all
business flows still require an employee.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0002_seed_roles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="employee",
            field=models.OneToOneField(
                blank=True,
                help_text="پروندهٔ پرسنلی؛ برای کاربران سیستمی مثل superuser می‌تواند تهی باشد",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="user_account",
                to="people.employee",
            ),
        ),
    ]

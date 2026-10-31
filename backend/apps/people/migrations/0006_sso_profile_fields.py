"""SSO profile fields on User — full identity transferred from Rose Hub.

Phase 65: the Rose Hub SSO token now carries the complete counselor identity
(nationalId, mobile, province, provinceCode, clinic alongside email/name).
These additive blank columns store that profile on the local account and are
refreshed on every rose-sso login (source of truth: Rose Hub). Existing rows
(system accounts) keep blank values.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0005_ssousedtoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="full_name",
            field=models.CharField(blank=True, help_text="نام و نام خانوادگی (رز هاب)", max_length=200),
        ),
        migrations.AddField(
            model_name="user",
            name="mobile",
            field=models.CharField(blank=True, help_text="موبایل (رز هاب)", max_length=20),
        ),
        migrations.AddField(
            model_name="user",
            name="national_id",
            field=models.CharField(blank=True, help_text="کد ملی — نام کاربری رز هاب", max_length=15),
        ),
        migrations.AddField(
            model_name="user",
            name="province",
            field=models.CharField(blank=True, help_text="استان", max_length=80),
        ),
        migrations.AddField(
            model_name="user",
            name="province_code",
            field=models.CharField(blank=True, help_text="کد استان", max_length=10),
        ),
        migrations.AddField(
            model_name="user",
            name="clinic",
            field=models.CharField(blank=True, help_text="کلینک محل خدمت", max_length=200),
        ),
    ]

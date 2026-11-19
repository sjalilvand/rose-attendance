"""فاز ۷۲ — بند ۶: مرکز/کلینک با مختصات نقشه از رز هاب روی حساب کاربر.

رز هاب در پاسخ /api/sso/profile علاوه بر مشخصات پایه، شیء «center» و
«clinicCenter» (شامل نام، آدرس، عرض/طول جغرافیایی و شعاع تردد) و نام
مدیریت متبوع و مدیر مستقیم را می‌فرستد؛ این ستون‌های افزودی آن داده‌ها
را روی حساب محلی نگه می‌دارند تا UI حضور و غیاب بتواند مرکز خدمت را با
نقشه نشان دهد. منبع حقیقت همچنان رز هاب است.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0006_sso_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="hub_center_name",
            field=models.CharField(blank=True, help_text="نام مرکز تخصیص (رز هاب)", max_length=200),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_center_address",
            field=models.CharField(blank=True, help_text="آدرس مرکز تخصیص (رز هاب)", max_length=300),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_center_lat",
            field=models.FloatField(blank=True, help_text="عرض جغرافیایی مرکز (رز هاب)", null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_center_lng",
            field=models.FloatField(blank=True, help_text="طول جغرافیایی مرکز (رز هاب)", null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_center_radius_m",
            field=models.PositiveIntegerField(blank=True, help_text="شعاع مجاز تردد مرکز (رز هاب)", null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_clinic_name",
            field=models.CharField(blank=True, help_text="نام کلینیک خدمت با نقشه (رز هاب)", max_length=200),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_clinic_lat",
            field=models.FloatField(blank=True, help_text="عرض جغرافیایی کلینیک (رز هاب)", null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_clinic_lng",
            field=models.FloatField(blank=True, help_text="طول جغرافیایی کلینیک (رز هاب)", null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_management",
            field=models.CharField(blank=True, help_text="مدیریت متبوع (رز هاب)", max_length=120),
        ),
        migrations.AddField(
            model_name="user",
            name="hub_manager_name",
            field=models.CharField(blank=True, help_text="مدیر مستقیم (رز هاب)", max_length=120),
        ),
    ]

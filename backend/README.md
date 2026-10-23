<div dir="rtl">

# بک‌اند — سامانه حضور و غیاب رز سفید (Django + DRF)

پیاده‌سازی فاز ۲ (گام ۱) بر اساس `docs/analysis/schema.sql` و اسناد تحلیل فاز ۱ و سند مصوب نسخه ۲٫۱.

## گام ۱ شامل چه چیزی است؟

| حوزه | محتوا |
|---|---|
| `config/` | settings سه‌لایه (base/development/production)، Celery، ASGI/WSGI، آستانه‌های مصوب محیطی |
| `apps/core` | Enumهای مشترک، مدل پایه زمان‌دار، تقویم شمسی (تصمیم مصوب #۲)، هاورساین، اعتبارسنجی آستانه‌ها |
| `apps/orgs` | `regions`، `branches` (شعاع ۵۰–۱۰۰۰ متر، پیش‌فرض ۱۵۰/۳۰۰ — تصمیم مصوب #۳)، تخصیص تاریخ‌دار پرسنل-شعبه |
| `apps/people` | `employees`، `users` سفارشی (Argon2id، قفل حساب)، نقش‌ها/مجوزها/تخصیص‌های تاریخ‌دار، نشست دستگاه‌ها |
| `apps/scheduling` | تقویم و تعطیلات، شیفت‌ها (شامل شیفت شب)، الگوهای چرخشی، شیفت‌های برنامه‌ریزی‌شده با بازه مطلق |
| `apps/attendance` | رویدادها/بازه‌ها/اصلاحات + موتور تردد: ژئوفنس «خارج محدوده» برچسبی، CLOCK_SKEW ±۵ دقیقه، آفلاین ۷ روز → NEEDS_REVIEW، جفت‌سازی زمان‌مؤثری تکرارپذیر |
| `apps/leaves` | انواع مرخصی، مرخصی/مأموریت با بخش‌های چندشعبه‌ای مستقل (تصمیم مصوب #۵)، گردش مانده |
| `apps/messaging` | گفتگو، پیام (idempotent با UUID)، اعلان‌ها |
| `apps/rules` | قواعد نسخه‌دار داده‌ای با اولویت BRANCH > REGION > GLOBAL (تصمیم مصوب #۷) |
| `apps/reports` | خلاصه ماهانه شمسی و بستن دوره |
| `apps/ops` | بارگذاری Excel، حسابرسی (بدون متن پیام/مختصات کامل — §۲۷)، اجرای پاکسازی |

## اجرای محلی

```bash
cd backend
python3 -m venv /path/to/venv && source /path/to/venv/bin/activate
pip install -r requirements.in          # برای توسعه
python manage.py migrate
python manage.py createsuperuser
python manage.py test                   # ۳۵ تست خط لوله تردد
python manage.py runserver
```

تنظیمات توسعه به‌طور پیش‌فرض SQLite است (موتور تردد به GIS وابسته نیست؛ فاصله با هاورساین در پایتون محاسبه می‌شود تا تست‌ها قابل حمل باشند). استقرار همان `compose.yml` ریشه است.

## قرارداد API (گام ۱)

| مسیر | متد | شرح |
|---|---|---|
| `/api/v1/auth/token/` | POST | ورود JWT + قفل حساب پس از ۵ خطا (۱۵ دقیقه) |
| `/api/v1/auth/token/refresh/` | POST | تمدید توکن |
| `/api/v1/me/` | GET | پروفایل + نقش‌ها |
| `/api/v1/time/` | GET | زمان سرور برای سنجش افست ساعت دستگاه (CLOCK_SKEW) |
| `/api/v1/attendance/events/punch/` | POST | ثبت تردد آنلاین (idempotent با `event_uuid`) |
| `/api/v1/attendance/events/sync/` | POST | همگام‌سازی دسته آفلاین (≤ `SYNC_MAX_BATCH`=۱۰۰) |
| `/api/v1/attendance/events/` | GET | تاریخچه ۳ ماه شمسی اخیر پرسنل |
| `/api/v1/attendance/sessions/` | GET | بازه‌های حضور (واحد پاکسازی §۱۵) |
| `/api/v1/attendance/review-queue/` | GET | صف NEEDS_REVIEW برای مدیر شعبه/منابع انسانی |
| `/api/v1/attendance/review-queue/approve/` | POST | تأیید زمان مؤثر با لایه TIME_FIX (بدون بازنویسی تاریخچه) |
| `/api/v1/reports/monthly-summaries/` | GET | خلاصه‌های ماهانه (نگهداری ≥ ۲۴ ماه) |
| `/api/v1/health/` | GET | سلامت DB/Redis برای پروکسی |

## متغیرهای محیطی آستانه‌دار (مصوب ۲٫۱)

`CLOCK_SKEW_MINUTES=5`، `CLOCK_SKEW_REVIEW_MINUTES=60` (آستانه ابهام)، `OFFLINE_MAX_DAYS=7`، `RETENTION_SUMMARY_MONTHS=24`، `SYNC_MAX_BATCH=100`، `UPLOAD_MAX_MB=10`، `LOCATION_MAX_ACCURACY_M=100`.

در production همه از `.env` خوانده و در استارتاپ اعتبارسنجی می‌شوند (`apps/core/validation.py`)؛ کف مصوب ≥ ۲۴ ماه برای نگهداری خلاصه به‌صورت check سختگیرانه کنترل می‌شود.

## محدودیت‌های گام ۱ (گام‌های بعدی)

- محاسبات روزانه/ماهانه (LATE/REST/OVERTIME) و `monthly_summaries` تولید نمی‌شوند — شبه‌کد سند محاسبه §۷–§۱۰، گام ۲.
- محاسبه دقیق بازه «سه ماه» در APIها فعلاً معادل تقویمی شمسی است و پاکسازی واقعی فقط `dry_run` ثبت می‌کند (حذف فقط پس از بستن دوره — گام ۲).
- WebSocket پیام‌رسانی (Channels) و نقاط API درخواست‌ها/گفتگو/بارگذاری Excel — گام ۳.
- `branch_geo_points` (چند نقطه مجاز شعبه، PostGIS) — گام ۳؛ فعلاً مکانیزم فعال، مرکز + شعاع شعبه است.
- API رزرو/برنامه شیفت و صفحه‌های مدیریت — گام ۳.

## تست‌ها

۳۵ تست پوشش‌دهنده: برچسب‌گذاری ژئوفنس (۱۵۰/۳۰۰ متر و بازه ۵۰–۱۰۰۰)، انحراف ساعت آنلاین/آفلاین، آستانه ۷ روز، idempotency، قواعد جفت‌سازی (کامل/باز/ترتیب نامعتبر/ورود تکراری/شیفت شب)، تکرارپذیری بازسازی، قفل حساب و جریان رسیدگی مدیر.

</div>

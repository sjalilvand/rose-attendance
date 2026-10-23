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
python manage.py test                   # ۱۳۳ تست خط لوله تردد، محاسبات، درخواست‌ها، ورود گروهی، WebSocket، مدیریت سازمان و ماندهٔ مرخصی
python manage.py runserver
```

تنظیمات توسعه به‌طور پیش‌فرض SQLite است (موتور تردد به GIS وابسته نیست؛ فاصله با هاورساین در پایتون محاسبه می‌شود تا تست‌ها قابل حمل باشند). استقرار همان `compose.yml` ریشه است.

## قرارداد API (گام ۱)

| مسیر | متد | شرح |
|---|---|---|
| `/api/v1/auth/token/` | POST | ورود JWT + قفل حساب پس از ۵ خطا (۱۵ دقیقه) |
| `/api/v1/auth/token/refresh/` | POST | تمدید توکن |
| `/api/v1/me/` | GET | پروفایل + نقش‌ها |
| `/api/v1/people/import/` | POST | بارگذاری گروهی پرسنل (xlsx) — HR/ADMIN؛ form: `file`، `dry_run` |
| `/api/v1/people/import/template/` | GET | دریافت قالب xlsx ورود گروهی |
| `/api/v1/time/` | GET | زمان سرور برای سنجش افست ساعت دستگاه (CLOCK_SKEW) |
| `/api/v1/attendance/events/punch/` | POST | ثبت تردد آنلاین (idempotent با `event_uuid`) |
| `/api/v1/attendance/events/sync/` | POST | همگام‌سازی دسته آفلاین (≤ `SYNC_MAX_BATCH`=۱۰۰) |
| `/api/v1/attendance/events/` | GET | تاریخچه ۳ ماه شمسی اخیر پرسنل |
| `/api/v1/attendance/sessions/` | GET | بازه‌های حضور (واحد پاکسازی §۱۵) |
| `/api/v1/attendance/review-queue/` | GET | صف NEEDS_REVIEW برای مدیر شعبه/منابع انسانی |
| `/api/v1/attendance/review-queue/approve/` | POST | تأیید زمان مؤثر با لایه TIME_FIX (بدون بازنویسی تاریخچه) |
| `/api/v1/reports/monthly-summaries/` | GET | خلاصه‌های ماهانه (نگهداری ≥ ۲۴ ماه) |
| `/api/v1/org/regions/` | GET/POST/PATCH | مدیریت مناطق (نوشتن HR/ADMIN) |
| `/api/v1/org/branches/` | GET/POST/PATCH | مدیریت شعب با فیلتر/جست‌وجو/صفحه‌بندی (نوشتن HR/ADMIN) |
| `/api/v1/org/branches/bulk/` | POST | upsert گروهی شعب بر مبنای کد + dry run |
| `/api/v1/scheduling/shifts/` | GET/POST/PATCH | کاتالوگ شیفت‌ها (نوشتن HR/ADMIN) |
| `/api/v1/scheduling/shifts/bulk/` | POST | upsert گروهی شیفت‌ها + dry run |
| `/api/v1/leaves/ledger/balances/` | GET | ماندهٔ هر نوع مرخصی (خود شخص؛ مدیران سراسری با `employee=`) |
| `/api/v1/leaves/ledger/` | GET | گردش‌های دفتر مانده یک پرسنل (HR/ADMIN) |
| `/api/v1/leaves/ledger/seed/` | POST | ثبت گروهی مانده اولیه/استحقاق/تعدیل با تاریخ شمسی + dry run (HR/ADMIN) |
| `/api/v1/leaves/ledger/adjust/` | POST | تعدیل سریع مانده با دقیقهٔ مثبت/منفی (HR/ADMIN) |
| `/api/v1/health/` | GET | سلامت DB/Redis برای پروکسی |

## متغیرهای محیطی آستانه‌دار (مصوب ۲٫۱)

`CLOCK_SKEW_MINUTES=5`، `CLOCK_SKEW_REVIEW_MINUTES=60` (آستانه ابهام)، `OFFLINE_MAX_DAYS=7`، `RETENTION_SUMMARY_MONTHS=24`، `SYNC_MAX_BATCH=100`، `UPLOAD_MAX_MB=10`، `LOCATION_MAX_ACCURACY_M=100`.

در production همه از `.env` خوانده و در استارتاپ اعتبارسنجی می‌شوند (`apps/core/validation.py`)؛ کف مصوب ≥ ۲۴ ماه برای نگهداری خلاصه به‌صورت check سختگیرانه کنترل می‌شود.

## گام ۲ فاز ۲ — محاسبات روزانه/ماهانه (تازه)

- **`apps/attendance/calculation.py`** — موتور محاسبه روزانه خالص و تکرارپذیر: کارکرد، کسر استراحت سه‌حالته (FIXED / DEDUCT_IF_SHORT / NONE)، تأخیر/تعجیل پله‌ای از `rule_sets` نسخه‌دار (FLAG_ONLY / DEDUCT / TREAT_AS_ABSENCE_HALF)، غیبت کامل و نیم‌روز، اولویت حضور بر مرخصی (منع دوباره‌شماری §۷٫۱) و پیشنهاد اضافه‌کاری فراتر از `planned_end`.
- **`OvertimeProposal`** — ثبت پیشنهاد و تأیید مدیر (§۷٫۳)؛ فقط دقیقه‌های تأییدشده وارد خلاصه می‌شود.
- **`apps/reports/services.py`** — رول‌آپ (پرسنل × شعبه × ماه شمسی) با مرزهای جلالی (`jalali_month_range`)، ارفاق ماهانه تأخیر، شمارنده‌های کیفی، `rule_set_ids` و **بستن دوره شش‌مرحله‌ای** با کنترل تردد ناقص/درخواست معلق/رسیدگی معلق و قفل دوره بسته.
- **دستورات مدیریتی:** `python manage.py recompute_month --jyear 1405 --jmonth 7 [--branch B100 --employee 12345]` و `python manage.py close_month ...`.
- **APIهای تازه:** `GET /api/v1/attendance/daily/` (تابلوی روزانه مشتق‌شده)، `GET /api/v1/attendance/daily/today/`، `GET|POST /api/v1/attendance/overtime/` (+`approve/`) و افزودن `server_time` و `branches` (با ژئو) به `/me/`.
- **رفع باگ تقویم:** `_jalali_days_in_month` به‌جای طول ماه شمسی، شماره روز میلادی آخرین روز را برمی‌گرداند (اثر در پنجره سه‌ماهه `subtract_jalali_months`) — با تست مرزها کشف و اصلاح شد.

## محدودیت‌های باقی‌مانده (گام ۳)

- WebSocket پیام‌رسانی (Channels) و نقاط API درخواست‌ها/گفتگو/بارگذاری Excel.
- `branch_geo_points` (چند نقطه مجاز شعبه، PostGIS)؛ فعلاً مکانیزم فعال، مرکز + شعاع شعبه است.
- API رزرو/برنامه شیفت، پنل مدیران (React) و جریان رسیدگی صف اضافه‌کاری در UI.

## تست‌ها

۱۳۳ تست پوشش‌دهنده: برچسب‌گذاری ژئوفنس (۱۵۰/۳۰۰ متر و بازه ۵۰–۱۰۰۰)، انحراف ساعت آنلاین/آفلاین، آستانه ۷ روز، idempotency، قواعد جفت‌سازی (کامل/باز/ترتیب نامعتبر/ورود تکراری/شیفت شب)، تکرارپذیری بازسازی، قفل حساب و جریان رسیدگی مدیر؛ به‌علاوه موتور محاسبه، رول‌آپ شمسی، کنترل‌های بستن دوره، APIهای درخواست‌ها و رسیدگی، ورود گروهی پرسنل، WebSocket، و گام ۵ (CRUD و upsert گروهی شعب/شیفت‌ها با تفکیک دسترسی HR، و چرخهٔ کامل LeaveLedger: ثبت مانده، گارد مانده در ثبت، کسر خودکار در تأیید و مانده در صف رسیدگی).

</div>

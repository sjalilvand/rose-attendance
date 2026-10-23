<div dir="rtl" align="right">

# سامانه حضور و غیاب رز سفید 🌹

سامانه مرکزی مدیریت حضور و غیاب سازمانی، مبتنی بر **Android، PWA و استقرار Docker** — طراحی‌شده برای مقیاس حدود **۸٬۵۰۰ پرسنل در ۸۵۰ شعبه و کلینیک**، با زبان فارسی، رابط راست‌به‌چپ و تقویم شمسی.

| موضوع | شرح |
|---|---|
| نسخه سند مرجع | ۲٫۱ |
| وضعیت | فاز ۲ در جریان — گام ۱ هسته بک‌اند · گام ۲ محاسبات و PWA · گام ۳ پنل مدیران و درخواست‌ها · گام ۴ بارگذاری Excel و WebSocket منتشر شد |
| محل استقرار | مرکز داده، قابل دسترسی از اینترنت |
| استقرار | Docker و Docker Compose |

## اصول قطعی پروژه

1. **ثبت تردد بدون GPS مجاز است** و تأیید مدیر نمی‌خواهد.
2. **ثبت آفلاین از نسخه اول وجود دارد** و پس از اتصال، بدون تکرار همگام می‌شود.
3. **جزئیات تردد، موقعیت و پیام سه‌ماهه هستند**؛ خلاصه کارکرد ماهانه حفظ می‌شود.

## پشته فناوری

| بخش | فناوری |
|---|---|
| اپلیکیشن پرسنل | Flutter (Android) |
| PWA و پنل مدیران | React + TypeScript |
| بک‌اند | Django + Django REST Framework + Channels |
| پایگاه داده | PostgreSQL + PostGIS |
| صف کار | Celery + Redis |
| وب‌سرور ورودی | Nginx |
| استقرار | Docker Compose |

## ساختار مخزن

```text
rose-attendance/
├── backend/            # بک‌اند Django
│   ├── config/         # settings سه‌لایه + Celery + ASGI
│   ├── apps/           # core, orgs, people, scheduling, attendance, leaves, messaging, rules, reports, ops
│   ├── requirements.in / requirements.lock (hashed)
│   └── Dockerfile
├── frontend/           # PWA پرسنل (React + TypeScript + Vite)
│   ├── src/pages/      # ورود، ثبت تردد، کارکرد، خلاصه ماه، تنظیمات
│   ├── src/lib/        # JWT، صف آفلاین IndexedDB، ژئو، تقویم شمسی
│   ├── Dockerfile
│   └── nginx.conf
├── deploy/
│   ├── nginx.conf      # پیکربندی مرجع Nginx
│   └── tls/            # محل گواهی‌های TLS (هرگز کامیت نشود)
├── docs/
│   ├── REQUIREMENTS.md # سند جامع نیازمندی‌ها، معماری و استقرار (نسخه ۲٫۱)
│   ├── REQUIREMENTS.pdf# نسخه رسمی PDF سند
│   └── analysis/       # فاز ۱: مدل داده، قواعد محاسبه و طراحی صفحات
├── compose.yml         # استقرار تک‌میزبانی: db, redis, migrate, api, worker, scheduler, gateway
├── update.ps1          # بروزرسانی از گیت‌هاب روی ویندوز (PowerShell)
├── .env.example        # قالب تنظیمات محیط
└── .gitignore
```

## شروع سریع

> ⚠️ راهنمای اجرای محلی بک‌اند و قرارداد API در [backend/README.md](backend/README.md) و راهنمای PWA در [frontend/README.md](frontend/README.md) است. استقرار تولید همان پایپ‌لاین Docker زیر است.

```bash
# ۱) قالب تنظیمات را آماده کنید
cp .env.example .env

# ۲) فایل‌های Secret را بسازید (وارد مخزن نمی‌شوند)
mkdir -p secrets deploy/tls
printf '<django-secret-key>' > secrets/django_secret.txt
printf '<db-password>'       > secrets/db_password.txt
# گواهی TLS: fullchain.pem و privkey.pem را در deploy/tls قرار دهید

# ۳) ساخت و اجرا
docker compose config
docker compose build
docker compose up -d db redis
docker compose run --rm migrate
docker compose up -d api worker scheduler gateway
docker compose ps
```

## بروزرسانی از گیت‌هاب روی سیستم خودتان (PowerShell)

بار اول:

```powershell
git clone https://github.com/sjalilvand/rose-attendance.git C:\rose-attendance
cd C:\rose-attendance
copy .env.example .env
.\update.ps1
```

هر بار بروزرسانی بعدی فقط:

```powershell
cd C:\rose-attendance
.\update.ps1
```

اسکریپت `update.ps1` به‌ترتیب `git pull` → آماده‌سازی خودکار `secrets/` و `.env` → `docker compose build` → `up -d` → مهاجرت دیتابیس را انجام می‌دهد (اولین اجرا: فایل‌های secret تصادفی می‌سازد و `localhost` را به ALLOWED_HOSTS اضافه می‌کند). بدون Docker با `-SkipDocker` اجرا کنید. جایگزین گرافیکی: در **GitHub Desktop** دکمه «Fetch origin → Pull origin» و سپس اجرای همان دستورات compose.

## گام ۲ فاز ۲ چه چیزی اضافه کرد؟

- **موتور محاسبه روزانه** (`apps/attendance/calculation.py`): کارکرد، کسر استراحت سه‌حالته، تأخیر/تعجیل پله‌ای از `rule_sets` نسخه‌دار، غیبت کامل/نیم‌روز، اولویت حضور بر مرخصی (منع دوباره‌شماری) — مطابق سند قواعد فاز ۱ §۶–§۸.
- **تولید `monthly_summaries`**: رول‌آپ (پرسنل × شعبه × ماه شمسی) با مرزهای تقویم جلالی، ارفاق ماهانه تأخیر، شمارنده‌های کیفی و ثبت نسخه قواعد استفاده‌شده؛ دستور `recompute_month` و تسک شبانه + نگهبان اول ماه.
- **اضافه‌کاری فقط با تأیید**: پیشنهاد خودکار از خروج فراتر از شیفت، صف تأیید مدیر (`attendance/overtime`) و ورود به خلاصه پس از تأیید (§۷٫۳).
- **بستن دوره**: `close_month` با کنترل‌های شش‌مرحله‌ای (تردد ناقص، درخواست‌های معلق، رویدادهای NEEDS_REVIEW) و قفل نسخه قطعی.
- **PWA پرسنل** (`frontend/`): ثبت ورود/خروج آنلاین/آفلاین با صف IndexedDB و همگام‌سازی خودکار، تابلو روزانه، کارکرد ماه شمسی، خلاصه ماهانه و اندازه‌گیری اختلاف ساعت — بدون ردیابی مستمر GPS.

## گام ۳ فاز ۲ چه چیزی اضافه کرد؟

- **API درخواست‌ها** (`/api/v1/requests/`): ثبت مرخصی/مأموریت با شکست خودکار به بخش‌های (شعبه × بازه) طبق مصوبهٔ #۵، لغو درخواست در انتظار، فهرست «درخواست‌های من» با وضعیت ترکیبی، و `leave-types` برای فرم.
- **رسیدگی مستقل بخش‌ها** (`/api/v1/requests/queue/`): صف مدیران با محدودهٔ نقش (مدیر شعبه فقط شعب خودش؛ HR/ادمین/منطقه سراسری)، تصمیم APPROVE/REJECT با ثبت `approval_actions`، ترکیب وضعیت کل (هر رد → رد، همه تأیید → تأیید) و رول‌آپ ماهِ شمسیِ بخش پس از تصمیم.
- **تابلوی مدیران** (`/api/v1/reports/manager-board/`): ردیف محاسبه‌شدهٔ هر پرسنل شعبه در تاریخ مشخص (ورود/خروج، تأخیر، غیبت، اضافه‌کاری پیشنهادی، تردد ناقص، مرخصی) — مشتق‌شده و بدون ذخیرهٔ اضافه.
- **پنل رسیدگی PWA** (`/approvals`): چهار زبانه — درخواست‌ها، تردد نیازمند رسیدگی (اصلاح زمان مؤثر)، اضافه‌کاری و تابلوی شعبه؛ زبانه فقط برای کاربران دارای نقش مدیریتی نمایش داده می‌شود.
- **صفحهٔ درخواست‌های پرسنل** (`/requests`): ثبت مرخصی/مأموریت با انتخاب نوع و بازه، پیگیری وضعیت هر بخش و لغو.
- تأیید مرخصی بلافاصله در محاسبهٔ کارکرد اعمال می‌شود (موتور از قبل `RequestSegment`های تأییدشده را مصرف می‌کند). ماندهٔ مرخصی (LeaveLedger) پس از دریافت ورودی HR فعال می‌شود.

### گام ۴ فاز ۲ — بارگذاری Excel پرسنل + WebSocket اطلاع‌رسانی زنده (تازه)

- **ورود گروهی پرسنل** (`/api/v1/people/import/`): آپلود xlsx با upsert بر مبنای کد پرسنلی، اعتبارسنجی ردیف‌به‌ردیف (خطاها گزارش و رد می‌شوند، بقیه ثبت می‌شوند)، پشتیبانی تاریخ شمسی، حالت «بررسی بدون ثبت» (dry run)، دریافت قالب آماده از `/api/v1/people/import/template/`؛ دسترسی HR/ADMIN؛ تخصیص اختیاری شیفت به‌صورت الگوی شمسی سطح شعبه (کدهای `IMP-...`). صفحهٔ PWA در `/import` فقط برای HR/ADMIN در ناوبری ظاهر می‌شود.
- **WebSocket اطلاع‌رسانی زنده** (`/ws/notifications/`): JWT در query string (توسط میان‌افزار اختصاصی اعتبارسنجی می‌شود)، گروه اختصاصی هر کاربر، رویدادهای تصمیم (تأیید/رد درخواست، تأیید تردد نیازمند رسیدگی، تأیید اضافه‌کاری) هم در جدول `notifications` پایدار می‌شوند و هم به‌صورت زنده به PWA می‌رسند (toast). لایهٔ کانال Redis (DB 1) جدا از برور Celery (DB 0).

## مستندات

- **[سند جامع نیازمندی‌ها، معماری و استقرار (نسخه ۲٫۱)](docs/REQUIREMENTS.md)** — مرجع رسمی پروژه؛ شامل نیازمندی‌های کسب‌وکار، سیاست داده، معماری Docker، API و امنیت و فازهای اجرا.
- **[نسخه PDF سند](docs/REQUIREMENTS.pdf)** — نسخه رسمی قابل چاپ و امضا.
- **[موارد تصویب‌شده (بخش ۳۴)](docs/REQUIREMENTS.md#۳۴-موارد-تصویب‌شده-نسخه-۲۱)** — ده تصمیم قطعی‌شده با تأیید کارفرما در نسخه ۲٫۱؛ مبنای طراحی و قرارداد.
- **[فاز ۱ ـ تحلیل نهایی](docs/analysis/README.md)** — [مدل داده نهایی و ERD](docs/analysis/01-data-model.md) · [DDL اسکلت PostgreSQL](docs/analysis/schema.sql) · [قواعد محاسبه کارکرد](docs/analysis/02-calculation-rules.md) · [طراحی صفحات Android و PWA](docs/analysis/03-screens.md).
- **[بک‌اند Django](backend/README.md)** — مدل‌ها، موتور تردد و محاسبات، API نسخه ۱، WebSocket، Celery و ۱۱۰ تست خط لوله.
- **[PWA پرسنل](frontend/README.md)** — گام ۲ فاز ۲: صفحات، معماری آفلاین و اجرای محلی.

## نکته امنیتی

- پوشه `secrets/`، فایل `.env` و گواهی‌های `deploy/tls/` هرگز وارد مخزن نمی‌شوند (`.gitignore`).
- پورت‌های PostgreSQL و Redis فقط روی شبکه داخلی Docker در دسترس‌اند.
- توکن‌های دسترسی Git نباید در کد یا مستندات ذخیره شوند؛ پس از استفاده، توکن‌های افشاشده فوراً باطل شوند.

</div>

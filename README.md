<div dir="rtl" align="right">

# سامانه حضور و غیاب رز سفید 🌹

سامانه مرکزی مدیریت حضور و غیاب سازمانی، مبتنی بر **Android، PWA و استقرار Docker** — طراحی‌شده برای مقیاس حدود **۸٬۵۰۰ پرسنل در ۸۵۰ شعبه و کلینیک**، با زبان فارسی، رابط راست‌به‌چپ و تقویم شمسی.

| موضوع | شرح |
|---|---|
| نسخه سند مرجع | ۲٫۱ |
| وضعیت | مبنای طراحی، توسعه، آزمون و برآورد پروژه |
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
├── backend/            # بک‌اند Django (فاز توسعه)
│   └── Dockerfile
├── frontend/           # PWA و پنل مدیران (فاز توسعه)
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
├── .env.example        # قالب تنظیمات محیط
└── .gitignore
```

## شروع سریع

> ⚠️ این مخزن در مرحله سند و اسکلت استقرار است؛ کد اپلیکیشن در فازهای توسعه تکمیل می‌شود (بخش ۳۲ سند).

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

## مستندات

- **[سند جامع نیازمندی‌ها، معماری و استقرار (نسخه ۲٫۱)](docs/REQUIREMENTS.md)** — مرجع رسمی پروژه؛ شامل نیازمندی‌های کسب‌وکار، سیاست داده، معماری Docker، API و امنیت و فازهای اجرا.
- **[نسخه PDF سند](docs/REQUIREMENTS.pdf)** — نسخه رسمی قابل چاپ و امضا.
- **[موارد تصویب‌شده (بخش ۳۴)](docs/REQUIREMENTS.md#۳۴-موارد-تصویب‌شده-نسخه-۲۱)** — ده تصمیم قطعی‌شده با تأیید کارفرما در نسخه ۲٫۱؛ مبنای طراحی و قرارداد.
- **[فاز ۱ ـ تحلیل نهایی](docs/analysis/README.md)** — [مدل داده نهایی و ERD](docs/analysis/01-data-model.md) · [DDL اسکلت PostgreSQL](docs/analysis/schema.sql) · [قواعد محاسبه کارکرد](docs/analysis/02-calculation-rules.md) · [طراحی صفحات Android و PWA](docs/analysis/03-screens.md).

## نکته امنیتی

- پوشه `secrets/`، فایل `.env` و گواهی‌های `deploy/tls/` هرگز وارد مخزن نمی‌شوند (`.gitignore`).
- پورت‌های PostgreSQL و Redis فقط روی شبکه داخلی Docker در دسترس‌اند.
- توکن‌های دسترسی Git نباید در کد یا مستندات ذخیره شوند؛ پس از استفاده، توکن‌های افشاشده فوراً باطل شوند.

</div>

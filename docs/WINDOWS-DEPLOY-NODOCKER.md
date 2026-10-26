<div dir="rtl" align="right">

# راهنمای استقرار بدون Docker روی Windows Server 2025 (حالت HTTP — فاز توسعه)

این راهنما سامانه «رز سفید» را **بدون Docker** و کاملاً نیتیو روی ویندوز بالا می‌آورد: پایتون مستقیم + PostgreSQL/PostGIS نیتیو + Redis ویندوزی + Nginx برای ویندوز. معماری نهایی:

```text
مرورگر/اپ  ──HTTP 8080──▶  Nginx (سرویس RoseNginx)
                             ├─ /            → فایل‌های frontend\dist (PWA)
                             ├─ /static/     → backend\staticfiles (پنل ادمین)
                             ├─ /api/  /admin/ → پروکسی به Daphne (RoseApi :8000)
                             └─ /ws/         → پروکسی WebSocket به :8000
سرویس‌های ویندوزی: RoseRedis (127.0.0.1:6379) · RoseApi (Daphne/ASGI) ·
                   RoseWorker + RoseBeat (Celery) · RoseNginx · postgresql-x64-16
```

> پیش‌نیاز سخت‌افزاری: رم ≥ ۸ گیگ، فضای خالی C ≥ ۳۰ گیگ، دسترسی اینترنت برای دانلود نصب‌کننده‌ها.

## گام ۱ — جمع‌آوری مشخصات سرور (توصیه‌شده)

```powershell
# PowerShell با دسترسی Administrator
cd C:\rose-attendance
powershell -ExecutionPolicy Bypass -File .\server-inventory.ps1
```

گزارش `RoseServerReport_*.txt` روی دسکتاپ ساخته می‌شود؛ آن را برای کارشناس استقرار ارسال کنید (به‌ویژه اگر پورت 8080 اشغال است تا پورت جایگزین تعیین شود).

## گام ۲ — نصب پیش‌نیازها (Python 3.12 + Node 22 + PostgreSQL 16 + PostGIS + Redis + Nginx + NSSM)

```powershell
cd C:\rose-attendance
git pull
powershell -ExecutionPolicy Bypass -File .\install-rose-prereq.ps1
```

این اسکریپت idempotent است (هرچه موجود باشد دوباره نصب نمی‌شود) و همه‌چیز را در `C:\rose-stack` می‌ریزد. چند نکته:

- رمز `postgres` هنگام نصب تصادفی ساخته و در `C:\rose-stack\secrets\pg_postgres_password.txt` ذخیره می‌شود.
- اگر نصب خودکار **PostGIS** ناموفق بود، StackBuilder را دستی اجرا کنید: منوی استارت → StackBuilder → گزینه PostgreSQL 16 → **Categories → Spatial Extensions → PostGIS for PostgreSQL 16**.
- قانون فایروال پورت 8080 هم در همین گام باز می‌شود.
- پس از پایان، خلاصه نصب نمایش داده می‌شود؛ هر قلم `FAILED` را طبق پیام راهنما دستی نصب کنید و دوباره اسکریپت را اجرا کنید.

## گام ۳ — راه‌اندازی اپلیکیشن (دیتابیس + وابستگی‌ها + build + مهاجرت)

```powershell
cd C:\rose-attendance
powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "یک-رمز-قوی-انتخاب-کنید"
```

کاری که این اسکریپت می‌کند:

1. ساخت `secrets\django_secret.txt` و `secrets\db_password.txt` (مقادیر تصادفی).
2. ساخت کاربر `rose_app`، دیتابیس `rose_attendance` و افزونه `postgis` در PostgreSQL.
3. ساخت venv در `C:\rose-stack\venv` و نصب `backend\requirements.lock` (+ daphne برای WebSocket).
4. تولید `C:\rose-stack\rose-backend.env` (تنظیمات اتصال، ALLOWED_HOSTS برای `130.185.73.157`، CSRF برای پورت 8080).
5. اجرای `migrate` و `collectstatic`.
6. `npm ci` و `npm run build` برای فرانت‌اند (خروجی: `frontend\dist`).
7. ساخت کاربر مدیر `admin` با رمزی که در پارامتر دادید.

> اگر pip یا npm وسط کار خطا داد، همان دستور را دوباره اجرا کنید (idempotent است) و در صورت تکرار، خروجی خطا را برای کارشناس بفرستید.

## گام ۴ — اجرا

**حالت سرویس ویندوزی (توصیه‌شده — پس از ریبوت خودکار بالا می‌آید):**

```powershell
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -InstallServices
```

**حالت کنسول موقت (برای تست سریع، لاگ جلوی چشم):**

```powershell
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -Console
```

سایر دستورات: `-Status` (وضعیت سرویس‌ها و پورت‌ها)، `-Stop`، `-Start`، `-Restart`، `-UninstallServices`.

## گام ۵ — تست

| بررسی | آدرس/دستور | نتیجه مورد انتظار |
|---|---|---|
| سلامت API | `curl http://130.185.73.157:8080/api/v1/health/` | JSON سالم |
| PWA | `http://130.185.73.157:8080/` در مرورگر | صفحه ورود |
| وضعیت سرویس‌ها | `.\run-rose.ps1 -Status` | همه Running، پورت‌های 8000/8080/6379/5432 گوش می‌دهند |
| لاگ‌ها | `C:\rose-stack\logs\*.log` | بدون خطای قرمز |

> **نکته مهم:** در حالت HTTP، PWA پرسنل (JWT) و API و WebSocket کامل کار می‌کنند، اما **لاگین پنل ادمین جنگو** (`/admin`) به‌دلیل کوکی `Secure` تنظیمات production روی HTTP انجام نمی‌شود — پس از گرفتن SSL خودبه‌خود رفع می‌شود. مدیریت داده‌ها در این فاصله از طریق PWA (پنل HR/ADMIN) انجام می‌شود.

## عیب‌یابی رایج

- **پورت 8080 اشغال است** → در `C:\rose-stack\nginx\conf\nginx.conf` مقدار `listen 8080` را تغییر دهید، `run-rose.ps1 -Restart` بزنید و `DJANGO_CSRF_TRUSTED_ORIGINS` در `C:\rose-stack\rose-backend.env` را همگام کنید.
- **RoseApi استارت نمی‌شود** → `C:\rose-stack\logs\RoseApi.err.log` را ببینید؛ رایج‌ترین علت: PostgreSQL/Redis بالا نیست یا `rose-backend.env` ناقص است.
- **خطای GIS/GDAL در migrate** → مطمئن شوید PostGIS از طریق StackBuilder نصب شده و مسیر `C:\Program Files\PostgreSQL\16\bin` در PATH سیستم است؛ سپس سرور را ری‌استارت کنید.
- **WebSocket وصل نمی‌شود** → daphne باید نصب باشد (`C:\rose-stack\venv\Scripts\python.exe -m pip show daphne`)؛ اگر نیست نصبش کنید و `run-rose.ps1 -Restart` بزنید.
- **از بیرون باز نمی‌شود ولی روی خود سرور باز است** → قانون فایروال 8080 و DNAT روتر/فایروال سازمانی را بررسی کنید.
- **پس از تغییر rose-backend.env** → `run-rose.ps1 -Restart` الزامی است.

## مهاجرت بعدی به SSL (پس از پایان توسعه)

1. دامنه را به IP سرور متصل کنید و گواهی بگیرید (Let's Encrypt یا سازمانی).
2. در `C:\rose-stack\nginx\conf\nginx.conf` بلاک HTTPS با `ssl_certificate` اضافه و ۸۰ را به ۴۴۳ ریدایرکت کنید؛ قانون فایروال 443 را باز کنید.
3. در `C:\rose-stack\rose-backend.env` مقدار `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain` و ALLOWED_HOSTS به دامنه.
4. `run-rose.ps1 -Restart`.

## بهره‌برداری

- بکاپ دیتابیس: `"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -h 127.0.0.1 -U rose_app -d rose_attendance -F c -f C:\rose-backups\rose-%DATE%.dump`
- لاگ‌ها با چرخش خودکار در `C:\rose-stack\logs\` (هر ۱۰MB).
- سرویس‌ها روی `SERVICE_AUTO_START` هستند؛ پس از ریبوت سرور به‌صورت خودکار بالا می‌آیند.
- `secrets\`، `rose-backend.env` و گواهی‌ها هرگز commit/push نشوند.

</div>

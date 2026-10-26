# استقرار «رز سفید» روی Windows Server بدون Docker

این راهنما اجرای کامل سامانه روی **Windows Server 2025** بدون هیچ‌گونه Docker/WSL است.
همه‌چیز به‌صورت سرویس‌های بومی ویندوز اجرا می‌شود و بعد از ری‌بوت سرور خودکار بالا می‌آید.

---

## ۱) معماری و پورت‌ها (نسخه ۲)

| جزء | سرویس ویندوزی | پورت | توضیح |
|---|---|---|---|
| Nginx (درگاه) | `RoseNginx` | **8085** | سرو PWA + پروکسی API/WS/ادمین — از اینترنت در دسترس |
| Django + Channels (Daphne) | `RoseApi` | **3005** | ASGI با پشتیبانی WebSocket — از اینترنت هم در دسترس |
| Celery Worker | `RoseWorker` | — | صف‌ها (pool=solo مخصوص ویندوز) |
| Celery Beat | `RoseBeat` | — | کارهای زمان‌بندی‌شده |
| Redis (tporadowski 5.0.14) | `RoseRedis` | 6379 | فقط localhost — بروکر Celery + channel layer |
| PostgreSQL 16 | `postgresql-x64-16` | 5432 | فقط localhost — دیتابیس `rose_attendance` |

- آدرس وب‌اپ: `http://130.185.73.157:8085/`
- پنل ادمین: `http://130.185.73.157:8085/admin/` (با تنظیمات `windows_http` روی HTTP هم لاگین می‌شود)
- تست مستقیم بک‌اند: `http://130.185.73.157:3005/api/v1/health/`
- پوشه‌ها: برنامه‌های جانبی در `C:\rose-stack`، مخزن کد در `C:\rose-attendance`

---

## ۲) مراحل نصب (به‌ترتیب)

همه دستورات را در PowerShell **Run as Administrator** اجرا کنید:

```powershell
cd C:\rose-attendance
git pull

# ۱) پیش‌نیازها (Python/Node/PostgreSQL/PostGIS/Redis/NSSM/Nginx + فایروال 8085 و 3005)
powershell -ExecutionPolicy Bypass -File .\install-rose-prereq.ps1

# ۲) اپ: دیتابیس + وابستگی‌ها + مهاجرت‌ها + build فرانت‌اند + ادمین
powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز-قوی-دلخواه"

# ۳) سرویس‌های ویندوزی (خودکار پس از ری‌بوت)
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -InstallServices

# وضعیت
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -Status
```

سپس در مرورگر: `http://130.185.73.157:8085/`

---

## ۳) تغییرات نسخه ۲ (علت خطاهای قبلی)

| مشکل قبلی | راه‌حل v2 |
|---|---|
| `winget` نصب PostgreSQL را ناتمام گذاشت | دانلود مستقیم نصب‌کننده EDB با **BITS** (مقاوم در قطعی شبکه) + fallback «بسته باینری» (بدون نصب‌کننده، با initdb و ثبت سرویس) + تلاش مجدد winget |
| دانلود NSSM از `nssm.cc` خطای 503 | منبع اول: میرور **GitHub** (`kirillkovalenko/nssm`)؛ سپس nssm.cc |
| PostGIS ناموجود → خطا | PostGIS حالا **اختیاری** است — برنامه (ENGINE جنگو = postgresql عادی) بدون آن هم کامل کار می‌کند؛ آخرین بسته خودکار از فهرست OSGeo انتخاب می‌شود |
| پنل ادمین جنگو روی HTTP لاگین نمی‌شد | فایل تنظیمات جدید `backend/config/settings/windows_http.py` (کوکی‌های Secure فقط تا رسیدن SSL خاموش می‌شوند) |
| پورت‌های 8080/8000 | طبق درخواست: **وب 8085** و **بک‌اند 3005** — فایروال هر دو خودکار باز می‌شود |
| تداخل Windows Defender | مسیر `C:\rose-stack` به‌عنوان استثنا ثبت می‌شود |

---

## ۴) عیب‌یابی

### لاگ‌ها
```
C:\rose-stack\logs\RoseApi.err.log      ← خطاهای بک‌اند
C:\rose-stack\logs\RoseWorker.err.log   ← خطاهای صف
C:\rose-stack\logs\RoseNginx.err.log    ← خطاهای وب‌سرور
C:\rose-stack\logs\RoseRedis.out.log
```

### PostgreSQL نصب نشد؟
اسکریپت سه مسیر را امتحان می‌کند (نصب‌کننده EDB → بسته باینری → winget). اگر هر سه شکست خورد:
1. نصب‌کننده را دستی از `https://www.enterprisedb.com/downloads/postgres-postgresql-downloads` بگیرید (PostgreSQL 16 Windows x64) و نصب کنید (رمز فراموش نشود).
2. رمز را در `C:\rose-stack\secrets\pg_postgres_password.txt` ذخیره کنید (فقط متن رمز).
3. دوباره `install-rose-prereq.ps1` و سپس `install-rose-app.ps1` را اجرا کنید.

### تغییرات نسخه ۳ (رمز PostgreSQL و مدیر سرویس)
- `install-rose-app.ps1` حالا پارامتر **`-PostgresPassword`** دارد؛ اگر داده شود ذخیره می‌شود و در اجراهای بعدی استفاده می‌گردد. منبع رمز در خروجی اسکریپت چاپ می‌شود.
- اسکریپت جدید **`reset-postgres-password.ps1`** رمز postgres نمونه‌ی موجود (مثلاً rosepsy) را وقتی رمزش را نمی‌دانید ریست می‌کند.
- مدیر سرویس از NSSM به **WinSW** تغییر اولویت یافت (دانلود از GitHub Releases پایدار است)؛ `run-rose.ps1` اگر NSSM نبود، خودش WinSW را دانلود و استفاده می‌کند.

### تغییرات نسخه ۳.۴ (فرانت‌اند آماده + ریست رمز ادمین)
- خروجی build فرانت‌اند (`frontend/dist`) حالا داخل مخزن قرار دارد — سرور به Node.js/npm نیاز ندارد و صفحه اصلی بدون build کار می‌کند. برای تغییر آینده‌ی فرانت‌اند، build را روی ماشینی با Node انجام دهید و پوشه `frontend/dist` را به‌روز کنید (یا Node.js را روی سرور نصب و `install-rose-app.ps1` را دوباره اجرا کنید).
- اسکریپت جدید **`reset-admin-password.ps1`** برای ریست رمز کاربر مدیر پنل (`/admin`) — اگر رمز فراموش شد:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\reset-admin-password.ps1 -NewPassword "رمز-جدید"
  # بدون پارامتر: رمز تصادفی می‌سازد و در خروجی نشان می‌دهد
  ```
  (نام کاربری پیش‌فرض: `admin`؛ کاربر در صورت نبود با دسترسی ابرکاربر ساخته می‌شود.)
- رفع race در به‌روزرسانی پیکربندی سرویس‌ها (حالا تا Stopped شدن کامل سرویس و آزاد شدن فایل exe صبر می‌کند — علت حذف شدن `RoseWorker` در اجرای قبلی همین بود).

### تغییرات نسخه ۳.۳ (میرور PyPI برای سرورهای ایران + سرویس PostgreSQL)
- **نصب وابستگی‌ها وقتی `files.pythonhosted.org` در دسترس نیست** (خطای `ReadTimeoutError` در pip): اسکریپت حالا خودش چند منبع را به‌ترتیب امتحان می‌کند — میرور ایرانی **RunFlare**، سپس Aliyun، Tsinghua و در نهایت PyPI رسمی — و اولین منبع سالم را برای نصب استفاده می‌کند. با `-PipIndexUrl` هم می‌توانید میرور دلخواه بدهید:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز" -PipIndexUrl "https://mirror-pypi.runflare.com/simple"
  ```
- اگر `npm ci` شکست بخورد، خودکار با میرور `registry.npmmirror.com` تلاش می‌شود.
- سرویس اختیاری **`RosePostgres`** با کلید `-WithPostgres`: اگر PostgreSQL شما سرویس ویندوزی ندارد (مثل نمونه‌ی rosepsy که با pg_ctl بالا می‌آید)، سرویس ویندوزی می‌سازد تا پس از ری‌بوت سرور دیتابیس هم خودکار بالا بیاید (حساب NetworkService + دسترسی icacls به datadir). اگر نمونه PostgreSQL از قبل سرویس داشته باشد، دست نمی‌زند. اگر شروع سرویس ناموفق باشد، سرویس حذف و PostgreSQL همان‌طور دستی روشن می‌شود تا نصب متوقف نشود:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -InstallServices -WithPostgres
  ```
- رفع باگ اندازه لاگ WinSW (قبلاً هر ۱۰ کیلوبایت می‌چرخید — حالا ۱۰ مگابایت).
- `createsuperuser` حالا idempotent است (اگر admin موجود باشد رمز را دست نمی‌زند).
- در شکست شروع هر سرویس، چند خط آخر لاگ همان سرویس چاپ می‌شود.

### رمز postgres را نمی‌دانید / خطای password authentication failed؟
این خطا یعنی PostgreSQL در حال اجراست ولی رمز خوانده‌شده از
`C:\rose-stack\secrets\pg_postgres_password.txt` (از اجرای قبلی) با رمز واقعی نمونه‌ی شما نمی‌خواند.

**راه A — رمز را می‌دانید** (رمزی که هنگام نصب PostgreSQL/rosepsy تعیین شده):
```powershell
powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -PostgresPassword "رمز-واقعی" -AdminPassword "رمز-ادمین"
```

**راه B — رمز را نمی‌دانید:** اسکریپت ریست، pg_hba.conf را موقتاً trust می‌کند، رمز را عوض می‌کند و همه‌چیز را برمی‌گرداند (سرویس PostgreSQL چند ثانیه ری‌استارت می‌شود):
```powershell
powershell -ExecutionPolicy Bypass -File .\reset-postgres-password.ps1 -NewPassword "رمز-جدید-قوی"
powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز-ادمین"
```
رمز جدید در `C:\rose-stack\secrets\pg_postgres_password.txt` ذخیره می‌شود تا مراحل بعدی خودکار باشند.

### مدیر سرویس‌ها (WinSW / NSSM)
- اگر `C:\rose-stack\winsw\WinSW-x64.exe` موجود باشد → سرویس‌ها با WinSW ساخته می‌شوند (XML هر سرویس: `C:\rose-stack\winsw\<نام-سرویس>\<نام-سرویس>.xml`).
- اگر `C:\rose-stack\nssm\nssm.exe` موجود باشد → همان NSSM قبلی استفاده می‌شود.
- اگر هیچ‌کدام نباشد → `run-rose.ps1 -InstallServices` خودش WinSW را دانلود می‌کند (GitHub Releases).
- وضعیت/شروع/توقف همه‌ی سرویس‌ها مستقل از ابزار با `Get-Service Rose*` / `Start-Service` / `Stop-Service` کار می‌کند.

### سرویسی بالا نیامد؟
```powershell
Get-Service Rose*
Get-Service RoseApi | Format-List Name, Status
type C:\rose-stack\logs\RoseApi.err.log
# شروع مجدد تک‌سرویس:
Restart-Service RoseApi
```

### پورت اشغال است؟
```powershell
Get-NetTCPConnection -State Listen -LocalPort 8085,3005 | Select LocalPort,OwningProcess
Get-Process -Id (Get-NetTCPConnection -LocalPort 8085 -State Listen).OwningProcess
```

### ادمین لاگین نمی‌شود؟
- بررسی کنید `C:\rose-stack\rose-backend.env` شامل `DJANGO_SETTINGS_MODULE=config.settings.windows_http` باشد.
- اگر قبلاً مرورگر نسخه HTTPS را دیده، کش کوکی را پاک کنید (Ctrl+Shift+Del).
- رمز ادمین را دوباره ست کنید:
```powershell
$env:PGPASSWORD = (Get-Content C:\rose-stack\secrets\pg_postgres_password.txt -Raw).Trim()
$env:DJANGO_SETTINGS_MODULE = "config.settings.windows_http"
$env:DJANGO_SECRET_KEY_FILE = "C:\rose-attendance\secrets\django_secret.txt"
$env:DB_PASSWORD_FILE = "C:\rose-attendance\secrets\db_password.txt"
cd C:\rose-attendance\backend
C:\rose-stack\venv\Scripts\python.exe manage.py changepassword admin
```

---

## ۵) به‌روزرسانی برنامه (نسخه جدید کد)

```powershell
cd C:\rose-attendance
git pull
powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -SkipFrontend   # اگر فرانت تغییر نکرده
# اگر فرانت هم تغییر کرده: بدون -SkipFrontend اجرا کنید
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -Restart
```

---

## ۶) مهاجرت آینده به SSL

بعد از دریافت گواهی معتبر (مثلاً Let's Encrypt با دامنه):

1. گواهی (`fullchain.pem`/`privkey.pem` → `fullchain.cer`/`key.key` با فرمت PEM) را در `C:\rose-stack\tls` بگذارید.
2. در `rose-nginx-windows.conf` یک بلوک `listen 443 ssl;` با `ssl_certificate`/`ssl_certificate_key` اضافه و `listen 8085` را به redirect تبدیل کنید؛ سپس فایل را به `C:\rose-stack\nginx\conf\nginx.conf` کپی و `RoseNginx` را ری‌استارت کنید.
3. فایروال 443 را باز کنید: `New-NetFirewallRule -DisplayName "Rose HTTPS 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow`
4. در `C:\rose-stack\rose-backend.env` مقدار `DJANGO_SETTINGS_MODULE` را به `config.settings.production` برگردانید و `DJANGO_CSRF_TRUSTED_ORIGINS` را به `https://دامنه-شما` تغییر دهید؛ سپس `Restart-Service RoseApi`.
5. تمدید خودکار گواهی (Win-ACME) را هم می‌توان بعداً اضافه کرد — در صورت نیاز، کیت مربوطه تهیه می‌شود.

---

## ۷) نکات امنیتی

- Redis و PostgreSQL فقط روی `127.0.0.1` گوش می‌دهند و از اینترنت قابل دسترسی نیستند.
- پورت 3005 (بک‌اند مستقیم) در فایروال باز است برای تست؛ پس از راه‌اندازی می‌توانید ببندید:
  `Remove-NetFirewallRule -DisplayName "Rose Attendance API 3005"`
- رمزهای تصادفی: `C:\rose-stack\secrets\pg_postgres_password.txt` (postgres)، `C:\rose-attendance\secrets\` (جنگو/دیتابیس). پوشه secrets هرگز نباید commit یا عمومی شود.
- توکن GitHub که در گفتگو استفاده شد، پس از پایان استقرار باید **revoke** شود.

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

---

## ۸) تغییرات نسخه ۳.۵ — رفع ۵۰۰ سراسری و شکست ریست رمز ادمین

### خطای اول: Server Error (500) هنگام ورود — دیتابیس پایین بود

**ریشه:** در نسخه‌های قبل، `-WithPostgres` فقط سرویس‌هایی با نام `postgresql*` را «سرویس موجود PostgreSQL» می‌شناخت. روی این سرور، PostgreSQL متعلق به استک rosepsy با نام سرویس `rosepsy-pg` نصب است که با این الگو تطبیق نمی‌کرد. در نتیجه:

1. یک سرویس تکراری `RosePostgres` روی همان datadir سرویس rosepsy-pg (`C:/rosepsy/data/pgdata`) ساخته شد؛
2. postgres در حالِ اجرا «نمونه دستی» فرض شد و با pg_ctl متوقف شد (rosepsy-pg به Stopped رفت)؛
3. postgres داخل سرویس RosePostgres پس از آن دیگر بالا نیامد → هیچ چیزی روی پورت دیتابیس گوش نمی‌داد → `database: error: OperationalError` → خطای 500 در لاگین پنل ادمین و اپلیکیشن.

**رفع در نسخه ۳.۵:**

- تشخیص سرویس PostgreSQL خارجی دومرحله‌ای شد: تطبیق نام (`postgres`، `pgsql` یا توکن مستقل `pg` مانند `rosepsy-pg`) به‌علاوه بررسی سرویس‌هایی که پروسه postgres.exe را اجرا می‌کنند.
- اگر سرویس خارجی پیدا شود: سرویس تکراری RosePostgres به‌صورت خودکار Stop و Uninstall می‌شود، سرویس خارجی Start می‌شود و RosePostgres اصلاً ساخته نمی‌شود.
- `Stop-ManualPostgres` دیگر هیچ پروسه متعلق به سرویس ویندوزی را نمی‌کشد (بررسی Win32_Service روی PID مالک پورت و PID والد آن) و در شکست pg_ctl، پروسه یتیم را force-kill می‌کند.
- وابستگی RoseApi به سرویس PostgreSQL واقعی (RosePostgres یا سرویس خارجی) در XML سرویس ثبت می‌شود تا ترتیب بوت درست باشد.
- `-Start` / `-Restart` هم در صورت وجود، سرویس PostgreSQL خارجی را قبل از بقیه شروع می‌کنند.
- `-Status` پورت دیتابیس را از `DATABASE_URL` فایل env می‌خواند (به‌جای 5432 ثابت).

### خطای دوم: شکست ریست رمز ادمین («unrecognized arguments»)

**ریشه:** PowerShell 5.1 هنگام پاس‌دادن آرگومان چندخطی دارای کوتیشن دوتایی به برنامه بومی (`manage.py shell -c $code`) کوتیشن‌های داخلی را escape نمی‌کند؛ رشته پایتون وسطش می‌شکند و argparse آرگومان‌های اضافی می‌بیند.

**رفع در نسخه ۳.۵:** کد پایتون در فایل `C:\rose-stack\rose-reset-admin-user.py` نوشته و با `shell -c "exec(open(r'...', encoding='utf-8').read())"` اجرا می‌شود (بدون هیچ کوتیشن دوتایی در خط فرمان). رمز همچنان از متغیر محیطی پاس می‌شود و در خط فرمان/log ظاهر نمی‌شود. یک پیش‌آزمون اتصال دیتابیس هم اضافه شد تا اگر PostgreSQL بالا نیست، پیام واضح بدهد.

### ریکاوری همین سرور (پس از git pull)

```powershell
cd C:\rose-attendance
# ۱) اصلاح سرویس دیتابیس: حذف خودکار RosePostgres تکراری + شروع rosepsy-pg + شروع بقیه سرویس‌ها
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -InstallServices -WithPostgres
# ۲) ریست رمز ادمین
powershell -ExecutionPolicy Bypass -File .\reset-admin-password.ps1 -NewPassword "رمز-جدید-قوی"
# ۳) بررسی
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -Status
curl http://127.0.0.1:8085/api/v1/health/
```

اگر `rosepsy-pg` بالا نیامد و در لاگ آن خطای دسترسی پوشه دادهشد، دسترسی اضافه‌شده توسط نسخه‌های قبل را حذف کنید و دوباره شروع کنید:

```powershell
icacls C:\rosepsy\data\pgdata /remove:g *S-1-5-20 /T
Start-Service rosepsy-pg
```

---

## ۹) تغییرات نسخه ۳.۶ — اپ موبایل با QR + مدیریت پرسنل خارج از پنل ادمین

- **صفحهٔ نصب موبایل (`/install`)**: صفحهٔ عمومی با QR Code آدرس سامانه + راهنمای نصب اندروید/iOS/دسکتاپ. لینک آن از پایین صفحهٔ ورود هم در دسترس است. کد QR در `frontend/public/qr-install.svg` است؛ اگر آدرس سرور عوض شود باید دوباره ساخته شود. «اپ موبایل» همان PWA است: با «افزودن به صفحهٔ اصلی» مثل اپ واقعی تمام‌صفحه اجرا می‌شود و ثبت تردد آفلاین هم دارد.
- **صفحهٔ مدیریت (`/management`)**: فقط برای نقش‌های HR/ADMIN/مدیرکل دیده می‌شود (خارج از پنل ادمین). امکانات: فهرست/جست‌وجوی پرسنل، افزودن و ویرایش پروندهٔ پرسنلی، ساخت حساب کاربری و اتصال به پرونده، ریست گذرواژه (با رفع قفل)، فعال/غیرفعال کردن کاربران، و دکمهٔ «ساخت پرسنل نمونه» برای تست ورود (پیش‌فرض ۳۰ نفر، نام کاربری از ادامهٔ آخرین کد پرسنلی، گذرواژهٔ یکسان).
- **API های جدید** (فقط HR/ADMIN): `GET/POST /api/v1/management/personnel/`، `PATCH .../personnel/{id}/`، `POST .../personnel/{id}/create-user/`، `GET /api/v1/management/users/`، `PATCH .../users/{id}/`، `POST .../users/{id}/set-password/`، `POST /api/v1/management/seed-demo/`.
- **رفع ۵۰۰ برای حساب‌های بدون پروندهٔ پرسنلی**: کارکرد (history)، کارت امروز، درخواست‌ها و ثبت تردد برای حساب‌هایی که به پروندهٔ پرسنلی وصل نیستند دیگر خطای ۵۰۰ نمی‌دهند؛ پیام روشن «حساب شما به پروندهٔ پرسنلی متصل نیست» (کد `NO_EMPLOYEE_PROFILE`) برمی‌گردد و فهرست‌ها خالی می‌شوند. کافی است مدیر در صفحهٔ «مدیریت» پرونده بسازد یا حساب موجود را به پرونده متصل کند.
- پس از به‌روزرسانی: `run-rose.ps1 -Restart` کافی است (مهاجرت دیتابیس و نصب پکیج جدید لازم نیست).

---

## ۱۰) تغییرات نسخه ۳.۷ — رفع گیر کردن توقف RoseNginx

- علت گیر کردن `-Restart`/`-Stop` روی nginx: سیگنال توقف `-s quit` «خاموشی تدریجی» است و منتظر بسته‌شدن همه اتصال‌های باز (وب‌سوکت PWA کاربران متصل و keep-alive مرورگر) می‌ماند؛ در نتیجه توقف سرویس تا بی‌نهایت طول می‌کشد.
- **RoseNginx حالا با `-s stop` (خاموشی سریع) متوقف می‌شود.**
- XML همه سرویس‌های WinSW دارای `<stoptimeout>20 Sec</stoptimeout>` و `<stopparentprocessfirst>true</stopparentprocessfirst>` است — توقف هرگز بیش از حدود ۲۰ ثانیه طول نمی‌کشد و در صورت پاس ندادن، درخت پروسه به‌اجبار بسته می‌شود.
- تابع جدید `Stop-RoseServiceSafe`: توقف با `sc.exe stop` + انتظار زمان‌دار + force-kill درخت پروسه (`taskkill /T /F`). همهٔ مسیرهای `-Stop`، `-Restart` و `-UninstallServices` از آن استفاده می‌کنند (دیگر کنسول گیر نمی‌کند).
- پیش از شروع RoseNginx، پروسه‌های nginx یتیم (بدون سرویس) خودکار بسته می‌شوند تا تداخل پورت 8085 پیش نیاید.
- رفع فوری بدون آپدیت (اگر کنسول روی «Waiting for service ... to stop» گیر کرد): `Ctrl+C` بزنید و در پنجرهٔ جدید:

```powershell
Get-Process nginx, RoseNginx -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -Start
```

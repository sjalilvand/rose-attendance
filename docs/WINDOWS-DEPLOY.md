<div dir="rtl" align="right">

# راهنمای استقرار روی Windows Server 2025 (بدون SSL — فاز توسعه)

این راهنما نحوهٔ بالا آوردن سامانهٔ حضور و غیاب «رز سفید» روی **Windows Server 2025** با IP عمومی `130.185.73.157` را در حالت **HTTP خالص روی پورت 8080** (بدون گواهی TLS، مخصوص دورهٔ توسعه) شرح می‌دهد. پس از پایان توسعه، طبق بخش ۸ به HTTPS/443 مهاجرت کنید.

## ۰) چرا یک لایه لینوکس لازم است؟

پشتهٔ پروژه (PostgreSQL+PostGIS، Redis، Celery، تصویر Nginx) همگی **کانتینرهای لینوکسی** هستند. ویندوز نمی‌تواند مستقیماً کانتینر لینوکسی اجرا کند؛ بنابراین یکی از دو مسیر زیر لازم است:

| مسیر | توضیح | مجوز |
|---|---|---|
| **الف) WSL2 + Docker Engine** (پیشنهادی) | اوبونتوی سبک داخل WSL2 و Docker Engine استاندارد داخل آن. کاملاً مشابه سرور لینوکسی واقعی | رایگان و متن‌باز |
| ب) Docker Desktop | ساده‌ترین ابزار روی ویندوز؛ docker/compose داخل PowerShell کار می‌کند | برای سازمان بزرگ‌تر از ۲۵۰ نفر نیاز به اشتراک تجاری دارد |

> مقیاس پروژه (~۸٬۵۰۰ پرسنل) عملاً یعنی مسیر «ب» نیاز به لایسنس پولی دارد؛ بنابراین مسیر «الف» توصیهٔ اصلی این سند است. با این حال اگر Docker Desktop موجود است، همهٔ مراحل بخش ۵ فقط با `update-http.ps1` انجام می‌شود.

## ۱) گام صفر — احصای مشخصات سرور

قبل از هر نصبی، اسکریپت `server-inventory.ps1` را روی سرور اجرا کنید تا وضعیت پورت‌های باز، برنامه‌های نصب‌شده و پیش‌نیازها (مجازی‌سازی، WSL، دیسک، فایروال) مشخص شود:

```powershell
# در PowerShell با دسترسی Administrator
cd C:\path\to\server-inventory.ps1
powershell -ExecutionPolicy Bypass -File .\server-inventory.ps1
```

خروجی دو فایل است (`RoseServerReport_*.txt` و `*.json` روی دسکتاپ) که باید کامل برای کارشناس استقرار ارسال شود. موارد کلیدی که در گزارش بررسی می‌شود:

- `port 80 / 443 / 8080` آزاد باشند (اگر ۸۰۸۰ اشغال است، در `compose.http.yml` پورت دیگری بگذارید)
- `VT-x in firmware: YES` و `HypervisorPresent` (برای WSL2 حیاتی است)
- وضعیت WSL و Docker (نصب است یا نه)
- `IIS` یا SQL Server در حال اجرا (تداخل پورت ۸۰)
- رم ≥ ۸ گیگابایت و فضای خالی دیسک C ≥ ۳۰ گیگابایت

## ۲) مسیر الف (پیشنهادی) — نصب WSL2 و Docker Engine

### ۲-۱) فعال‌سازی ویژگی‌های ویندوز

```powershell
# PowerShell با دسترسی Administrator
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Restart-Computer
```

> اگر در گزارش بخش [E] مقدار `VT-x in firmware: NO` بود، ابتدا از تنظیمات BIOS/UEFI سرور قابلیت مجازی‌سازی (Intel VT-x / AMD-V) را فعال کنید. اگر سرور خودش یک ماشین مجازی است، Nested Virtualization باید روی هایپروایزر فعال شود.

### ۲-۲) نصب خود WSL

```powershell
# اگر سرور به اینترنت و Microsoft Store دسترسی دارد:
wsl --install -d Ubuntu-24.04 --no-launch
wsl --set-default-version 2

# اگر Store در دسترس نیست (نصب آفلاین از GitHub):
# ۱) فایل msi آخرین نسخه را از https://github.com/microsoft/WSL/releases بگیرید
# ۲) msiexec /i wsl.x.x.x.x64.msi /qn
# ۳) wsl --install -d Ubuntu-24.04
```

پس از راه‌اندازی اولیه اوبونتو، یوزرنیم و رمز لینوکسی بسازید و مطمئن شوید `wsl -l -v` نسخهٔ `2` را نشان می‌دهد.

### ۲-۳) شبکهٔ WSL — حالت Mirrored (مهم!)

WSL2 به‌صورت پیش‌فرض زیر NAT است و پورت‌های داخل اوبونتو از بیرون دیده نمی‌شوند. روی Server 2025 (بیلد ۲۶۱۰۰) حالت **mirrored** پشتیبانی می‌شود که این مشکل را کامل حل می‌کند. فایل `C:\Users\<YourUser>\.wslconfig` را بسازید:

```ini
[wsl2]
networkingMode=mirrored

[experimental]
hostAddressLoopback=true
```

سپس در PowerShell: `wsl --shutdown` و دوباره وارد اوبونتو شوید. از این پس هر پورتی که داخل اوبونتو publish شود، مستقیماً روی IPهای خود سرور ویندوزی (از جمله `130.185.73.157`) هم گوش می‌دهد.

> **اگر mirrored در محیط شما کار نکرد** (برخی شبکه‌های مجازی/فایروال‌های سخت‌افزاری)، راه جایگزین portproxy در بخش ۷ آمده است.

### ۲-۴) نصب Docker Engine داخل اوبونتو

```bash
# داخل اوبونتو (WSL)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# خارج و دوباره وارد WSL شوید تا گروه docker اعمال شود
docker --version && docker compose version
```

### ۲-۵) دریافت پروژه و اجرا

```bash
# داخل اوبونتو (WSL) — پروژه را در فایل‌سیستم لینوکسی نگه دارید (نه /mnt/c) برای سرعت IO
git clone https://github.com/sjalilvand/rose-attendance.git ~/rose-attendance
cd ~/rose-attendance
cp .env.example .env
bash deploy/update-wsl.sh
```

اسکریپت `update-wsl.sh` خودش این کارها را می‌کند: `git pull` → ساخت `secrets/` تصادفی → اصلاح `.env` برای IP `130.185.73.157` و پورت ۸۰۸۰ → `docker compose -f compose.http.yml build` → `up -d` → `migrate`.

## ۳) محتوای `.env` صحیح برای این استقرار

```ini
APP_VERSION=1.0.0

DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=130.185.73.157,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://130.185.73.157:8080,http://localhost

DB_NAME=rose_attendance
DB_USER=rose_app

BUSINESS_TIME_ZONE=Asia/Tehran
```

> اگر پورت ۸۰ در گزارش آزاد بود و ترجیح می‌دهید بدون :8080 کار کنید، در `compose.http.yml` خط `8080:80` را به `80:80` تغییر دهید و `DJANGO_CSRF_TRUSTED_ORIGINS` را به `http://130.185.73.157` تغییر بدهید (بدون پورت). در این حالت به‌جای `compose.http.yml` می‌توانید از `compose.yml` اصلی هم استفاده کنید (entrypoint گیت‌وی بدون گواهی، خودش HTTP می‌شود) اما پورت ۴۴۳ بی‌استفاده publish خواهد شد.

## ۴) فایروال ویندوز

```powershell
# PowerShell با دسترسی Administrator
New-NetFirewallRule -DisplayName "Rose Attendance HTTP 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Any
```

اگر سرور پشت روتر/فایروال سازمانی است، DNAT پورت ۸۰۸۰ را به این سرور تنظیم کنید. پورت‌های PostgreSQL/Redis به‌هیچ‌وجه از داکر بیرون داده نمی‌شوند (فقط شبکهٔ داخلی compose) — نیازی به باز کردن آن‌ها نیست.

## ۵) مسیر ب — Docker Desktop (اگر ترجیح دادید)

1. Docker Desktop را نصب و در تنظیمات آن **Use WSL 2 based engine** را فعال کنید.
2. مخزن را با `git clone https://github.com/sjalilvand/rose-attendance.git C:\rose-attendance` بگیرید و `cd C:\rose-attendance`.
3. اجرا: `.\update-http.ps1` (همان فلوی secrets و .env و migrate را با `compose.http.yml` انجام می‌دهد).
4. قانون فایروال بخش ۴ را حتماً اجرا کنید.
> توجه مجوز: برای سازمان بیش از ۲۵۰ نفر یا درآمد بیش از ۱۰ میلیون دلار، Docker Desktop اشتراک تجاری می‌خواهد.

## ۶) ساخت کاربر مدیر و تست سلامت

```bash
# داخل WSL (مسیر الف) — در مسیر ب معادل PowerShell همان دستور compose است
DJANGO_SUPERUSER_PASSWORD="رمز-دلخواه-قوی" docker compose -f compose.http.yml run --rm migrate python manage.py createsuperuser --noinput --username admin
```

تست‌ها:

| بررسی | دستور/آدرس | نتیجهٔ مورد انتظار |
|---|---|---|
| سلامت API | `curl http://130.185.73.157:8080/api/v1/health/` (از بیرون سرور) | پاسخ JSON سالم |
| PWA | باز کردن `http://130.185.73.157:8080/` در مرورگر | صفحهٔ ورود |
| WebSocket | باز کردن PWA → تب اعلان‌ها | toast اعلان زنده |
| کانتینرها | `docker compose -f compose.http.yml ps` | همه `healthy/running` |

> **نکتهٔ مهم در حالت HTTP:** PWA پرسنل (احراز هویت JWT) و API و WebSocket کامل کار می‌کنند، اما **پنل ادمین جنگو** (`/admin`) به‌خاطر کوکی‌های `Secure` در تنظیمات production، روی HTTP لاگین نمی‌شود. این محدودیت فقط تا دریافت SSL است؛ پس از مهاجرت به HTTPS خودبه‌خود رفع می‌شود. اگر قبل از SSL به پنل ادمین نیاز فوری داشتید، به کارشناس استقرار اطلاع دهید تا یک لایهٔ تنظیمات موقت اضافه شود.

## ۷) عیب‌یابی رایج

- **پورت ۸۰۸۰ اشغال است** → در گزارش بخش [I] مالکش را ببینید؛ پورت را در `compose.http.yml` عوض کنید و `DJANGO_CSRF_TRUSTED_ORIGINS` را همگام کنید.
- **از بیرون باز نمی‌شود ولی روی خود سرور `curl localhost:8080` جواب می‌دهد** → حالت mirrored فعال نیست؛ بخش ۲-۳ را دوباره انجام دهید یا portproxy بگیرید:
  ```powershell
  # IP اوبونتوی WSL را بگیرید
  wsl hostname -I
  # (IP را جایگزین کنید) — توجه: بعد از هر ریبوت باید تکرار شود
  netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8080 connectaddress=<WSL_IP> connectport=8080
  New-NetFirewallRule -DisplayName "Rose portproxy 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
  ```
- **خطای `APP_VERSION is required`** → فایل `.env` کنار فایل‌های compose نیست یا `APP_VERSION` ندارد.
- **سلامت api همیشه unhealthy** → `docker compose -f compose.http.yml logs api` را ببینید؛ معمولاً `.env` ناقص (ALLOWED_HOSTS) یا آماده‌نشدن Redis است.
- **پس از تغییر `.env`** → حتماً `docker compose -f compose.http.yml up -d --force-recreate` بزنید.

## ۸) مهاجرت به SSL معتبر (پس از پایان توسعه)

1. دامنهٔ رسمی را به IP سرور متصل کنید (A record) و مقدار `server_name` را در کانفیگ گیت‌وی روی همان دامنه بگذارید.
2. گواهی (مثلاً Let's Encrypt یا گواهی سازمانی) را تهیه و دو فایل `fullchain.pem` و `privkey.pem` را در `deploy/tls/` بگذارید.
3. `.env` را به‌روز کنید: `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain` و در صورت نیاز ALLOWED_HOSTS به دامنه.
4. به `compose.yml` اصلی برگردید (`docker compose up -d` — گیت‌وی با وجود گواهی، خودش HTTPS را فعال می‌کند و پورت ۸۰ را به ۴۴۳ ریدایرکت می‌کند) و قانون فایروال ۴۴۳ را باز کنید.
5. کش HSTS و Service Worker مرورگرها را در تست در نظر بگیرید (یک بار hard refresh).

## ۹) نکات امنیتی و بهره‌برداری

- `secrets/`، `.env` و `deploy/tls/` هرگز commit/push نشوند (در `.gitignore` هستند).
- توکن‌های GitHub را پس از اتمام کار باطل/چرخش کنید؛ توکن در دستورات روی سرور ذخیره نشود (مخزن عمومی است و clone بدون توکن انجام می‌شود).
- بکاپ منظم: `docker run --rm -v rose-attendance_pgdata:/data -v C:\backups:/backup alpine tar czf /backup/pgdata-$(date +%F).tgz -C /data .`
- برای مشاهدهٔ لاگ‌ها: `docker compose -f compose.http.yml logs -f --tail=100 api`

</div>

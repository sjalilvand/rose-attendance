#Requires -Version 5.1
<#
.SYNOPSIS
  راه‌اندازی اپلیکیشن «رز سفید» بدون Docker: دیتابیس، وابستگی‌های بک‌اند،
  build فرانت‌اند، مهاجرت‌ها و فایل‌های env (نسخه ۲).

.CHANGES v2
  - پورت‌های جدید: وب 8085، بک‌اند 3005
  - تنظیمات windows_http: پنل ادمین جنگو روی HTTP هم کار می‌کند (تا رسیدن SSL)
  - ساخت افزونه PostGIS اختیاری شد (شکستش نصب را متوقف نمی‌کند)
  - کشف مسیر psql/python از C:\rose-stack\stack-env.ps1

.DESCRIPTION
  پیش‌نیاز: install-rose-prereq.ps1 اجرا شده باشد و مخزن در C:\rose-attendance باشد.
  این اسکریپت:
    ۱) secrets تصادفی می‌سازد (django_secret / db_password)
    ۲) در PostgreSQL دیتابیس rose_attendance و کاربر rose_app می‌سازد (+PostGIS در صورت وجود)
    ۳) venv پایتون می‌سازد و requirements.lock (+ daphne برای WebSocket) را نصب می‌کند
    ۴) فایل env یکپارچه C:\rose-stack\rose-backend.env را تولید می‌کند
    ۵) migrate و collectstatic اجرا می‌کند
    ۶) فرانت‌اند را با npm ci + npm run build می‌سازد
    ۷) (اختیاری) کاربر admin می‌سازد

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز-قوی"
#>

[CmdletBinding()]
param(
  [string]$PostgresPassword = "",
  [string]$AdminPassword = "",
  [switch]$SkipFrontend,
  [string]$RepoRoot = ""
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ProgressPreference = 'SilentlyContinue'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = $PSScriptRoot }
$stack = 'C:\rose-stack'
$backend = Join-Path $RepoRoot 'backend'
$frontend = Join-Path $RepoRoot 'frontend'
$RoseWebPort = 8085
$RoseApiPort = 3005

Write-Host ''
Write-Host '== راه‌اندازی اپلیکیشن رز سفید (بدون Docker) — نسخه ۲ ==' -ForegroundColor Cyan
Write-Host ("   مخزن   : " + $RepoRoot)
Write-Host ("   پورت‌ها : وب $RoseWebPort / بک‌اند $RoseApiPort")

# ------------------------------------------------- ۰) پیش‌نیازها -------------
if (-not (Test-Path $backend) -or -not (Test-Path $frontend)) {
  Write-Error "این اسکریپت باید داخل ریشه مخزن (C:\rose-attendance) اجرا شود. مسیر فعلی: $RepoRoot"
  exit 1
}

# stack-env از اسکریپت پیش‌نیاز (اگر باشد)
$RosePsqlFromStack = $null
$RosePythonFromStack = $null
if (Test-Path "$stack\stack-env.ps1") {
  . "$stack\stack-env.ps1"
  $RosePsqlFromStack = $RosePsql
  $RosePythonFromStack = $RosePython
}

$psql = @("$RosePsqlFromStack",
          'C:\Program Files\PostgreSQL\16\bin\psql.exe') |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $psql) {
  try {
    $reg = Get-ItemProperty 'HKLM:\SOFTWARE\PostgreSQL\Installations\postgresql-x64-16' -ErrorAction SilentlyContinue
    if ($reg -and $reg.'Base Directory') {
      $cand = Join-Path $reg.'Base Directory' 'bin\psql.exe'
      if (Test-Path $cand) { $psql = $cand }
    }
  } catch { }
}
if (-not $psql) {
  $svc = Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($svc -and $svc.PathName) {
    $exe = $null
    if ($svc.PathName -match '^"([^"]+)"') { $exe = $Matches[1] } else { $exe = ($svc.PathName -split ' ')[0] }
    $candidate = Join-Path (Split-Path (Split-Path $exe -Parent) -Parent) 'bin\psql.exe'
    if (Test-Path $candidate) { $psql = $candidate }
  }
}
if (-not $psql) { Write-Error 'psql یافت نشد — ابتدا install-rose-prereq.ps1 را اجرا کنید.'; exit 1 }
Write-Host ("   psql   : " + $psql)

# ------------------------------------------------- ۱) secrets ----------------
Write-Host '-- ۱/۷ آماده‌سازی secrets --' -ForegroundColor Yellow
$secretsDir = Join-Path $RepoRoot 'secrets'
New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null
foreach ($name in @('django_secret', 'db_password')) {
  $file = Join-Path $secretsDir ($name + '.txt')
  if (-not (Test-Path $file)) {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    [System.IO.File]::WriteAllText($file, (-join ($bytes | ForEach-Object { $_.ToString('x2') })))
    Write-Host ("   ساخته شد: secrets\" + $name + ".txt")
  }
}
$dbPassword = (Get-Content (Join-Path $secretsDir 'db_password.txt') -Raw).Trim()

# ------------------------------------------------- ۲) دیتابیس ----------------
Write-Host '-- ۲/۷ ساخت دیتابیس و کاربر در PostgreSQL --' -ForegroundColor Yellow
$pgPwFile = "$stack\secrets\pg_postgres_password.txt"
$pgPwSource = 'param (-PostgresPassword)'
if ([string]::IsNullOrWhiteSpace($PostgresPassword)) {
  if (Test-Path $pgPwFile) {
    $PostgresPassword = (Get-Content $pgPwFile -Raw).Trim()
    $pgPwSource = 'file: ' + $pgPwFile
  }
}
if ([string]::IsNullOrWhiteSpace($PostgresPassword)) {
  $pgPwSource = 'manual input'

  $sec = Read-Host 'رمز کاربر postgres را وارد کنید' -AsSecureString
  $PostgresPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
$env:PGPASSWORD = $PostgresPassword
Write-Host ("   منبع رمز postgres: " + $pgPwSource)
if ($pgPwSource -notlike 'file:*') {
  try { [System.IO.File]::WriteAllText($pgPwFile, $PostgresPassword) } catch { }
}

function Invoke-Psql([string]$sql) {
  & $psql -h 127.0.0.1 -p 5432 -U postgres -v ON_ERROR_STOP=1 -c $sql
  if ($LASTEXITCODE -ne 0) { throw "psql ناموفق: $sql" }
}

# تست اتصال
& $psql -h 127.0.0.1 -p 5432 -U postgres -c "SELECT version();" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Warning 'اتصال به PostgreSQL با کاربر postgres ناموفق بود.'
  Write-Host ''
  Write-Host '   علت رایج: رمز ذخیره‌شده در C:\rose-stack\secrets\pg_postgres_password.txt (از اجرای قبلی) با رمز واقعی این نمونه PostgreSQL (rosepsy) نمی‌خواند.' -ForegroundColor Yellow
  Write-Host '   راه A) اگر رمز postgres را می‌دانید (رمزی که هنگام نصب PostgreSQL تعیین کرده‌اید):' -ForegroundColor Cyan
  Write-Host '      powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -PostgresPassword "رمز-واقعی-postgres" -AdminPassword "رمز-ادمین"'
  Write-Host '   راه B) اگر رمز را نمی‌دانید — با اسکریپت زیر ریست کنید (سرویس PostgreSQL چند ثانیه ری‌استارت می‌شود):' -ForegroundColor Cyan
  Write-Host '      powershell -ExecutionPolicy Bypass -File .\reset-postgres-password.ps1 -NewPassword "رمز-جدید-قوی"'
  Write-Host '   سپس دوباره همین اسکریپت را اجرا کنید.' -ForegroundColor Cyan
  exit 1
}
Write-Host '   اتصال PostgreSQL برقرار است.'

# کاربر rose_app (SUPERUSER تا مهاجرت‌ها و افزونه‌ها بدون مشکل ساخته شوند)
# بررسی نسخه سرور PostgreSQL (Django 6.1 به PostgreSQL 14+ نیاز دارد)
try {
  $pgVerRaw = (& $psql -tA -h 127.0.0.1 -p 5432 -U postgres -c "SHOW server_version_num;") 2>$null
  $pgMajor = [math]::Floor([int]("$pgVerRaw".Trim()) / 10000)
  if ($pgMajor -ge 14) {
    Write-Host ("   نسخه PostgreSQL سرور: " + $pgMajor)
  } else {
    Write-Warning ("نسخه PostgreSQL سرور " + $pgMajor + " است؛ Django 6.1 به PostgreSQL 14+ نیاز دارد و ممکن است مهاجرت‌ها شکست بخورند.")
  }
} catch { }

$roleExists = & $psql -tA -h 127.0.0.1 -p 5432 -U postgres -c "SELECT 1 FROM pg_roles WHERE rolname='rose_app';"
if ("$roleExists".Trim() -ne '1') {
  Invoke-Psql "CREATE ROLE rose_app LOGIN SUPERUSER PASSWORD '$dbPassword';"
  Write-Host '   کاربر rose_app ساخته شد.'
} else {
  Invoke-Psql "ALTER ROLE rose_app WITH LOGIN SUPERUSER PASSWORD '$dbPassword';"
  Write-Host '   کاربر rose_app موجود است (رمز همگام شد).'
}

# دیتابیس rose_attendance
$dbExists = & $psql -tA -h 127.0.0.1 -p 5432 -U postgres -c "SELECT 1 FROM pg_database WHERE datname='rose_attendance';"
if ("$dbExists".Trim() -ne '1') {
  Invoke-Psql "CREATE DATABASE rose_attendance OWNER rose_app;"
  Write-Host '   دیتابیس rose_attendance ساخته شد.'
} else {
  Write-Host '   دیتابیس rose_attendance موجود است.'
}

# افزونه PostGIS — اختیاری (برنامه بدون آن هم کار می‌کند)
try {
  Invoke-Psql "CREATE EXTENSION IF NOT EXISTS postgis;"
  Write-Host '   افزونه PostGIS فعال است.'
} catch {
  Write-Warning 'افزونه PostGIS فعال نشد — اشکالی ندارد، برنامه بدون آن کار می‌کند.'
}

# ------------------------------------------------- ۳) فایل env ---------------
Write-Host '-- ۳/۷ تولید فایل env یکپارچه --' -ForegroundColor Yellow
$envMap = [ordered]@{
  'DJANGO_SETTINGS_MODULE'      = 'config.settings.windows_http'
  'DJANGO_SECRET_KEY_FILE'      = (Join-Path $secretsDir 'django_secret.txt')
  'DB_PASSWORD_FILE'            = (Join-Path $secretsDir 'db_password.txt')
  'DB_HOST'                     = '127.0.0.1'
  'DB_PORT'                     = '5432'
  'DB_NAME'                     = 'rose_attendance'
  'DB_USER'                     = 'rose_app'
  'REDIS_URL'                   = 'redis://127.0.0.1:6379/0'
  'CHANNEL_REDIS_URL'           = 'redis://127.0.0.1:6379/1'
  'DJANGO_ALLOWED_HOSTS'        = '130.185.73.157,localhost,127.0.0.1'
  'DJANGO_CSRF_TRUSTED_ORIGINS' = "http://130.185.73.157:$RoseWebPort,http://localhost:$RoseWebPort"
  'DJANGO_DEBUG'                = 'False'
}
$envPath = "$stack\rose-backend.env"
$lines = foreach ($k in $envMap.Keys) { "$k=$($envMap[$k])" }
[System.IO.File]::WriteAllLines($envPath, $lines)
$cmdLines = foreach ($k in $envMap.Keys) { 'set "' + $k + '=' + $envMap[$k] + '"' }
[System.IO.File]::WriteAllLines("$stack\rose-backend-env.cmd", $cmdLines)
Write-Host ("   نوشته شد: " + $envPath)

# بارگذاری env در این نشست
foreach ($k in $envMap.Keys) { Set-Item -Path ("env:" + $k) -Value $envMap[$k] }

# ------------------------------------------------- ۴) venv و وابستگی‌ها ------
Write-Host '-- ۴/۷ ساخت venv و نصب وابستگی‌های بک‌اند (چند دقیقه) --' -ForegroundColor Yellow
$venvPy = "$stack\venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  $py = $RosePythonFromStack
  if (-not $py -or -not (Test-Path $py)) {
    foreach ($c in @('python', 'py')) {
      $cmd = Get-Command $c -ErrorAction SilentlyContinue
      if ($cmd) {
        $v = (& $cmd.Source --version 2>&1) | Out-String
        if ($v -match 'Python\s+3\.(12|13)') { $py = $cmd.Source; break }
      }
    }
  }
  if (-not $py) { Write-Error 'Python 3.12/3.13 یافت نشد — ابتدا install-rose-prereq.ps1 را اجرا کنید.'; exit 1 }
  & $py -m venv "$stack\venv"
}
& $venvPy -m pip install --upgrade pip --quiet
$lock = Join-Path $backend 'requirements.lock'
if (Test-Path $lock) {
  Write-Host '   نصب از requirements.lock (hashed) ...'
  & $venvPy -m pip install --require-hashes -r $lock
  if ($LASTEXITCODE -ne 0) {
    Write-Warning 'نصب از lock ناموفق بود؛ تلاش با requirements.in ...'
    & $venvPy -m pip install -r (Join-Path $backend 'requirements.in')
    if ($LASTEXITCODE -ne 0) { Write-Error 'نصب وابستگی‌های پایتون ناموفق بود.'; exit 1 }
  }
} else {
  & $venvPy -m pip install -r (Join-Path $backend 'requirements.in')
}
# سرور ASGI با پشتیبانی WebSocket (daphne مرجع Channels است)
& $venvPy -m pip show daphne --quiet
if ($LASTEXITCODE -ne 0) {
  Write-Host '   نصب daphne (سرور ASGI/WebSocket) ...'
  & $venvPy -m pip install daphne
}
Write-Host '   وابستگی‌های بک‌اند نصب شد.' -ForegroundColor Green

# ------------------------------------------------- ۵) migrate + static -------
Write-Host '-- ۵/۷ مهاجرت دیتابیس و جمع‌آوری فایل‌های static --' -ForegroundColor Yellow
Push-Location $backend
& $venvPy manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error 'migrate ناموفق بود (اتصال دیتابیس را بررسی کنید).'; exit 1 }
& $venvPy manage.py collectstatic --noinput
if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error 'collectstatic ناموفق بود.'; exit 1 }
Pop-Location
Write-Host '   مهاجرت‌ها و static کامل شد.' -ForegroundColor Green

# ------------------------------------------------- ۶) فرانت‌اند --------------
if (-not $SkipFrontend) {
  Write-Host '-- ۶/۷ ساخت فرانت‌اند (npm ci + build؛ چند دقیقه) --' -ForegroundColor Yellow
  $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
  if ($npmCmd) {
    Push-Location $frontend
    & npm ci
    if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error 'npm ci ناموفق بود.'; exit 1 }
    & npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error 'npm run build ناموفق بود.'; exit 1 }
    Pop-Location
    Write-Host '   فرانت‌اند ساخته شد: frontend\dist' -ForegroundColor Green
  } else {
    Write-Warning 'npm یافت نشد — Node.js را نصب و دوباره اجرا کنید (یا با -SkipFrontend رد شوید).'
  }
} else {
  Write-Host '-- ۶/۷ فرانت‌اند رد شد (-SkipFrontend) --' -ForegroundColor Yellow
}

# ------------------------------------------------- ۷) کاربر admin ------------
Write-Host '-- ۷/۷ کاربر مدیر (اختیاری) --' -ForegroundColor Yellow
if (-not [string]::IsNullOrWhiteSpace($AdminPassword)) {
  $env:DJANGO_SUPERUSER_PASSWORD = $AdminPassword
  Push-Location $backend
  & $venvPy manage.py createsuperuser --noinput --username admin
  Pop-Location
  Remove-Item Env:\DJANGO_SUPERUSER_PASSWORD -ErrorAction SilentlyContinue
  Write-Host '   کاربر admin ساخته شد (نام کاربری: admin).'
} else {
  Write-Host '   رد شد — بعداً اجرا کنید:'
  Write-Host '   $env:DJANGO_SUPERUSER_PASSWORD="رمز-دلخواه"; cd C:\rose-attendance\backend; C:\rose-stack\venv\Scripts\python.exe manage.py createsuperuser --noinput --username admin'
}

# ------------------------------------------------- پایان ---------------------
Write-Host ''
Write-Host 'راه‌اندازی اپلیکیشن کامل شد ✓' -ForegroundColor Green
Write-Host ''
Write-Host 'گام بعدی — اجرای همه سرویس‌ها:' -ForegroundColor Cyan
Write-Host '  powershell -ExecutionPolicy Bypass -File .\run-rose.ps1 -InstallServices'
Write-Host "سپس مرورگر:  http://130.185.73.157:$RoseWebPort/"
Write-Host "پنل ادمین :  http://130.185.73.157:$RoseWebPort/admin/"
Write-Host "سلامت API :  http://130.185.73.157:$RoseWebPort/api/v1/health/"

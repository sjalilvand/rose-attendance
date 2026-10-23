#Requires -Version 5.1
<#
.SYNOPSIS
  بروزرسانی سامانه حضور و غیاب «رز سفید» از گیت‌هاب روی سیستم شما.

.DESCRIPTION
  فلوی استاندارد: git pull → آماده‌سازی secrets و .env → build تصاویر → اجرای سرویس‌ها → مهاجرت دیتابیس.
  نیازمندی‌ها: Git، Docker Desktop (برای حالت داکر) و فایل .env آماده (از .env.example).

.EXAMPLE
  .\update.ps1
  .\update.ps1 -SkipDocker     # فقط pull + راهنمای دستی
  .\update.ps1 -SkipPull       # فقط بازسازی سرویس‌ها بدون pull
#>
param(
  [switch]$SkipPull,
  [switch]$SkipDocker
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Host ''
Write-Host '== بروزرسانی سامانه حضور و غیاب رز سفید ==' -ForegroundColor Cyan
Write-Host ''

# --- ۱) دریافت آخرین تغییرات از گیت‌هاب -------------------------------------
if (-not $SkipPull) {
  Write-Host '-- ۱/۴ دریافت تغییرات از origin/main --' -ForegroundColor Yellow
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) {
    throw 'git pull ناموفق بود؛ تغییرات محلی را commit یا stash کنید (git stash) و دوباره اجرا کنید.'
  }
  Write-Host ''
}

# --- ۲) آماده‌سازی secrets و .env -------------------------------------------
Write-Host '-- ۲/۴ آماده‌سازی secrets و .env --' -ForegroundColor Yellow

$secretsDir = Join-Path $PSScriptRoot 'secrets'
New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null
foreach ($name in @('django_secret', 'db_password')) {
  $file = Join-Path $secretsDir ($name + '.txt')
  if (-not (Test-Path $file)) {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    [System.IO.File]::WriteAllText($file, $secret)
    Write-Host ('  ساخته شد: secrets\' + $name + '.txt (مقدار تصادفی)')
  }
}

$envFile = Join-Path $PSScriptRoot '.env'
if (Test-Path $envFile) {
  $lines = @(Get-Content $envFile)
  $idx = $null
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -like 'DJANGO_ALLOWED_HOSTS=*') { $idx = $i; break }
  }
  if ($null -ne $idx) {
    $value = $lines[$idx].Substring('DJANGO_ALLOWED_HOSTS='.Length)
    $list = @($value.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($list -notcontains 'localhost') {
      $newList = @($list) + 'localhost'
      $lines[$idx] = ('DJANGO_ALLOWED_HOSTS=' + ($newList -join ','))
      [System.IO.File]::WriteAllLines($envFile, $lines)
      Write-Host '  .env: localhost به DJANGO_ALLOWED_HOSTS اضافه شد.'
    }
  }
}
else {
  Write-Warning '.env یافت نشد؛ ابتدا اجرا کنید: copy .env.example .env'
}

Write-Host ''

# --- ۳) اجرای سرویس‌ها -------------------------------------------------------
if ($SkipDocker) {
  Write-Host 'حالت بدون داکر فعال است؛ دستورات زیر را دستی اجرا کنید:' -ForegroundColor Yellow
  Write-Host '  بک‌اند  : pip install -r backend\requirements.lock ; python backend\manage.py migrate'
  Write-Host '  فرانت‌اند: npm ci ; npm run build   (داخل پوشه frontend)'
  return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker یافت نشد. Docker Desktop را نصب/اجر کنید یا با -SkipDocker اجرا کنید.'
}

Write-Host '-- ۳/۴ ساخت و اجرای سرویس‌ها (db, redis, api, worker, scheduler, gateway) --' -ForegroundColor Yellow
docker compose build
if ($LASTEXITCODE -ne 0) { throw 'docker compose build ناموفق بود.' }
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up ناموفق بود.' }

Write-Host ''
Write-Host '-- ۴/۴ مهاجرت دیتابیس --' -ForegroundColor Yellow
docker compose run --rm migrate
if ($LASTEXITCODE -ne 0) { throw 'مهاجرت ناموفق بود؛ لاگ سرویس migrate را بررسی کنید.' }

Write-Host ''
Write-Host 'بروزرسانی کامل شد ✓' -ForegroundColor Green
Write-Host 'سلامت سرویس‌ها : http://localhost/api/v1/health/'
Write-Host 'وب‌اپ (PWA)   : http://localhost/'
Write-Host ''
Write-Host 'ساخت کاربر مدیر اولیه (اختیاری):' 
Write-Host '  $env:DJANGO_SUPERUSER_PASSWORD="رمز-دلخواه"; docker compose run --rm migrate python manage.py createsuperuser --noinput --username admin --email admin@example.com'
Write-Host ''
Write-Host 'نکته: پس از بروزرسانی فرانت‌اند، در مرورگر یک بار بارگذاری مجدد کنید تا Service Worker جدید فعال شود.'

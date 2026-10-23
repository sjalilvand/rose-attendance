#Requires -Version 5.1
<#
.SYNOPSIS
  بروزرسانی سامانه حضور و غیاب «رز سفید» از گیت‌هاب روی سیستم شما.

.DESCRIPTION
  فلوی استاندارد: git pull → build تصاویر → اجرای سرویس‌ها → مهاجرت دیتابیس.
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
  Write-Host '-- ۱/۳ دریافت تغییرات از origin/main --' -ForegroundColor Yellow
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) {
    throw 'git pull ناموفق بود؛ تغییرات محلی را commit یا stash کنید (git stash) و دوباره اجرا کنید.'
  }
  Write-Host ''
}

# --- ۲) اجرای سرویس‌ها -------------------------------------------------------
if ($SkipDocker) {
  Write-Host 'حالت بدون داکر فعال است؛ دستورات زیر را دستی اجرا کنید:' -ForegroundColor Yellow
  Write-Host '  بک‌اند  : pip install -r backend\requirements.lock ; python backend\manage.py migrate'
  Write-Host '  فرانت‌اند: npm ci ; npm run build   (داخل پوشه frontend)'
  return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker یافت نشد. Docker Desktop را نصب/اجر کنید یا با -SkipDocker اجرا کنید.'
}

Write-Host '-- ۲/۳ ساخت و اجرای سرویس‌ها (db, redis, api, worker, scheduler, gateway) --' -ForegroundColor Yellow
docker compose build
if ($LASTEXITCODE -ne 0) { throw 'docker compose build ناموفق بود.' }
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up ناموفق بود.' }

Write-Host ''
Write-Host '-- ۳/۳ مهاجرت دیتابیس --' -ForegroundColor Yellow
docker compose run --rm migrate
if ($LASTEXITCODE -ne 0) { throw 'مهاجرت ناموفق بود؛ لاگ سرویس migrate را بررسی کنید.' }

Write-Host ''
Write-Host 'بروزرسانی کامل شد ✓' -ForegroundColor Green
Write-Host 'سلامت سرویس‌ها : http://localhost/api/v1/health/'
Write-Host 'وب‌اپ (PWA)   : http://localhost/'
Write-Host ''
Write-Host 'نکته: پس از بروزرسانی فرانت‌اند، در مرورگر یک بار بارگذاری مجدد کنید تا Service Worker جدید فعال شود.'

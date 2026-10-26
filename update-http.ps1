#Requires -Version 5.1
<#
.SYNOPSIS
  بروزرسانی و اجرای سامانه حضور و غیاب «رز سفید» در حالت HTTP (بدون SSL) روی ویندوز.

.DESCRIPTION
  فلوی استاندارد حالت HTTP: git pull → آماده‌سازی secrets و .env → build → up -d → migrate
  بر اساس compose.http.yml (پورت پیش‌فرض 8080، بدون 443 و بدون گواهی TLS).
  نیازمندی‌ها: Git و Docker Desktop (یا هر Docker سازگار روی ویندوز).

.EXAMPLE
  .\update-http.ps1
  .\update-http.ps1 -SkipPull     # فقط بازسازی سرویس‌ها بدون pull
#>

param(
  [switch]$SkipPull
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Host ''
Write-Host '== بروزرسانی سامانه رز سفید — حالت HTTP روی پورت 8080 ==' -ForegroundColor Cyan
Write-Host ''

# --- ۱) دریافت آخرین تغییرات از گیت‌هاب --------------------------------------
if (-not $SkipPull) {
  Write-Host '-- ۱/۴ دریافت تغییرات از origin/main --' -ForegroundColor Yellow
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) {
    throw 'git pull ناموفق بود؛ تغییرات محلی را commit یا stash کنید و دوباره اجرا کنید.'
  }
  Write-Host ''
}

# --- ۲) آماده‌سازی secrets و .env --------------------------------------------
Write-Host '-- ۲/۴ آماده‌سازی secrets و .env --' -ForegroundColor Yellow

$secretsDir = Join-Path $PSScriptRoot 'secrets'
New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'deploy\tls') | Out-Null

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
if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $PSScriptRoot '.env.example') $envFile
  Write-Host '  .env از روی .env.example ساخته شد.' -ForegroundColor Yellow
}

# تضمین مقادیر لازم برای IP سرور و پورت 8080
$lines = @(Get-Content $envFile)

# ۲/الف) DJANGO_ALLOWED_HOSTS باید شامل 130.185.73.157 باشد
$idx = $null
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -like 'DJANGO_ALLOWED_HOSTS=*') { $idx = $i; break }
}
if ($null -eq $idx) {
  $lines += 'DJANGO_ALLOWED_HOSTS=130.185.73.157,localhost,127.0.0.1'
  Write-Host '  .env: DJANGO_ALLOWED_HOSTS اضافه شد.'
} else {
  $value = $lines[$idx].Substring('DJANGO_ALLOWED_HOSTS='.Length)
  $list = @($value.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  $changed = $false
  foreach ($h in @('130.185.73.157', 'localhost', '127.0.0.1')) {
    if ($list -notcontains $h) { $list = @($list) + $h; $changed = $true }
  }
  if ($changed) {
    $lines[$idx] = ('DJANGO_ALLOWED_HOSTS=' + ($list -join ','))
    Write-Host '  .env: 130.185.73.157/localhost به DJANGO_ALLOWED_HOSTS اضافه شد.'
  }
}

# ۲/ب) DJANGO_CSRF_TRUSTED_ORIGINS باید http://130.185.73.157:8080 را داشته باشد
$idx = $null
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -like 'DJANGO_CSRF_TRUSTED_ORIGINS=*') { $idx = $i; break }
}
if ($null -eq $idx) {
  $lines += 'DJANGO_CSRF_TRUSTED_ORIGINS=http://130.185.73.157:8080,http://localhost'
  Write-Host '  .env: DJANGO_CSRF_TRUSTED_ORIGINS اضافه شد.'
} else {
  $value = $lines[$idx].Substring('DJANGO_CSRF_TRUSTED_ORIGINS='.Length)
  $list = @($value.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  $changed = $false
  foreach ($o in @('http://130.185.73.157:8080', 'http://localhost')) {
    if ($list -notcontains $o) { $list = @($list) + $o; $changed = $true }
  }
  if ($changed) {
    $lines[$idx] = ('DJANGO_CSRF_TRUSTED_ORIGINS=' + ($list -join ','))
    Write-Host '  .env: origin های لازم به DJANGO_CSRF_TRUSTED_ORIGINS اضافه شد.'
  }
}

[System.IO.File]::WriteAllLines($envFile, $lines)
Write-Host ''

# --- ۳) ساخت و اجرای سرویس‌ها -------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker یافت نشد. ابتدا Docker (یا WSL2 + Docker Engine) را نصب و اجرا کنید.'
}

Write-Host '-- ۳/۴ ساخت و اجرای سرویس‌ها (compose.http.yml) --' -ForegroundColor Yellow
docker compose -f compose.http.yml build
if ($LASTEXITCODE -ne 0) { throw 'docker compose build ناموفق بود.' }
docker compose -f compose.http.yml up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up ناموفق بود.' }

Write-Host ''
Write-Host '-- ۴/۴ مهاجرت دیتابیس --' -ForegroundColor Yellow
docker compose -f compose.http.yml run --rm migrate
if ($LASTEXITCODE -ne 0) { throw 'مهاجرت ناموفق بود؛ لاگ سرویس migrate را بررسی کنید.' }

Write-Host ''
Write-Host 'بروزرسانی (حالت HTTP) کامل شد ✓' -ForegroundColor Green
Write-Host 'سلامت سرویس‌ها : http://130.185.73.157:8080/api/v1/health/'
Write-Host 'وب‌اپ (PWA)   : http://130.185.73.157:8080/'
Write-Host ''
Write-Host 'ساخت کاربر مدیر اولیه (اختیاری):'
Write-Host '  $env:DJANGO_SUPERUSER_PASSWORD="رمز-دلخواه"; docker compose -f compose.http.yml run --rm migrate python manage.py createsuperuser --noinput --username admin'
Write-Host ''
Write-Host 'نکته: فایروال ویندوز باید پورت 8080 را از ورودی مجاز کند:' -ForegroundColor Yellow
Write-Host '  New-NetFirewallRule -DisplayName "Rose Attendance HTTP" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow'
Write-Host 'نکته: پس از بروزرسانی فرانت‌اند، در مرورگر یک بار بارگذاری مجدد کنید تا Service Worker جدید فعال شود.'

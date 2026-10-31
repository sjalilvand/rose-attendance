#Requires -Version 5.1
<#
.SYNOPSIS
  بروزرسانی یک‌فرمانی «رز سفید» روی استقرار بومی ویندوز (بدون Docker).

.DESCRIPTION
  فلو استاندارد: git pull --ff-only ← install-rose-app.ps1 -SkipFrontend (venv + مهاجرت دیتابیس + static)
  ← run-rose.ps1 -Restart ← بررسی سلامت API.
  dist فرانت‌اند در مخزن کامیت شده و سرور به Node.js نیازی ندارد.

.EXAMPLE
  .\update-rose.ps1
  .\update-rose.ps1 -SkipPull    # فقط نصب/مهاجرت/ری‌استارت بدون pull
#>
param(
  [switch]$SkipPull
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Set-Location $PSScriptRoot

$FrontendChanged = $false
$WebPort = 8085

Write-Host ''
Write-Host '== بروزرسانی سامانه رز سفید (استقرار بومی ویندوز) ==' -ForegroundColor Cyan
Write-Host ('  مخزن: ' + $PSScriptRoot)
Write-Host ''

$oldHead = (& git rev-parse HEAD).Trim()

# --- ۱/۳ دریافت آخرین نسخه از گیت‌هاب ----------------------------------------
if (-not $SkipPull) {
  Write-Host '-- ۱/۳ دریافت آخرین نسخه (git pull --ff-only) --' -ForegroundColor Yellow
  git pull --ff-only origin main
  if ($LASTEXITCODE -ne 0) {
    throw 'git pull ناموفق بود؛ تغییرات محلی را کنار بگذارید (git stash) و دوباره اجرا کنید.'
  }
  $newHead = (& git rev-parse HEAD).Trim()
  if ($newHead -ne $oldHead) {
    $fe = @(git diff --name-only $oldHead $newHead -- frontend/dist | Where-Object { $_ })
    if ($fe.Count -gt 0) { $FrontendChanged = $true }
  }
  Write-Host ''
}
else {
  Write-Host '-- ۱/۳ pull رد شد (-SkipPull) --' -ForegroundColor DarkGray
}

# --- ۲/۳ نصب وابستگی + مهاجرت دیتابیس + static --------------------------------
Write-Host '-- ۲/۳ وابستگی‌ها + مهاجرت دیتابیس + static (install-rose-app.ps1 -SkipFrontend) --' -ForegroundColor Yellow
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install-rose-app.ps1') -SkipFrontend
if ($LASTEXITCODE -ne 0) { throw 'install-rose-app.ps1 ناموفق بود؛ خروجی بالا را بررسی کنید.' }
Write-Host ''

# --- ۳/۳ ری‌استارت سرویس‌ها ----------------------------------------------------
Write-Host '-- ۳/۳ ری‌استارت سرویس‌ها (run-rose.ps1 -Restart) --' -ForegroundColor Yellow
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-rose.ps1') -Restart
if ($LASTEXITCODE -ne 0) { throw 'run-rose.ps1 ناموفق بود؛ خروجی بالا را بررسی کنید.' }

# --- بررسی سلامت API -----------------------------------------------------------
Start-Sleep -Seconds 3
$healthOk = $false
try {
  $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 ('http://localhost:' + $WebPort + '/api/v1/health/')
  if ($resp.StatusCode -eq 200) { $healthOk = $true }
} catch { }
if ($healthOk) {
  Write-Host ('سلامت API: OK (پورت ' + $WebPort + ')') -ForegroundColor Green
} else {
  Write-Warning ('سلامت API هنوز پاسخ نداد؛ چند لحظه صبر کنید و http://localhost:' + $WebPort + '/api/v1/health/ را دوباره باز کنید.')
}

Write-Host ''
Write-Host 'بروزرسانی کامل شد ✓' -ForegroundColor Green
Write-Host ('  وب‌اپ     : http://localhost:' + $WebPort + '/')
Write-Host ('  پنل ادمین : http://localhost:' + $WebPort + '/admin/')
if ($FrontendChanged) {
  Write-Host ''
  Write-Host 'فرانت‌اند تغییر کرد: در مرورگر یک بار Ctrl+Shift+R بزنید تا Service Worker جدید فعال شود.' -ForegroundColor Magenta
}
Write-Host ''

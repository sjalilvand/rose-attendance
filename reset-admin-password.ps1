#Requires -Version 5.1
<#
.SYNOPSIS
  ریست رمز کاربر مدیر پنل «رز سفید» (Django admin) — نسخه ۱

.DESCRIPTION
  env را از C:\rose-stack\rose-backend.env می‌خواند و رمز کاربر مدیر را با
  manage.py shell عوض می‌کند (کاربر را در صورت نبود هم با دسترسی ابرکاربر می‌سازد).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\reset-admin-password.ps1 -NewPassword "رمز-جدید-قوی"
  powershell -ExecutionPolicy Bypass -File .\reset-admin-password.ps1    # رمز تصادفی تولید می‌کند
#>

[CmdletBinding()]
param(
  [string]$NewPassword = "",
  [string]$Username = "admin"
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stack = 'C:\rose-stack'
$backend = 'C:\rose-attendance\backend'
$venvPy = "$stack\venv\Scripts\python.exe"
$envFile = "$stack\rose-backend.env"

Write-Host ''
Write-Host '== ریست رمز کاربر مدیر پنل رز سفید ==' -ForegroundColor Cyan
Write-Host ("   venv    : " + $venvPy)
Write-Host ("   env     : " + $envFile)

if (-not (Test-Path $venvPy)) { Write-Error 'venv یافت نشد — ابتدا install-rose-app.ps1 را اجرا کنید.'; exit 1 }
if (-not (Test-Path $envFile)) { Write-Error 'فایل env یافت نشد — ابتدا install-rose-app.ps1 را اجرا کنید.'; exit 1 }

# رمز تصادفی اگر داده نشده باشد
if ([string]::IsNullOrWhiteSpace($NewPassword)) {
  $chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ' + 'abcdefghjkmnpqrstuvwxyz' + '23456789' + '!@#%*+'
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $bytes = New-Object byte[] 16
  $rng.GetBytes($bytes); $rng.Dispose()
  $NewPassword = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
  Write-Host '   رمز تصادفی تولید شد.'
}

# بارگذاری env در این نشست (DJANGO_SETTINGS_MODULE و رمز دیتابیس و ...)
foreach ($line in (Get-Content $envFile)) {
  if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
  }
}

$env:ROSE_ADMIN_USERNAME = $Username
$env:ROSE_NEW_ADMIN_PASSWORD = $NewPassword

$code = @'
import os
from django.contrib.auth import get_user_model
U = get_user_model()
u, created = U.objects.get_or_create(
    username=os.environ["ROSE_ADMIN_USERNAME"],
    defaults={"is_staff": True, "is_superuser": True},
)
u.is_staff = True
u.is_superuser = True
u.set_password(os.environ["ROSE_NEW_ADMIN_PASSWORD"])
u.save()
print("OK username=%s created=%s" % (u.username, created))
'@

Push-Location $backend
try {
  & $venvPy manage.py shell -c $code
  $ok = ($LASTEXITCODE -eq 0)
} finally {
  Pop-Location
  Remove-Item Env:\ROSE_ADMIN_USERNAME -ErrorAction SilentlyContinue
  Remove-Item Env:\ROSE_NEW_ADMIN_PASSWORD -ErrorAction SilentlyContinue
}

if ($ok) {
  Write-Host ''
  Write-Host '   رمز مدیر با موفقیت عوض شد ✓' -ForegroundColor Green
  Write-Host ''
  Write-Host '   ─────────── اطلاعات ورود پنل ───────────' -ForegroundColor Yellow
  Write-Host ("   نام کاربری : " + $Username) -ForegroundColor Yellow
  Write-Host ("   رمز عبور   : " + $NewPassword) -ForegroundColor Yellow
  Write-Host '   آدرس پنل   : http://130.185.73.157:8085/admin/' -ForegroundColor Yellow
  Write-Host '   ────────────────────────────────────────' -ForegroundColor Yellow
  Write-Host ''
  Write-Host '   این رمز را در جای امنی ذخیره کنید.' -ForegroundColor DarkGray
} else {
  Write-Error 'تغییر رمز ناموفق بود — خروجی بالا را بررسی کنید.'
}

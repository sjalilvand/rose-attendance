#Requires -Version 5.1
<#
.SYNOPSIS
  ریست رمز کاربر postgres روی نمونه‌ی محلی و در حال اجرای PostgreSQL
  (مثلاً نمونه‌ی rosepsy) وقتی رمز فعلی را نمی‌دانید.

.DESCRIPTION
  روش کار:
    ۱) دایرکتوری داده (datadir) از خط فرمان پروسه‌ی در حال اجرای postgres.exe کشف می‌شود
    ۲) از pg_hba.conf نسخه پشتیبان گرفته می‌شود
    ۳) دو خط trust برای 127.0.0.1 موقتاً به ابتدای pg_hba.conf اضافه می‌شود
    ۴) سرویس PostgreSQL ری‌استارت می‌شود (چند ثانیه downtime)
    ۵) رمز postgres با ALTER USER تغییر می‌کند
    ۶) pg_hba.conf اصلی بازگردانده و دوباره ری‌استارت می‌شود
    ۷) رمز جدید در C:\rose-stack\secrets\pg_postgres_password.txt ذخیره می‌شود
       تا install-rose-app.ps1 خودکار از آن استفاده کند

  این اسکریپت باید با دسترسی Administrator اجرا شود.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\reset-postgres-password.ps1 -NewPassword "Rose#Pg2026"
#>

[CmdletBinding()]
param(
  [string]$NewPassword = "",
  [int]$Port = 5432,
  [string]$PgUser = "postgres"
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stack = 'C:\rose-stack'

Write-Host ''
Write-Host '== ریست رمز postgres نمونه‌ی محلی PostgreSQL ==' -ForegroundColor Cyan

# ---------- بررسی دسترسی Administrator ----------
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Warning 'این اسکریپت باید داخل PowerShell با دسترسی Administrator اجرا شود (ری‌استارت سرویس لازم است).'
}

# ---------- تولید رمز تصادفی در صورت نیاز ----------
if ([string]::IsNullOrWhiteSpace($NewPassword)) {
  $bytes = New-Object byte[] 24
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes); $rng.Dispose()
  $NewPassword = (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
  Write-Host ("   رمز تصادفی تولید شد: " + $NewPassword) -ForegroundColor Yellow
}

# ---------- کشف psql ----------
$psql = $null
if (Test-Path "$stack\stack-env.ps1") {
  try { . "$stack\stack-env.ps1"; $psql = $RosePsql } catch { }
}
if (-not $psql -or -not (Test-Path $psql)) {
  foreach ($c in @('C:\rosepsy\runtime\pgsql\bin\psql.exe', 'C:\Program Files\PostgreSQL\16\bin\psql.exe')) {
    if (Test-Path $c) { $psql = $c; break }
  }
}
if (-not $psql -or -not (Test-Path $psql)) {
  $cmd = Get-Command psql -ErrorAction SilentlyContinue
  if ($cmd) { $psql = $cmd.Source }
}
if (-not $psql -or -not (Test-Path $psql)) {
  Write-Error 'psql یافت نشد — مسیر آن را دستی در C:\rose-stack\stack-env.ps1 (RosePsql) تنظیم کنید.'
  exit 1
}
Write-Host ("   psql      : " + $psql)
$pgBin = Split-Path $psql -Parent

# ---------- کشف پروسه‌ی postmaster در حال اجرا ----------
function Get-PgMainProcess {
  Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '\s-D\s' } | Select-Object -First 1
}

$main = Get-PgMainProcess
if (-not $main) {
  # شاید PostgreSQL هنوز روشن نیست — تلاش برای روشن کردن سرویس
  Write-Host '   PostgreSQL در حال اجرا نیست — تلاش برای روشن کردن سرویس ...'
  $svcList = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -match 'postgres|pgsql') -or ($_.DisplayName -match 'postgres|pgsql') }
  foreach ($s in $svcList) {
    try { Start-Service $s.Name -ErrorAction Stop; Start-Sleep -Seconds 5; break } catch { }
  }
  $main = Get-PgMainProcess
  if (-not $main) {
    Write-Error 'پروسه‌ی PostgreSQL روی پورت 5432 در حال اجرا نیست — ابتدا سرویس PostgreSQL را روشن کنید.'
    exit 1
  }
}

# ---------- کشف datadir از خط فرمان پروسه ----------
$dataDir = $null
if ($main.CommandLine -match '-D\s+"([^"]+)"') { $dataDir = $Matches[1] }
elseif ($main.CommandLine -match '-D\s+([^\s"]+)') { $dataDir = $Matches[1] }
if (-not $dataDir -or -not (Test-Path (Join-Path $dataDir 'pg_hba.conf'))) {
  Write-Error ("دایرکتوری داده PostgreSQL کشف نشد (خط فرمان: " + $main.CommandLine + ")")
  exit 1
}
Write-Host ("   datadir   : " + $dataDir)

# ---------- کشف سرویس مالک پروسه ----------
$svc = Get-CimInstance Win32_Service -Filter "ProcessId=$($main.ProcessId)" -ErrorAction SilentlyContinue
if ($svc) { Write-Host ("   service   : " + $svc.Name) }
else { Write-Host '   service   : (به‌صورت سرویس ویندوزی اجرا نمی‌شود — از pg_ctl استفاده می‌شود)' }

# ---------- توابع کمکی ----------
function Wait-PgPort([int]$seconds = 45) {
  for ($i = 0; $i -lt $seconds; $i++) {
    try {
      $c = New-Object Net.Sockets.TcpClient
      $c.Connect('127.0.0.1', $Port)
      $c.Close()
      return $true
    } catch { Start-Sleep -Seconds 1 }
  }
  return $false
}

function Restart-Pg {
  if ($svc) {
    Restart-Service $svc.Name -Force -ErrorAction Stop
  } else {
    & (Join-Path $pgBin 'pg_ctl.exe') -D $dataDir restart -m fast 2>&1 | Out-Null
  }
  if (-not (Wait-PgPort)) {
    Write-Error 'PostgreSQL پس از ری‌استارت روی پورت 5432 بالا نیامد — pg_hba.conf پشتیبان را دستی برگردانید.'
    exit 1
  }
}

# ---------- ۱) پشتیبان‌گیری و تزریق trust ----------
$hba = Join-Path $dataDir 'pg_hba.conf'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$hba.rose-backup-$stamp"
Copy-Item $hba $backup -Force
Write-Host ("   پشتیبان   : " + $backup)

$orig = [System.IO.File]::ReadAllText($hba)
$trustLines = "host all all 127.0.0.1/32 trust`r`nhost all all ::1/128 trust`r`n"
[System.IO.File]::WriteAllText($hba, $trustLines + $orig)

try {
  # ---------- ۲) ری‌استارت ----------
  Write-Host '   ری‌استارت PostgreSQL (چند ثانیه) ...'
  Restart-Pg

  # ---------- ۳) تغییر رمز ----------
  $safe = $NewPassword.Replace("'", "''")
  & $psql -h 127.0.0.1 -p $Port -U $PgUser -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER $PgUser WITH PASSWORD '$safe';"
  if ($LASTEXITCODE -ne 0) { throw 'اجرای ALTER USER ناموفق بود.' }
  Write-Host '   رمز postgres تغییر کرد.' -ForegroundColor Green

  # ---------- ۴) بازگرداندن pg_hba و ری‌استارت مجدد ----------
  Copy-Item $backup $hba -Force
  Write-Host '   pg_hba.conf اصلی بازگردانده شد — ری‌استارت مجدد ...'
  Restart-Pg

  # ---------- ۵) تست با رمز جدید ----------
  $env:PGPASSWORD = $NewPassword
  & $psql -h 127.0.0.1 -p $Port -U $PgUser -c "SELECT 1;" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Warning 'تست اتصال با رمز جدید ناموفق بود — به‌نظر می‌رسد pg_hba.conf محدودیت دیگری دارد. لاگ PostgreSQL را بررسی کنید.'
  } else {
    Write-Host '   اتصال با رمز جدید تأیید شد.' -ForegroundColor Green
  }
  Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

  # ---------- ۶) ذخیره رمز برای install-rose-app ----------
  New-Item -ItemType Directory -Force -Path "$stack\secrets" | Out-Null
  [System.IO.File]::WriteAllText("$stack\secrets\pg_postgres_password.txt", $NewPassword)
  Write-Host ("   نوشته شد: " + $stack + "\secrets\pg_postgres_password.txt")
  Write-Host ''
  Write-Host 'ریست رمز کامل شد — حالا اجرا کنید:' -ForegroundColor Cyan
  Write-Host '  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز-ادمین"'
} catch {
  # بازگردانی ایمن در صورت خطا
  Write-Warning ("خطا: " + $_.Exception.Message)
  Write-Warning 'بازگرداندن pg_hba.conf اصلی ...'
  Copy-Item $backup $hba -Force -ErrorAction SilentlyContinue
  try { Restart-Pg } catch { Write-Warning 'ری‌استارت مجدد ناموفق بود — دستی بررسی کنید.' }
  exit 1
}

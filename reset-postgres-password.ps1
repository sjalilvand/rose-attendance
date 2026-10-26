#Requires -Version 5.1
<#
.SYNOPSIS
  ریست رمز کاربر postgres روی نمونه‌ی محلی PostgreSQL (مثلاً نمونه‌ی rosepsy) — نسخه ۳.۲
  حالت‌آگاه و قابل ادامه: اگر سرور خاموش باشد آن را روشن می‌کند، اگر trust از اجرای قبلی
  فعال باشد بدون ری‌استارت اضافی رمز را عوض می‌کند، و در همه‌ی مراحل timeout دارد.

.DESCRIPTION
  مراحل (idempotent — اجرای تکراری بی‌خطر است):
    ۱) کشف psql و datadir (از پروسه در حال اجرا، پارامتر -DataDir، یا مسیرهای شناخته‌شده)
    ۲) تعیین وضعیت: پورت باز؟ trust فعال؟ pg_hba.conf آلوده به trust اجرای قبلی؟
    ۳) گرفتن متن «اصلی» pg_hba.conf از بکاپ‌های قبلی یا بازسازی
    ۴) تزریق trust (اگر لازم) و اطمینان از روشن بودن سرور (pg_ctl با timeout، fallback: taskkill)
    ۵) ALTER USER ... PASSWORD (در حالت trust)
    ۶) بازگردانی pg_hba.conf اصلی و ری‌استارت (stop+start با timeout)
    ۷) تست اتصال با رمز جدید و ذخیره در C:\rose-stack\secrets\pg_postgres_password.txt

  این اسکریپت باید با دسترسی Administrator اجرا شود.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\reset-postgres-password.ps1 -NewPassword "Rose#Pg1404"
#>

[CmdletBinding()]
param(
  [string]$NewPassword = "",
  [int]$Port = 5432,
  [string]$PgUser = "postgres",
  [string]$DataDir = ""
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stack = 'C:\rose-stack'
$marker = '# rose-trust-injected'

Write-Host ''
Write-Host '== ریست رمز postgres نمونه‌ی محلی PostgreSQL — نسخه ۳.۲ ==' -ForegroundColor Cyan

# ---------- دسترسی Administrator ----------
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Warning 'بهتر است داخل PowerShell با دسترسی Administrator اجرا شود.'
}

# ---------- رمز تصادفی در صورت نیاز ----------
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
  Write-Error 'psql یافت نشد — مسیر آن را در C:\rose-stack\stack-env.ps1 (RosePsql) تنظیم کنید.'
  exit 1
}
Write-Host ("   psql      : " + $psql)
$pgBin = Split-Path $psql -Parent
$pgCtl = Join-Path $pgBin 'pg_ctl.exe'

# ---------- کشف datadir ----------
function Find-DataDir {
  # ۱) پروسه در حال اجرا (معتبرترین منبع)
  $main = Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '\s-D\s' } | Select-Object -First 1
  if ($main) {
    if ($main.CommandLine -match '-D\s+"([^"]+)"') { return $Matches[1] }
    elseif ($main.CommandLine -match '-D\s+([^\s"]+)') { return $Matches[1] }
  }
  # ۲) پارامتر و مسیرهای شناخته‌شده
  foreach ($c in @($DataDir, 'C:\rosepsy\data\pgdata', 'C:\Program Files\PostgreSQL\16\data')) {
    if ($c -and (Test-Path (Join-Path $c 'pg_hba.conf'))) { return $c }
  }
  # ۳) جستجو زیر C:\rosepsy
  try {
    $hit = Get-ChildItem 'C:\rosepsy' -Filter 'pg_hba.conf' -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.DirectoryName }
  } catch { }
  return $null
}

$dataDir = Find-DataDir
if (-not $dataDir -or -not (Test-Path (Join-Path $dataDir 'pg_hba.conf'))) {
  Write-Error 'دایرکتوری داده PostgreSQL پیدا نشد — با -DataDir "مسیر" دستی بدهید.'
  exit 1
}
Write-Host ("   datadir   : " + $dataDir)

# ---------- سرویس ویندوزی؟ ----------
$mainProc = Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match '\s-D\s' } | Select-Object -First 1
$svc = $null
if ($mainProc) {
  $svc = Get-CimInstance Win32_Service -Filter "ProcessId=$($mainProc.ProcessId)" -ErrorAction SilentlyContinue
}
if (-not $svc) {
  $svc = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -match 'postgres|pgsql') -and $_.State -eq 'Running' } | Select-Object -First 1
}
if ($svc) { Write-Host ("   service   : " + $svc.Name) }
else { Write-Host '   service   : ندارد — از pg_ctl استفاده می‌شود' }

# ---------- ابزارهای وضعیت ----------
function Test-PgPort {
  try {
    $c = New-Object Net.Sockets.TcpClient
    $iar = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(1500)
    $connected = $ok -and $c.Connected
    $c.Close()
    return $connected
  } catch { return $false }
}

function Invoke-PgCtl([string[]]$CtlArgs, [int]$TimeoutSec) {
  New-Item -ItemType Directory -Force -Path "$stack\logs" | Out-Null
  $out = "$stack\logs\pg-ctl.out.log"
  $err = "$stack\logs\pg-ctl.err.log"
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $p = Start-Process -FilePath $pgCtl -ArgumentList $CtlArgs -NoNewWindow -PassThru `
      -RedirectStandardOutput $out -RedirectStandardError $err
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
      try { $p.Kill() } catch { }
      return -1
    }
    return $p.ExitCode
  } finally {
    $ErrorActionPreference = $prev
  }
}

function Stop-PgRobust {
  if (-not (Test-PgPort)) { Write-Host '   PostgreSQL خاموش است.'; return $true }
  Write-Host '   توقف PostgreSQL ...'
  if ($svc) {
    Stop-Service $svc.Name -Force -ErrorAction SilentlyContinue
  } else {
    $code = Invoke-PgCtl @('stop', '-D', $dataDir, '-m', 'fast', '-w', '-t', '60') 90
    if ($code -eq -1) { Write-Host '     pg_ctl تایم‌اوت شد — توقف اجباری ...' }
  }
  if (Test-PgPort) {
    # fallback: توقف اجباری postmaster از postmaster.pid
    try {
      $pmPid = (Get-Content (Join-Path $dataDir 'postmaster.pid') -TotalCount 1).Trim()
      if ("$pmPid" -match '^\d+$') {
        Write-Host ("     توقف اجباری پروسه " + $pmPid + " ...")
        Stop-Process -Id ([int]$pmPid) -Force -ErrorAction SilentlyContinue
      }
    } catch { }
    Start-Sleep -Seconds 3
  }
  return (-not (Test-PgPort))
}

function Start-PgRobust {
  if (Test-PgPort) { Write-Host '   PostgreSQL روشن است.'; return $true }
  Write-Host '   روشن کردن PostgreSQL ...'
  $startLog = "$stack\logs\rose-pg-start.log"
  if ($svc) {
    Start-Service $svc.Name -ErrorAction SilentlyContinue
  } else {
    if (-not (Test-Path $pgCtl)) { Write-Warning ("pg_ctl یافت نشد: " + $pgCtl); return $false }
    $code = Invoke-PgCtl @('start', '-D', $dataDir, '-w', '-t', '60', '-l', $startLog) 120
    if ($code -ne 0) { Write-Host ("     pg_ctl خروجی غیرصفر داد (کد " + $code + ")") }
  }
  for ($i = 0; $i -lt 20; $i++) { if (Test-PgPort) { break }; Start-Sleep -Seconds 1 }
  if (-not (Test-PgPort)) {
    Write-Warning 'سرور بالا نیامد — ۱۵ خط آخر لاگ:'
    foreach ($f in @("$stack\logs\rose-pg-start.log", "$stack\logs\pg-ctl.err.log", "$stack\logs\pg-ctl.out.log")) {
      if (Test-Path $f) {
        Get-Content $f -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ("      " + $_) }
        break
      }
    }
    return $false
  }
  return $true
}

# ---------- تحلیل وضعیت pg_hba.conf ----------
$hba = Join-Path $dataDir 'pg_hba.conf'
$hbaText = [System.IO.File]::ReadAllText($hba)
$polluted = ($hbaText -match '(?m)^host all all (127\.0\.0\.1/32|::1/128) trust\r?\n')

$portOpen = Test-PgPort
Write-Host ("   وضعیت     : پورت " + $(if ($portOpen) { 'باز' } else { 'بسته' }) + " / pg_hba آلوده به trust: " + $(if ($polluted) { 'بله' } else { 'خیر' }))

# متن «اصلی» pg_hba — از بکاپ قبلی یا بازسازی
$backups = Get-ChildItem $dataDir -Filter 'pg_hba.conf.rose-backup-*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
if ($polluted -and $backups) {
  $originalText = [System.IO.File]::ReadAllText($backups[0].FullName)
  Write-Host ("   متن اصلی  : از بکاپ " + $backups[0].Name)
} elseif ($polluted) {
  # بازسازی: حذف خطوط trust تزریق‌شده
  $lines = $hbaText -split "`r?`n" | Where-Object { ($_ -notmatch '^host all all (127\.0\.0\.1/32|::1/128) trust\r?$') -and ($_.Trim() -ne $marker) }
  $originalText = ($lines -join "`r`n")
  Write-Host '   متن اصلی  : با حذف خطوط trust بازسازی شد'
} else {
  $originalText = $hbaText
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $backup = "$hba.rose-backup-$stamp"
  Copy-Item $hba $backup -Force
  Write-Host ("   پشتیبان   : " + $backup)
}

# ---------- آیا trust همین حالا فعال است؟ ----------
$trustActive = $false
if ($portOpen) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    & $psql -h 127.0.0.1 -p $Port -U $PgUser -d postgres -tA -c "SELECT 1;" > $null 2>$null
    $trustActive = ($LASTEXITCODE -eq 0)
  } catch { $trustActive = $false }
  $ErrorActionPreference = $prev
  Write-Host ("   trust فعال: " + $(if ($trustActive) { 'بله (اتصال بدون رمز ممکن است)' } else { 'خیر (رمز لازم است)' }))
}

# ---------- توالی اصلی ----------
$restored = $false
function Restore-Hba {
  [System.IO.File]::WriteAllText($hba, $originalText)
  $script:restored = $true
  Write-Host '   pg_hba.conf اصلی بازگردانده شد.'
}

try {
  # --- مرحله ۱: فعال کردن trust (اگر لازم) و روشن کردن سرور ---
  if (-not $trustActive) {
    if ($polluted) {
      Write-Host '   pg_hba قبلاً trust دارد — بدون تزریق مجدد ادامه می‌دهیم.'
    } else {
      $trustLines = $marker + "`r`n" + "host all all 127.0.0.1/32 trust`r`nhost all all ::1/128 trust`r`n"
      [System.IO.File]::WriteAllText($hba, $trustLines + $originalText)
      Write-Host '   دو خط trust موقت به pg_hba.conf اضافه شد.'
      if ($portOpen) { if (-not (Stop-PgRobust)) { throw 'توقف PostgreSQL ناموفق بود.' } }
    }
    if (-not (Start-PgRobust)) { throw 'روشن کردن PostgreSQL ناموفق بود — لاگ بالا را بررسی کنید.' }
  }

  # --- مرحله ۲: تغییر رمز در حالت trust ---
  $safe = $NewPassword.Replace("'", "''")
  $env:PGPASSWORD = ''
  & $psql -h 127.0.0.1 -p $Port -U $PgUser -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER $PgUser WITH PASSWORD '$safe';"
  if ($LASTEXITCODE -ne 0) { throw 'اجرای ALTER USER ناموفق بود.' }
  Write-Host '   رمز postgres تغییر کرد.' -ForegroundColor Green

  # --- مرحله ۳: بازگردانی pg_hba اصلی و ری‌استارت ---
  Restore-Hba
  if (-not (Stop-PgRobust)) { throw 'توقف PostgreSQL برای اعمال pg_hba ناموفق بود.' }
  if (-not (Start-PgRobust)) { throw 'روشن کردن مجدد PostgreSQL ناموفق بود — لاگ بالا را بررسی کنید.' }

  # --- مرحله ۴: تست با رمز جدید ---
  $env:PGPASSWORD = $NewPassword
  & $psql -h 127.0.0.1 -p $Port -U $PgUser -c "SELECT 1;" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Warning 'تست اتصال با رمز جدید ناموفق بود — pg_hba ممکن است محدودیت دیگری داشته باشد (لاگ PostgreSQL را ببینید).'
  } else {
    Write-Host '   اتصال با رمز جدید تأیید شد.' -ForegroundColor Green
  }
  Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

  # --- مرحله ۵: ذخیره رمز برای install-rose-app ---
  New-Item -ItemType Directory -Force -Path "$stack\secrets" | Out-Null
  [System.IO.File]::WriteAllText("$stack\secrets\pg_postgres_password.txt", $NewPassword)
  Write-Host ("   نوشته شد: " + $stack + "\secrets\pg_postgres_password.txt")
  Write-Host ''
  Write-Host 'ریست رمز کامل شد — حالا اجرا کنید:' -ForegroundColor Cyan
  Write-Host '  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1 -AdminPassword "رمز-ادمین"'
} catch {
  Write-Warning ("خطا: " + $_.Exception.Message)
  if (-not $restored) {
    try { Restore-Hba; if (-not (Stop-PgRobust)) { }; if (-not (Start-PgRobust)) { } } catch { }
  }
  exit 1
}

#Requires -Version 5.1
<#
.SYNOPSIS
  نصب پیش‌نیازهای سامانه «رز سفید» روی ویندوز — بدون Docker.
  نصب: Python 3.12 + Node.js 22 + PostgreSQL 16 + PostGIS + Redis + Nginx + NSSM

.DESCRIPTION
  همه چیز در C:\rose-stack نصب می‌شود (Redis/Nginx/NSSM) و برنامه‌ها با نصب‌کننده‌های
  رسمی ویندوزی نصب می‌شوند. اسکریپت idempotent است — اجزای موجود را دوباره نصب نمی‌کند.
  PowerShell را حتماً Run as Administrator اجرا کنید.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-rose-prereq.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ProgressPreference = 'SilentlyContinue'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error 'این اسکریپت باید با دسترسی Administrator اجرا شود.'
  exit 1
}

$stack = 'C:\rose-stack'
New-Item -ItemType Directory -Force -Path $stack, "$stack\logs", "$stack\secrets" | Out-Null
$tmp = "$stack\_downloads"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

$report = [ordered]@{}

function Test-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = "$machine;$user"
}

function Get-WebFile([string[]]$urls, [string]$outFile) {
  foreach ($u in $urls) {
    try {
      Write-Host "    دانلود: $u" -ForegroundColor DarkGray
      Invoke-WebRequest -Uri $u -OutFile $outFile -UseBasicParsing -TimeoutSec 900
      if ((Get-Item $outFile).Length -gt 1MB) { return $true }
    } catch {
      Write-Host "    ناموفق: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
  }
  return $false
}

function Find-Python {
  Refresh-Path
  foreach ($c in @('python', 'py')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) {
      try {
        $v = (& $cmd.Source --version 2>&1) | Out-String
        if ($v -match 'Python\s+3\.(12|13)') { return $cmd.Source }
      } catch { }
    }
  }
  return $null
}

function Find-PgSql {
  # ۱) مسیر استاندارد
  $std = 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
  if (Test-Path $std) { return $std }
  # ۲) از روی سرویس ویندوز
  $svc = Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($svc -and $svc.PathName) {
    $dir = Split-Path (Split-Path ($svc.PathName -replace '^"([^"]+)"\s.*$', '$1') -Parent) -Parent
    $bin = Join-Path $dir 'bin\psql.exe'
    if (Test-Path $bin) { return $bin }
    $bin2 = Join-Path (Split-Path ($svc.PathName -replace '^"([^"]+)"\s.*$', '$1') -Parent) 'psql.exe'
    if (Test-Path $bin2) { return $bin2 }
  }
  # ۳) روی PATH
  if (Test-Command psql) { return (Get-Command psql).Source }
  return $null
}

function Find-PostGisControl([string]$psqlPath) {
  if (-not $psqlPath) { return $false }
  $root = Split-Path (Split-Path $psqlPath -Parent) -Parent
  return (Test-Path (Join-Path $root 'share\extension\postgis.control'))
}

Refresh-Path
Write-Host ''
Write-Host '== نصب پیش‌نیازهای رز سفید (بدون Docker) ==' -ForegroundColor Cyan

# ---------------------------------------------------------------- Python -----
Write-Host '-- ۱/۷ Python 3.12 --' -ForegroundColor Yellow
$py = Find-Python
if ($py) {
  Write-Host "   موجود است: $py" -ForegroundColor Green
  $report['python'] = $py
} else {
  $installed = $false
  if (Test-Command winget) {
    Write-Host '   نصب با winget ...'
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $py = Find-Python
    if ($py) { $installed = $true }
  }
  if (-not $installed) {
    $ok = $false
    foreach ($v in @('3.12.10', '3.12.9', '3.12.8', '3.12.7')) {
      $u = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
      $f = "$tmp\python-$v-amd64.exe"
      if (Get-WebFile @($u) $f) {
        Write-Host "   نصب بی‌صدا Python $v (چند دقیقه) ..."
        Start-Process -Wait -FilePath $f -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0'
        $ok = $true; break
      }
    }
    if (-not $ok) { Write-Warning 'نصب Python ناموفق بود — دستی از python.org نصب کنید.' }
  }
  $py = Find-Python
  if ($py) { Write-Host "   نصب شد: $py" -ForegroundColor Green }
  $report['python'] = $(if ($py) { $py } else { 'FAILED' })
}

# ------------------------------------------------------------------ Node -----
Write-Host '-- ۲/۷ Node.js 22 LTS --' -ForegroundColor Yellow
Refresh-Path
$nodeVer = $null
if (Test-Command node) { $nodeVer = ((& node --version) | Out-String).Trim() }
if ($nodeVer -match '^v(20|22|24)\.') {
  Write-Host "   موجود است: node $nodeVer" -ForegroundColor Green
  $report['node'] = $nodeVer
} else {
  $installed = $false
  if (Test-Command winget) {
    Write-Host '   نصب با winget ...'
    winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
    if (Test-Command node) { $installed = $true }
  }
  if (-not $installed) {
    foreach ($v in @('22.14.0', '22.12.0', '22.11.0')) {
      $u = "https://nodejs.org/dist/v$v/node-v$v-x64.msi"
      $f = "$tmp\node-v$v-x64.msi"
      if (Get-WebFile @($u) $f) {
        Write-Host "   نصب بی‌صدا Node v$v ..."
        Start-Process -Wait -FilePath 'msiexec.exe' -ArgumentList '/i', $f, '/qn', '/norestart'
        $installed = $true; break
      }
    }
    if (-not $installed) { Write-Warning 'نصب Node.js ناموفق بود — دستی از nodejs.org نصب کنید.' }
  }
  Refresh-Path
  $nodeVer = $null
  if (Test-Command node) { $nodeVer = ((& node --version) | Out-String).Trim() }
  $report['node'] = $(if ($nodeVer) { $nodeVer } else { 'FAILED' })
  if ($nodeVer) { Write-Host "   نصب شد: node $nodeVer" -ForegroundColor Green }
}

# ----------------------------------------------------------- PostgreSQL ------
Write-Host '-- ۳/۷ PostgreSQL 16 --' -ForegroundColor Yellow
$psql = Find-PgSql
if ($psql) {
  Write-Host "   موجود است: $psql" -ForegroundColor Green
  $report['postgresql'] = $psql
} else {
  # رمز postgres تولید و ذخیره می‌شود
  $pgPwFile = "$stack\secrets\pg_postgres_password.txt"
  if (-not (Test-Path $pgPwFile)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    [System.IO.File]::WriteAllText($pgPwFile, (-join ($bytes | ForEach-Object { $_.ToString('x2') })))
  }
  $pgPw = (Get-Content $pgPwFile -Raw).Trim()
  $installed = $false
  if (Test-Command winget) {
    Write-Host '   نصب با winget ...'
    winget install -e --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements --override "--mode unattended --unattendedmodeui minimal --superpassword $pgPw" | Out-Null
    Start-Sleep -Seconds 10
    $psql = Find-PgSql
    if ($psql) { $installed = $true }
  }
  if (-not $installed) {
    foreach ($v in @('16.9-1', '16.8-1', '16.6-1', '16.4-1')) {
      $u = "https://get.enterprisedb.com/postgresql/postgresql-$v-windows-x64.exe"
      $f = "$tmp\postgresql-$v-windows-x64.exe"
      if (Get-WebFile @($u) $f) {
        Write-Host "   نصب بی‌صدا PostgreSQL $v (۵ تا ۱۰ دقیقه) ..."
        Start-Process -Wait -FilePath $f -ArgumentList '--mode', 'unattended', '--unattendedmodeui', 'minimal', "--superpassword=$pgPw"
        $installed = $true; break
      }
    }
    if (-not $installed) { Write-Warning 'نصب PostgreSQL ناموفق بود — دستی از postgresql.org (EDB installer) نصب کنید و رمز postgres را در C:\rose-stack\secrets\pg_postgres_password.txt بگذارید.' }
  }
  $psql = Find-PgSql
  if ($psql) { Write-Host "   نصب شد: $psql" -ForegroundColor Green }
  $report['postgresql'] = $(if ($psql) { $psql } else { 'FAILED' })
}

# --------------------------------------------------------------- PostGIS -----
Write-Host '-- ۴/۷ PostGIS (برای جغرافیا) --' -ForegroundColor Yellow
$gisOk = Find-PostGisControl $psql
if ($gisOk) {
  Write-Host '   موجود است.' -ForegroundColor Green
  $report['postgis'] = 'installed'
} elseif (-not $psql) {
  Write-Warning 'PostgreSQL یافت نشد؛ PostGIS بعد از PostgreSQL نصب می‌شود.'
  $report['postgis'] = 'SKIPPED (no PostgreSQL)'
} else {
  $ok = $false
  foreach ($v in @('3.4.3.1', '3.4.2.1', '3.4.1.5', '3.5.2.1', '3.5.1.1')) {
    $base = "https://download.osgeo.org/postgis/windows/pg16"
    $f = "$tmp\postgis-bundle-pg16x64-setup-$v.exe"
    $u1 = "$base/postgis-bundle-pg16x64-setup-$v.exe"
    $u2 = "$base/archive/postgis-bundle-pg16x64-setup-$v.exe"
    if (Get-WebFile @($u1, $u2) $f) {
      Write-Host "   نصب بی‌صدا PostGIS $v (چند دقیقه) ..."
      Start-Process -Wait -FilePath $f -ArgumentList '--mode', 'unattended'
      $ok = $true; break
    }
  }
  if (-not $ok) {
    Write-Warning 'نصب خودکار PostGIS ناموفق بود. دستی: StackBuilder را اجرا کنید (Categories > Spatial Extensions > PostGIS for PostgreSQL 16) یا نصب‌کننده را از download.osgeo.org/postgis/windows/pg16 بگیرید.'
  }
  $gisOk = Find-PostGisControl $psql
  $report['postgis'] = $(if ($gisOk) { 'installed' } else { 'FAILED - manual StackBuilder needed' })
}

# ----------------------------------------------------------------- Redis -----
Write-Host '-- ۵/۷ Redis (سرویس ویندوزی) --' -ForegroundColor Yellow
$redisDir = "$stack\redis"
if (Test-Path "$redisDir\redis-server.exe") {
  Write-Host '   موجود است.' -ForegroundColor Green
  $report['redis'] = "$redisDir\redis-server.exe"
} else {
  $f = "$tmp\Redis-x64-5.0.14.1.zip"
  $ok = Get-WebFile @('https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip') $f
  if ($ok) {
    New-Item -ItemType Directory -Force -Path $redisDir, "$redisDir\data" | Out-Null
    Expand-Archive -Force -Path $f -DestinationPath "$tmp\redis"
    Copy-Item "$tmp\redis\*.exe", "$tmp\redis\*.dll" $redisDir -ErrorAction SilentlyContinue
    $conf = @"
bind 127.0.0.1
port 6379
dir ./
appendonly yes
maxmemory-policy noeviction
databases 16
"@
    [System.IO.File]::WriteAllText("$redisDir\redis.conf", $conf)
    $report['redis'] = "$redisDir\redis-server.exe"
    Write-Host '   نصب شد.' -ForegroundColor Green
  } else {
    Write-Warning 'دانلود Redis ناموفق بود — از github.com/tporadowski/redis/releases دستی بگیرید و در C:\rose-stack\redis بریزید.'
    $report['redis'] = 'FAILED'
  }
}

# ------------------------------------------------------------------ NSSM -----
Write-Host '-- ۶/۷ NSSM (مدیریت سرویس‌ها) --' -ForegroundColor Yellow
$nssmDir = "$stack\nssm"
if (Test-Path "$nssmDir\nssm.exe") {
  Write-Host '   موجود است.' -ForegroundColor Green
  $report['nssm'] = "$nssmDir\nssm.exe"
} else {
  $f = "$tmp\nssm-2.24.zip"
  $ok = Get-WebFile @('https://nssm.cc/release/nssm-2.24.zip') $f
  if ($ok) {
    Expand-Archive -Force -Path $f -DestinationPath "$tmp\nssm"
    New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
    Copy-Item "$tmp\nssm\nssm-2.24\win64\nssm.exe" $nssmDir
    $report['nssm'] = "$nssmDir\nssm.exe"
    Write-Host '   نصب شد.' -ForegroundColor Green
  } else {
    Write-Warning 'دانلود NSSM ناموفق بود — از nssm.cc دستی بگیرید (win64) و در C:\rose-stack\nssm بریزید.'
    $report['nssm'] = 'FAILED'
  }
}

# ----------------------------------------------------------------- Nginx -----
Write-Host '-- ۷/۷ Nginx (وب‌سرور درگاه) --' -ForegroundColor Yellow
$nginxDir = "$stack\nginx"
if (Test-Path "$nginxDir\nginx.exe") {
  Write-Host '   موجود است.' -ForegroundColor Green
  $report['nginx'] = "$nginxDir\nginx.exe"
} else {
  $f = "$tmp\nginx.zip"
  $ok = $false
  foreach ($v in @('1.26.3', '1.26.2', '1.27.4')) {
    if (Get-WebFile @("https://nginx.org/download/nginx-$v.zip") $f) { $ok = $true; break }
  }
  if ($ok) {
    Expand-Archive -Force -Path $f -DestinationPath "$tmp\nginx"
    $src = Get-ChildItem "$tmp\nginx" -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $nginxDir | Out-Null
    Copy-Item "$($src.FullName)\*" $nginxDir -Recurse -Force
    # جایگزینی کانفیگ با کانفیگ رز سفید (نسخه پیش‌فرض نگه داشته می‌شود)
    if (Test-Path "$nginxDir\conf\nginx.conf") { Move-Item -Force "$nginxDir\conf\nginx.conf" "$nginxDir\conf\nginx.conf.default" }
    if (Test-Path "$stack\rose-nginx-windows.conf") { Copy-Item "$stack\rose-nginx-windows.conf" "$nginxDir\conf\nginx.conf" }
    elseif (Test-Path 'C:\rose-attendance\rose-nginx-windows.conf') { Copy-Item 'C:\rose-attendance\rose-nginx-windows.conf' "$nginxDir\conf\nginx.conf" }
    $report['nginx'] = "$nginxDir\nginx.exe"
    Write-Host '   نصب شد (کانفیگ رز سفید جایگزین شد).' -ForegroundColor Green
  } else {
    Write-Warning 'دانلود Nginx ناموفق بود — از nginx.org/download دستی بگیرید و در C:\rose-stack\nginx باز کنید.'
    $report['nginx'] = 'FAILED'
  }
}

# -------------------------------------------------------------- Firewall -----
Write-Host '-- فایروال: باز کردن پورت 8080 --' -ForegroundColor Yellow
if (-not (Get-NetFirewallRule -DisplayName 'Rose Attendance HTTP 8080' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'Rose Attendance HTTP 8080' -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Any | Out-Null
  Write-Host '   قانون فایروال ساخته شد.' -ForegroundColor Green
  $report['firewall_8080'] = 'allowed'
} else {
  $report['firewall_8080'] = 'already allowed'
}

# ---------------------------------------------------------------- Summary ----
Write-Host ''
Write-Host '== خلاصه نصب پیش‌نیازها ==' -ForegroundColor Cyan
foreach ($k in $report.Keys) { Write-Host ("  " + $k.PadRight(14) + " : " + $report[$k]) }
Write-Host ''
Write-Host 'گام بعدی:  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1' -ForegroundColor Cyan
Write-Host '(اسکریپت بعدی: ساخت دیتابیس، نصب وابستگی‌های بک‌اند، build فرانت‌اند و مهاجرت‌ها)'

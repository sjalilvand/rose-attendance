#Requires -Version 5.1
<#
.SYNOPSIS
  نصب پیش‌نیازهای سامانه «رز سفید» روی ویندوز — بدون Docker (نسخه ۲).
  نصب: Python 3.12 + Node.js + PostgreSQL 16 + PostGIS + Redis + Nginx + NSSM

.CHANGES v2
  - پورت‌های جدید: وب 8085 و بک‌اند 3005 (فایروال خودکار باز می‌شود)
  - PostgreSQL: دانلود مستقیم نصب‌کننده با BITS (رفع مشکل winget) +
    fallback «بسته باینری» (بدون نصب‌کننده) + winget به‌عنوان آخرین گزینه
  - NSSM: دانلود از میرور GitHub (nssm.cc قطع است)
  - PostGIS: انتخاب خودکار آخرین بسته از فهرست OSGeo؛ اختیاری است و شکستش
    نصب را متوقف نمی‌کند (برنامه بدون PostGIS هم کار می‌کند)
  - کانفیگ Nginx در هر اجرا از مخزن به‌روزرسانی می‌شود
  - استثنای Windows Defender برای C:\rose-stack
  - تولید C:\rose-stack\stack-env.ps1 برای اسکریپت‌های بعدی

.DESCRIPTION
  PowerShell را حتماً Run as Administrator اجرا کنید. اسکریپت idempotent است
  و اجزای موجود را دوباره نصب نمی‌کند.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-rose-prereq.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error 'این اسکریپت باید با دسترسی Administrator اجرا شود.'
  exit 1
}

$stack = 'C:\rose-stack'
$repo  = 'C:\rose-attendance'
$RoseWebPort = 8085
$RoseApiPort = 3005
New-Item -ItemType Directory -Force -Path $stack, "$stack\logs", "$stack\secrets", "$stack\_downloads" | Out-Null
$tmp = "$stack\_downloads"

$report = [ordered]@{}

function Test-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = "$machine;$user"
}

function Get-WebFile([string[]]$urls, [string]$outFile, [double]$MinMB = 1) {
  foreach ($u in $urls) {
    try {
      Write-Host "    دانلود: $u" -ForegroundColor DarkGray
      $done = $false
      # ۱) BITS — مقاوم در برابر قطعی شبکه و قابل ادامه
      if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
        try { Start-BitsTransfer -Source $u -Destination $outFile -ErrorAction Stop; $done = $true } catch { }
      }
      # ۲) Invoke-WebRequest به‌عنوان جایگزین
      if (-not $done) {
        Invoke-WebRequest -Uri $u -OutFile $outFile -UseBasicParsing -TimeoutSec 1800
      }
      if ((Test-Path $outFile) -and ((Get-Item $outFile).Length -gt ($MinMB * 1MB))) { return $true }
    } catch {
      Write-Host "    ناموفق: $($_.Exception.Message)" -ForegroundColor DarkYellow
      Remove-Item $outFile -Force -ErrorAction SilentlyContinue
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

function Get-PgExeFromService {
  $svc = Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($svc -and $svc.PathName) {
    $exe = $null
    if ($svc.PathName -match '^"([^"]+)"') { $exe = $Matches[1] } else { $exe = ($svc.PathName -split ' ')[0] }
    if ($exe -and (Test-Path $exe)) { return $exe }
  }
  return $null
}

function Find-PgSql {
  # ۱) مسیر استاندارد
  $std = 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
  if (Test-Path $std) { return $std }
  # ۲) رجیستری (نصب EDB یا ثبت‌شده توسط اسکریپت)
  try {
    $reg = Get-ItemProperty 'HKLM:\SOFTWARE\PostgreSQL\Installations\postgresql-x64-16' -ErrorAction SilentlyContinue
    if ($reg -and $reg.'Base Directory') {
      $bin = Join-Path $reg.'Base Directory' 'bin\psql.exe'
      if (Test-Path $bin) { return $bin }
    }
  } catch { }
  # ۳) از روی سرویس ویندوز
  $pgExe = Get-PgExeFromService
  if ($pgExe) {
    $bin = Join-Path (Split-Path (Split-Path $pgExe -Parent) -Parent) 'bin\psql.exe'
    if (Test-Path $bin) { return $bin }
  }
  # ۴) بسته باینری محلی اسکریپت
  $local = "$stack\pgsql\pgsql\bin\psql.exe"
  if (Test-Path $local) { return $local }
  # ۵) روی PATH
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
Write-Host '== نصب پیش‌نیازهای رز سفید (بدون Docker) — نسخه ۲ ==' -ForegroundColor Cyan
Write-Host ("   پورت‌ها: وب $RoseWebPort / بک‌اند $RoseApiPort") -ForegroundColor DarkCyan

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
Write-Host '-- ۲/۷ Node.js (20/22/24) --' -ForegroundColor Yellow
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

  # ---- مسیر الف: دانلود مستقیم نصب‌کننده EDB (BITS مقاوم در برابر قطعی شبکه)
  foreach ($v in @('16.12-1', '16.11-1', '16.10-1', '16.9-1', '16.8-1', '16.6-1')) {
    if ($installed) { break }
    $u = "https://get.enterprisedb.com/postgresql/postgresql-$v-windows-x64.exe"
    $f = "$tmp\postgresql-$v-windows-x64.exe"
    if (Get-WebFile @($u) $f -MinMB 250) {
      Write-Host "   نصب بی‌صدا PostgreSQL $v (۵ تا ۱۰ دقیقه) ..."
      Start-Process -Wait -FilePath $f -ArgumentList @(
        '--mode', 'unattended', '--unattendedmodeui', 'minimal',
        "--superpassword=$pgPw", '--serverport', '5432',
        '--servicename', 'postgresql-x64-16',
        '--enable-components', 'server,commandlinetools',
        '--disable-components', 'pgAdmin,stackbuilder'
      )
      $psql = Find-PgSql
      if ($psql) { $installed = $true }
    }
  }

  # ---- مسیر ب: بستهٔ باینری EDB (بدون نصب‌کننده) — initdb + ثبت سرویس
  if (-not $installed) {
    Write-Host '   نصب‌کننده در دسترس نیست — تلاش با بستهٔ باینری PostgreSQL ...' -ForegroundColor DarkCyan
    foreach ($v in @('16.9-1', '16.8-1', '16.6-1')) {
      $u = "https://get.enterprisedb.com/postgresql/postgresql-$v-windows-x64-binaries.zip"
      $f = "$tmp\pg-binaries-$v.zip"
      if (Get-WebFile @($u) $f -MinMB 250) {
        Write-Host '   باز کردن بسته (چند دقیقه) ...'
        New-Item -ItemType Directory -Force -Path "$stack\pgsql" | Out-Null
        Expand-Archive -Force -Path $f -DestinationPath "$stack\pgsql"
        $pgHome = "$stack\pgsql\pgsql"
        $pgData = "$stack\pgdata"
        $pwFile = "$tmp\pg_initpw.txt"
        Set-Content -Path $pwFile -Value $pgPw -NoNewline -Encoding Ascii
        # سرور PostgreSQL زیر حساب Administrator اجرا نمی‌شود؛ initdb با حساب NETWORK SERVICE
        icacls $pwFile /grant '*S-1-5-20:R' | Out-Null
        $initCmd = "`"$pgHome\bin\initdb.exe`" -D `"$pgData`" -U postgres -A scram-sha-256 -E UTF8 --locale=C --pwfile=`"$pwFile`" > `"$tmp\pg_init.log`" 2>&1"
        $initCmdFile = "$tmp\rose-pg-init.cmd"
        Set-Content -Path $initCmdFile -Value $initCmd -Encoding Ascii
        schtasks /Create /F /TN RosePgInit /SC ONCE /ST 23:59 /RU "NT AUTHORITY\NETWORK SERVICE" /TR "`"$initCmdFile`"" | Out-Null
        schtasks /Run /I /TN RosePgInit | Out-Null
        $waited = 0
        while (-not (Test-Path "$pgData\PG_VERSION") -and $waited -lt 240) { Start-Sleep -Seconds 5; $waited += 5 }
        schtasks /Delete /F /TN RosePgInit | Out-Null
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
        if (Test-Path "$pgData\PG_VERSION") {
          Write-Host '   خوشهٔ دیتابیس ساخته شد — ثبت سرویس postgresql-x64-16 ...'
          & "$pgHome\bin\pg_ctl.exe" register -N postgresql-x64-16 -D $pgData -S auto
          # کلید رجیستری برای نصب‌کنندهٔ PostGIS و کشف مسیر
          reg add "HKLM\SOFTWARE\PostgreSQL\Installations\postgresql-x64-16" /v "Base Directory" /t REG_SZ /d "$pgHome" /f | Out-Null
          reg add "HKLM\SOFTWARE\PostgreSQL\Installations\postgresql-x64-16" /v "Data Directory" /t REG_SZ /d "$pgData" /f | Out-Null
          reg add "HKLM\SOFTWARE\PostgreSQL\Installations\postgresql-x64-16" /v "BRANDING" /t REG_SZ /d "PostgreSQL 16" /f | Out-Null
          try { Start-Service postgresql-x64-16 -ErrorAction Stop } catch { Write-Warning ("شروع سرویس PostgreSQL ناموفق: " + $_.Exception.Message) }
          Start-Sleep -Seconds 5
        } else {
          Write-Warning 'initdb کامل نشد. لاگ:'
          Get-Content "$tmp\pg_init.log" -ErrorAction SilentlyContinue | Select-Object -First 15 | Write-Host
        }
        $psql = Find-PgSql
        if ($psql) { $installed = $true; break }
      }
    }
  }

  # ---- مسیر ج: winget (آخرین گزینه)
  if (-not $installed -and (Test-Command winget)) {
    Write-Host '   نصب با winget (تلاش مجدد) ...'
    winget install -e --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements --override "--mode unattended --unattendedmodeui minimal --superpassword $pgPw" | Out-Null
    Start-Sleep -Seconds 10
    $psql = Find-PgSql
    if ($psql) { $installed = $true }
  }

  if (-not $installed) {
    Write-Warning 'نصب خودکار PostgreSQL ناموفق بود. دستی نصب کنید:'
    Write-Warning '  ۱) https://www.enterprisedb.com/downloads/postgres-postgresql-downloads (installer 16 x64)'
    Write-Warning '  ۲) رمز postgres را در C:\rose-stack\secrets\pg_postgres_password.txt بگذارید'
  }
  $psql = Find-PgSql
  if ($psql) {
    Write-Host "   نصب شد: $psql" -ForegroundColor Green
    $svcName = (Get-Service postgresql* -ErrorAction SilentlyContinue | Select-Object -First 1).Name
    if ($svcName) {
      $svc = Get-Service $svcName
      if ($svc.StartType -eq 'Disabled') { Set-Service $svcName -StartupType Automatic }
      if ($svc.Status -ne 'Running') { try { Start-Service $svcName -ErrorAction Stop; Start-Sleep -Seconds 3 } catch { } }
    }
  }
  $report['postgresql'] = $(if ($psql) { $psql } else { 'FAILED - manual install needed' })
}

# --------------------------------------------------------------- PostGIS -----
Write-Host '-- ۴/۷ PostGIS (اختیاری — برای جغرافیا) --' -ForegroundColor Yellow
$gisOk = Find-PostGisControl $psql
if ($gisOk) {
  Write-Host '   موجود است.' -ForegroundColor Green
  $report['postgis'] = 'installed'
} elseif (-not $psql) {
  Write-Warning 'PostgreSQL یافت نشد؛ PostGIS رد شد.'
  $report['postgis'] = 'SKIPPED (no PostgreSQL)'
} else {
  # یافتن آخرین بسته از فهرست رسمی OSGeo
  $candidates = @()
  try {
    $list = (Invoke-WebRequest -UseBasicParsing -Uri 'https://download.osgeo.org/postgis/windows/pg16/' -TimeoutSec 120).Content
    $found = @()
    foreach ($m in [regex]::Matches($list, 'postgis-bundle-pg16x64-setup-([0-9]+)\.([0-9]+)\.([0-9]+)-([0-9]+)\.exe')) {
      $found += [pscustomobject]@{
        Name = $m.Value
        Sort = [version]("$($m.Groups[1].Value).$($m.Groups[2].Value).$($m.Groups[3].Value)." + $m.Groups[4].Value)
      }
    }
    $candidates = @($found | Sort-Object Sort -Descending | Select-Object -ExpandProperty Name -First 3)
  } catch { }
  foreach ($fixed in @('3.5.3-1', '3.5.2-1', '3.4.3-1')) { $candidates += $fixed }
  $candidates = @($candidates | Select-Object -Unique)
  foreach ($v in $candidates) {
    $f = "$tmp\$v"
    if (Get-WebFile @(
        "https://download.osgeo.org/postgis/windows/pg16/$v",
        "https://download.osgeo.org/postgis/windows/pg16/archive/$v"
      ) $f -MinMB 20) {
      Write-Host "   نصب بی‌صدا PostGIS $v (چند دقیقه) ..."
      Start-Process -Wait -FilePath $f -ArgumentList '--mode', 'unattended'
      break
    }
  }
  $gisOk = Find-PostGisControl $psql
  if ($gisOk) { Write-Host '   نصب شد.' -ForegroundColor Green }
  else {
    Write-Warning 'نصب PostGIS ناموفق بود — مهم نیست: برنامه بدون PostGIS هم کامل کار می‌کند.'
    Write-Warning 'برای نصب دستی بعداً: StackBuilder > Spatial Extensions > PostGIS for PostgreSQL 16'
  }
  $report['postgis'] = $(if ($gisOk) { 'installed' } else { 'FAILED (optional - app works without it)' })
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
  $ok = Get-WebFile @(
    'https://github.com/kirillkovalenko/nssm/releases/download/2.24/nssm-2.24.zip',
    'https://nssm.cc/release/nssm-2.24.zip'
  ) $f
  if ($ok) {
    Expand-Archive -Force -Path $f -DestinationPath "$tmp\nssm"
    New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
    Copy-Item "$tmp\nssm\nssm-2.24\win64\nssm.exe" $nssmDir -Force -ErrorAction SilentlyContinue
    Copy-Item "$tmp\nssm\win64\nssm.exe" $nssmDir -Force -ErrorAction SilentlyContinue
    if (Test-Path "$nssmDir\nssm.exe") {
      $report['nssm'] = "$nssmDir\nssm.exe"
      Write-Host '   نصب شد.' -ForegroundColor Green
    } else {
      Write-Warning 'زیپ NSSM باز شد ولی nssm.exe پیدا نشد — دستی win64\nssm.exe را در C:\rose-stack\nssm بگذارید.'
      $report['nssm'] = 'FAILED (extract issue)'
    }
  } else {
    Write-Warning 'دانلود NSSM ناموفق بود — دستی nssm.exe (win64) را در C:\rose-stack\nssm بگذارید.'
    Write-Warning '  منبع: https://github.com/kirillkovalenko/nssm/releases (nssm-2.24.zip)'
    $report['nssm'] = 'FAILED'
  }
}

# ----------------------------------------------------------------- Nginx -----
Write-Host '-- ۷/۷ Nginx (وب‌سرور درگاه) --' -ForegroundColor Yellow
$nginxDir = "$stack\nginx"
if (Test-Path "$nginxDir\nginx.exe") {
  Write-Host "   موجود است: $nginxDir\nginx.exe" -ForegroundColor Green
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
    $report['nginx'] = "$nginxDir\nginx.exe"
    Write-Host '   نصب شد.' -ForegroundColor Green
  } else {
    Write-Warning 'دانلود Nginx ناموفق بود — از nginx.org/download دستی بگیرید و در C:\rose-stack\nginx باز کنید.'
    $report['nginx'] = 'FAILED'
  }
}
# کانفیگ رز سفید همیشه به‌روزرسانی می‌شود (پورت 8085 / بک‌اند 3005)
$confSrc = $null
foreach ($c in @("$repo\rose-nginx-windows.conf", "$stack\rose-nginx-windows.conf")) {
  if (Test-Path $c) { $confSrc = $c; break }
}
if ($confSrc -and (Test-Path "$nginxDir\conf")) {
  if (-not (Test-Path "$nginxDir\conf\nginx.conf.default")) {
    if (Test-Path "$nginxDir\conf\nginx.conf") { Copy-Item "$nginxDir\conf\nginx.conf" "$nginxDir\conf\nginx.conf.default" -Force }
  }
  Copy-Item $confSrc "$nginxDir\conf\nginx.conf" -Force
  Write-Host ("   کانفیگ Nginx به‌روزرسانی شد (از " + $confSrc + ")") -ForegroundColor Green
}

# -------------------------------------------------------------- Defender -----
Write-Host '-- استثنای Windows Defender برای C:\rose-stack --' -ForegroundColor Yellow
try {
  Add-MpPreference -ExclusionPath $stack -ErrorAction Stop
  $report['defender'] = "excluded: $stack"
  Write-Host '   انجام شد.' -ForegroundColor Green
} catch {
  $report['defender'] = 'skipped'
  Write-Host '   رد شد (اختیاری).' -ForegroundColor DarkYellow
}

# -------------------------------------------------------------- Firewall -----
Write-Host "-- فایروال: باز کردن پورت‌های $RoseWebPort (وب) و $RoseApiPort (بک‌اند) --" -ForegroundColor Yellow
foreach ($fw in @(
    @{ Name = 'Rose Attendance Web 8085'; Port = $RoseWebPort },
    @{ Name = 'Rose Attendance API 3005'; Port = $RoseApiPort }
  )) {
  if (-not (Get-NetFirewallRule -DisplayName $fw.Name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $fw.Name -Direction Inbound -Protocol TCP -LocalPort $fw.Port -Action Allow -Profile Any | Out-Null
    Write-Host ("   قانون ساخته شد: " + $fw.Name) -ForegroundColor Green
  }
  $key = 'firewall_' + $fw.Port
  $report[$key] = 'allowed'
}

# --------------------------------------------------- stack-env.ps1 -----------
$pgHomeForEnv = ''
if ($psql) { $pgHomeForEnv = Split-Path (Split-Path $psql -Parent) -Parent }
$nodeForEnv = 'node'
$ncmd = Get-Command node -ErrorAction SilentlyContinue
if ($ncmd) { $nodeForEnv = $ncmd.Source }
$pyForEnv = $(if ($py) { $py } else { '' })
$stackEnv = @"
# generated by install-rose-prereq.ps1 — do not edit manually
`$RoseStack     = '$stack'
`$RoseRepo      = '$repo'
`$RosePython    = '$pyForEnv'
`$RoseNode      = '$nodeForEnv'
`$RosePgHome    = '$pgHomeForEnv'
`$RosePsql      = '$(if ($psql) { $psql })'
`$RoseRedis     = '$redisDir\redis-server.exe'
`$RoseRedisConf = '$redisDir\redis.conf'
`$RoseNssm      = '$nssmDir\nssm.exe'
`$RoseNginx     = '$nginxDir\nginx.exe'
`$RoseWebPort   = $RoseWebPort
`$RoseApiPort   = $RoseApiPort
"@
[System.IO.File]::WriteAllText("$stack\stack-env.ps1", $stackEnv)
Write-Host ("   نوشته شد: $stack\stack-env.ps1") -ForegroundColor Green

# ---------------------------------------------------------------- Summary ----
Write-Host ''
Write-Host '== خلاصه نصب پیش‌نیازها ==' -ForegroundColor Cyan
foreach ($k in $report.Keys) { Write-Host ("  " + $k.PadRight(14) + " : " + $report[$k]) }
Write-Host ''
Write-Host 'گام بعدی:  powershell -ExecutionPolicy Bypass -File .\install-rose-app.ps1' -ForegroundColor Cyan
Write-Host '(اسکریپت بعدی: ساخت دیتابیس، نصب وابستگی‌های بک‌اند، build فرانت‌اند و مهاجرت‌ها)'

#Requires -Version 5.1
<#
.SYNOPSIS
  مدیریت اجرای سامانه رز سفید بدون Docker — نسخه ۳.۴ (WinSW / NSSM).

.DESCRIPTION
  پورت‌ها: بک‌اند 3005 و وب 8085.
  مدیر سرویس: ابتدا NSSM (اگر موجود باشد)، وگرنه WinSW (خودکار دانلود می‌شود).
  هر دو ابزار سرویس ویندوزی واقعی می‌سازند؛ Start/Stop از طریق Get-Service کار می‌کند.
  سرویس‌ها: RoseRedis، RoseApi (Daphne/ASGI روی 3005)، RoseWorker، RoseBeat (Celery)
  و RoseNginx (پورت 8085 — سرو فرانت‌اند + پروکسی API و WebSocket).

.EXAMPLE
  .\run-rose.ps1 -InstallServices    # ساخت و شروع سرویس‌های ویندوزی (توصیه‌شده)
  .\run-rose.ps1 -Console            # اجرای سریع موقت در پنجره‌های کنسول
  .\run-rose.ps1 -Status             # وضعیت سرویس‌ها و پورت‌ها
  .\run-rose.ps1 -Stop | -Start | -Restart | -UninstallServices
#>

[CmdletBinding()]
param(
  [switch]$InstallServices,
  [switch]$UninstallServices,
  [switch]$Console,
  [switch]$Start,
  [switch]$Stop,
  [switch]$Restart,
  [switch]$WithPostgres,
  [string]$PostgresBin = "",
  [string]$PostgresData = "",
  [switch]$Status
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stack = 'C:\rose-stack'
$repo  = 'C:\rose-attendance'
$backend = "$repo\backend"
$RoseWebPort = 8085
$RoseApiPort = 3005
$nssm     = "$stack\nssm\nssm.exe"
$winswDir = "$stack\winsw"
$winswExe = "$winswDir\WinSW-x64.exe"
$venvPy  = "$stack\venv\Scripts\python.exe"
$envFile = "$stack\rose-backend.env"
$envCmd  = "$stack\rose-backend-env.cmd"

# ------------------------- خواندن env -------------------------
$envPairs = [ordered]@{}
if (Test-Path $envFile) {
  foreach ($line in (Get-Content $envFile)) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $envPairs[$Matches[1]] = $Matches[2] }
  }
} else {
  Write-Error "فایل $envFile یافت نشد — ابتدا install-rose-app.ps1 را اجرا کنید."
  exit 1
}

$script:SvcTool = $null

function Get-ServiceTool {
  if (Test-Path $nssm) { return 'nssm' }
  if (Test-Path $winswExe) { return 'winsw' }
  return $null
}

function Ensure-WinSW {
  if (Test-Path $winswExe) { return $true }
  Write-Host '   دانلود WinSW (مدیر سرویس ویندوزی) ...'
  New-Item -ItemType Directory -Force -Path $winswDir | Out-Null
  foreach ($u in @(
    'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe',
    'https://github.com/winsw/winsw/releases/download/v2.11.0/WinSW-x64.exe'
  )) {
    try {
      Write-Host "     دانلود: $u" -ForegroundColor DarkGray
      Invoke-WebRequest -Uri $u -OutFile $winswExe -UseBasicParsing -TimeoutSec 600
      if ((Test-Path $winswExe) -and ((Get-Item $winswExe).Length -gt 1MB)) { return $true }
    } catch { Write-Host "     ناموفق: $($_.Exception.Message)" -ForegroundColor DarkYellow }
  }
  return $false
}

function Escape-Xml([string]$s) {
  if ($null -eq $s) { return '' }
  return $s.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;').Replace('"', '&quot;')
}

# ------------------------- تعریف سرویس‌ها -------------------------
$services = @(
  @{ Name='RoseRedis';  App="$stack\redis\redis-server.exe"; Args="$stack\redis\redis.conf"; Dir="$stack\redis"; Deps=@(); StopExe=''; StopArgs='' },
  @{ Name='RoseApi';    App=$venvPy; Args="-m daphne -b 0.0.0.0 -p $RoseApiPort config.asgi:application"; Dir=$backend; Deps=@('RoseRedis'); StopExe=''; StopArgs='' },
  @{ Name='RoseWorker'; App=$venvPy; Args='-m celery -A config worker --pool=solo --loglevel=INFO --without-gossip --without-mingle'; Dir=$backend; Deps=@('RoseRedis'); StopExe=''; StopArgs='' },
  @{ Name='RoseBeat';   App=$venvPy; Args="-m celery -A config beat --loglevel=INFO --schedule=$stack\celerybeat-schedule"; Dir=$backend; Deps=@('RoseRedis'); StopExe=''; StopArgs='' },
  @{ Name='RoseNginx';  App="$stack\nginx\nginx.exe"; Args=''; Dir="$stack\nginx"; Deps=@(); StopExe="$stack\nginx\nginx.exe"; StopArgs='-s quit' }
)

function Get-PgServiceName {
  $s = Get-Service postgresql* -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($s) { return $s.Name }
  return $null
}

function Assert-CorePrereq {
  $missing = @()
  foreach ($p in @($venvPy, "$stack\redis\redis-server.exe", "$stack\nginx\nginx.exe")) {
    if (-not (Test-Path $p)) { $missing += $p }
  }
  if ($missing.Count -gt 0) {
    Write-Error ("فایل‌های ناقص: " + ($missing -join ', ') + " — ابتدا install-rose-prereq.ps1 و install-rose-app.ps1 را اجرا کنید.")
    exit 1
  }
}

# ------------------------- نصب با NSSM -------------------------
function Install-Nssm($svc) {
  if (-not (Get-Service $svc.Name -ErrorAction SilentlyContinue)) {
    if ($svc.Args) { & $nssm install $svc.Name $svc.App $svc.Args | Out-Null }
    else { & $nssm install $svc.Name $svc.App | Out-Null }
  }
  & $nssm set $svc.Name AppDirectory $svc.Dir | Out-Null
  & $nssm set $svc.Name AppStdout "$stack\logs\$($svc.Name).out.log" | Out-Null
  & $nssm set $svc.Name AppStderr "$stack\logs\$($svc.Name).err.log" | Out-Null
  & $nssm set $svc.Name AppRotateOnline 1 | Out-Null
  & $nssm set $svc.Name AppRotateBytes 10485760 | Out-Null
  & $nssm set $svc.Name Start SERVICE_AUTO_START | Out-Null
  $extra = foreach ($k in $envPairs.Keys) { "$k=$($envPairs[$k])" }
  & $nssm set $svc.Name AppEnvironmentExtra $extra | Out-Null
  if ($svc.Deps.Count -gt 0) { & $nssm set $svc.Name DependOnService ($svc.Deps -join ' ') | Out-Null }
}

# ------------------------- نصب با WinSW -------------------------
function Install-Winsw($svc) {
  $dir = "$winswDir\$($svc.Name)"
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $exe = "$dir\$($svc.Name).exe"
  $xmlPath = "$dir\$($svc.Name).xml"

  $envXml = foreach ($k in $envPairs.Keys) {
    '  <env name="' + (Escape-Xml $k) + '" value="' + (Escape-Xml ([string]$envPairs[$k])) + '"/>'
  }
  $depXml = foreach ($d in $svc.Deps) { '  <depend>' + (Escape-Xml $d) + '</depend>' }
  $stopXml = ''
  if ($svc.StopExe) {
    $stopXml = '  <stopexecutable>' + (Escape-Xml $svc.StopExe) + "</stopexecutable>`r`n" +
               '  <stoparguments>' + (Escape-Xml $svc.StopArgs) + "</stoparguments>`r`n"
  }
  $xml = '<?xml version="1.0" encoding="utf-8"?>' + "`r`n" +
    "<service>`r`n" +
    '  <id>' + (Escape-Xml $svc.Name) + "</id>`r`n" +
    '  <name>Rose Attendance ' + (Escape-Xml $svc.Name) + "</name>`r`n" +
    '  <description>Rose Attendance - ' + (Escape-Xml $svc.Name) + "</description>`r`n" +
    '  <executable>' + (Escape-Xml $svc.App) + "</executable>`r`n" +
    '  <arguments>' + (Escape-Xml $svc.Args) + "</arguments>`r`n" +
    '  <workingdirectory>' + (Escape-Xml $svc.Dir) + "</workingdirectory>`r`n" +
    "  <startmode>Automatic</startmode>`r`n" +
    $stopXml +
    '  <logpath>' + (Escape-Xml "$stack\logs") + "</logpath>`r`n" +
    '  <log mode="roll-by-size">' + "`r`n" +
    "    <sizeThreshold>10485760</sizeThreshold>`r`n" +
    "    <keepFiles>8</keepFiles>`r`n" +
    "  </log>`r`n" +
    '  <onfailure action="restart" delay="10 sec"/>' + "`r`n" +
    ($depXml -join "`r`n") + "`r`n" +
    ($envXml -join "`r`n") + "`r`n" +
    "</service>`r`n"

  $svcExists = [bool](Get-Service $svc.Name -ErrorAction SilentlyContinue)
  $needInstall = $false
  if ($svcExists) {
    $oldXml = ''
    if (Test-Path $xmlPath) { $oldXml = [System.IO.File]::ReadAllText($xmlPath) }
    if ($oldXml -ne $xml) { $needInstall = $true }
  }
  if ($needInstall) {
    Write-Host ("     به‌روزرسانی پیکربندی سرویس " + $svc.Name + " ...")
    & sc.exe stop $svc.Name | Out-Null
    $waited = 0
    while ($waited -lt 20) {
      $st = (Get-Service $svc.Name -ErrorAction SilentlyContinue)
      if (-not $st -or $st.Status -eq 'Stopped') { break }
      Start-Sleep -Seconds 1
      $waited++
    }
    Start-Sleep -Seconds 1
    & $exe uninstall | Out-Null
    $waited = 0
    while ($waited -lt 10) {
      if (-not (Get-Service $svc.Name -ErrorAction SilentlyContinue)) { break }
      Start-Sleep -Seconds 1
      $waited++
    }
    Start-Sleep -Seconds 1
  }
  if ($needInstall -or -not (Test-Path $exe)) { Copy-Item $winswExe $exe -Force }
  [System.IO.File]::WriteAllText($xmlPath, $xml, (New-Object System.Text.UTF8Encoding($false)))
  if (-not (Get-Service $svc.Name -ErrorAction SilentlyContinue)) {
    & $exe install | Out-Null
  }
}

function Install-One($svc) {
  if ($script:SvcTool -eq 'nssm') { Install-Nssm $svc } else { Install-Winsw $svc }
}

# ------------------------- PostgreSQL (سرویس اختیاری — -WithPostgres) -------------------------
function Resolve-PostgresPaths {
  $script:RosePgBin = $PostgresBin
  $script:RosePgData = $PostgresData
  if (-not $script:RosePgBin) {
    $cands = @()
    if (Test-Path "$stack\stack-env.ps1") {
      try { . "$stack\stack-env.ps1" } catch { }
      if ($RosePsql) { $cands += (Split-Path $RosePsql -Parent) }
    }
    $cands += 'C:\rosepsy\runtime\pgsql\bin'
    $cands += 'C:\Program Files\PostgreSQL\16\bin'
    foreach ($c in $cands) {
      if ($c -and (Test-Path (Join-Path $c 'postgres.exe'))) { $script:RosePgBin = $c; break }
    }
  }
  if (-not $script:RosePgData) {
    try {
      $procs = Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue
      foreach ($p in $procs) {
        if ($p.CommandLine -match '-D\s+"?([^"\s]+)"?') { $script:RosePgData = $Matches[1]; break }
      }
    } catch { }
  }
  if (-not $script:RosePgData) {
    foreach ($d in @('C:\rosepsy\data\pgdata', 'C:\rosepsy\data')) {
      if (Test-Path (Join-Path $d 'PG_VERSION')) { $script:RosePgData = $d; break }
    }
  }
  if (-not $script:RosePgBin -or -not $script:RosePgData) { return $false }
  return (Test-Path (Join-Path $script:RosePgData 'PG_VERSION'))
}

function Install-PostgresService {
  if (-not (Resolve-PostgresPaths)) {
    Write-Warning 'با -WithPostgres مسیر PostgreSQL یافت نشد — سرویس RosePostgres ساخته نشد.'
    return $false
  }
  $pgBin = $script:RosePgBin
  $pgData = $script:RosePgData
  Write-Host ("   PostgreSQL bin : " + $pgBin)
  Write-Host ("   PostgreSQL data: " + $pgData)

  $pgSvc = Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($pgSvc) {
    Write-Host ("   PostgreSQL سرویس ویندوزی خودش را دارد: " + $pgSvc.Name + " — RosePostgres ساخته نمی‌شود.")
    return $false
  }
  if ($script:SvcTool -ne 'winsw') {
    Write-Warning 'سرویس RosePostgres فقط با WinSW پشتیبانی می‌شود — رد شد.'
    return $false
  }

  $svcName = 'RosePostgres'
  $dir = "$winswDir\$svcName"
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $exe = "$dir\$svcName.exe"
  $xmlPath = "$dir\$svcName.xml"
  $xml = '<?xml version="1.0" encoding="utf-8"?>' + "`r`n" +
    "<service>`r`n" +
    '  <id>RosePostgres</id>' + "`r`n" +
    '  <name>Rose Attendance PostgreSQL</name>' + "`r`n" +
    '  <description>Rose Attendance - PostgreSQL (local rosepsy instance)</description>' + "`r`n" +
    '  <executable>' + (Escape-Xml (Join-Path $pgBin 'postgres.exe')) + '</executable>' + "`r`n" +
    '  <arguments>-D "' + (Escape-Xml $pgData) + '"</arguments>' + "`r`n" +
    '  <workingdirectory>' + (Escape-Xml $pgBin) + '</workingdirectory>' + "`r`n" +
    '  <startmode>Automatic</startmode>' + "`r`n" +
    '  <stopexecutable>' + (Escape-Xml (Join-Path $pgBin 'pg_ctl.exe')) + '</stopexecutable>' + "`r`n" +
    '  <stoparguments>-D "' + (Escape-Xml $pgData) + '" -m fast stop</stoparguments>' + "`r`n" +
    '  <serviceaccount>' + "`r`n" +
    '    <domain>NT AUTHORITY</domain>' + "`r`n" +
    '    <user>NetworkService</user>' + "`r`n" +
    '  </serviceaccount>' + "`r`n" +
    '  <logpath>' + (Escape-Xml "$stack\logs") + '</logpath>' + "`r`n" +
    '  <log mode="roll-by-size">' + "`r`n" +
    '    <sizeThreshold>10485760</sizeThreshold>' + "`r`n" +
    '    <keepFiles>8</keepFiles>' + "`r`n" +
    '  </log>' + "`r`n" +
    '  <onfailure action="restart" delay="10 sec"/>' + "`r`n" +
    '</service>' + "`r`n"

  # دسترسی NetworkService به datadir و پوشه لاگ‌ها (اگر نباشد postgres شروع نمی‌شود)
  & icacls $pgData /grant '*S-1-5-20:(OI)(CI)F' /T | Out-Null
  & icacls "$stack\logs" /grant '*S-1-5-20:(OI)(CI)F' | Out-Null

  [System.IO.File]::WriteAllText($xmlPath, $xml, (New-Object System.Text.UTF8Encoding($false)))
  $svcObj = Get-Service $svcName -ErrorAction SilentlyContinue
  if (-not $svcObj -or $svcObj.Status -ne 'Running') { Copy-Item $winswExe $exe -Force }
  if (-not (Get-Service $svcName -ErrorAction SilentlyContinue)) {
    & $exe install | Out-Null
  }
  Write-Host '   سرویس RosePostgres نصب شد.' -ForegroundColor Green
  return $true
}

function Stop-ManualPostgres {
  try {
    $portBusy = Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $portBusy) { return }
    Write-Host '   توقف نمونه دستی PostgreSQL برای تحویل به سرویس RosePostgres ...'
    & (Join-Path $script:RosePgBin 'pg_ctl.exe') -D $script:RosePgData -m fast stop 2>$null | Out-Null
    Start-Sleep -Seconds 3
  } catch { }
}

function Show-ServiceLogTail([string]$Name, [int]$Lines = 12) {
  foreach ($f in @("$stack\logs\$Name.err.log", "$stack\logs\$Name.out.log", "$stack\logs\$Name.wrapper.log")) {
    if (Test-Path $f) {
      Write-Host ("     --- آخرین لاگ: " + $f + " ---") -ForegroundColor DarkGray
      Get-Content $f -Tail $Lines -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ("     " + $_) -ForegroundColor DarkGray }
      break
    }
  }
}

# ================================ InstallServices ================================
if ($InstallServices) {
  Assert-CorePrereq
  Write-Host '== نصب و شروع سرویس‌های ویندوزی رز سفید ==' -ForegroundColor Cyan

  $script:SvcTool = Get-ServiceTool
  if (-not $script:SvcTool) {
    if (Ensure-WinSW) { $script:SvcTool = 'winsw' }
    else {
      Write-Error 'نه NSSM و نه WinSW در دسترس نیست و دانلود WinSW هم ناموفق بود — اتصال اینترنت را بررسی کنید یا nssm.exe را دستی در C:\rose-stack\nssm بگذارید.'
      exit 1
    }
  }
  Write-Host ("   مدیر سرویس: " + $script:SvcTool)

  # سرویس PostgreSQL (اختیاری — -WithPostgres): استارت خودکار پس از بوت
  if ($WithPostgres) {
    Write-Host '   سرویس PostgreSQL (RosePostgres) ...'
    $pgReady = Install-PostgresService
    if ($pgReady) { Stop-ManualPostgres }
  }

  # وابستگی RoseApi به سرویس PostgreSQL (اگر سرویس آن پیدا شود)
  $pgName = Get-PgServiceName
  if ($pgName) {
    Write-Host ("   سرویس PostgreSQL: " + $pgName)
    $services[1].Deps = @('RoseRedis', $pgName)
  }

  New-Item -ItemType Directory -Force -Path "$stack\logs" | Out-Null
  foreach ($svc in $services) {
    Write-Host ("   نصب سرویس " + $svc.Name + " ...")
    Install-One $svc
  }

  $startOrder = @()
  if (Get-Service RosePostgres -ErrorAction SilentlyContinue) { $startOrder += 'RosePostgres' }
  $startOrder += @('RoseRedis', 'RoseApi', 'RoseWorker', 'RoseBeat', 'RoseNginx')
  foreach ($name in $startOrder) {
    try { Start-Service $name -ErrorAction Stop; Write-Host ("   شروع شد: " + $name) -ForegroundColor Green }
    catch {
      Write-Warning ("شروع " + $name + " ناموفق: " + $_.Exception.Message)
      Show-ServiceLogTail $name
      if ($name -eq 'RosePostgres') {
        Write-Host '     سرویس RosePostgres حذف و PostgreSQL به‌صورت دستی روشن می‌شود ...' -ForegroundColor Yellow
        if (-not $script:RosePgBin -or -not $script:RosePgData) { Resolve-PostgresPaths | Out-Null }
        & sc.exe delete RosePostgres | Out-Null
        & (Join-Path $script:RosePgBin 'pg_ctl.exe') -D $script:RosePgData -w start 2>$null | Out-Null
      }
    }
  }
  Start-Sleep -Seconds 5
  Get-Service RoseRedis, RoseApi, RoseWorker, RoseBeat, RoseNginx -ErrorAction SilentlyContinue |
    Format-Table Name, Status, StartType -AutoSize
  Write-Host ''
  Write-Host "وب‌اپ     : http://130.185.73.157:$RoseWebPort/" -ForegroundColor Green
  Write-Host "پنل ادمین : http://130.185.73.157:$RoseWebPort/admin/" -ForegroundColor Green
  Write-Host "سلامت API : http://130.185.73.157:$RoseWebPort/api/v1/health/" -ForegroundColor Green
  Write-Host "API مستقیم : http://130.185.73.157:$RoseApiPort/api/v1/health/" -ForegroundColor Green
  Write-Host ("لاگ‌ها     : " + $stack + "\logs\")
  return
}

# ================================ UninstallServices ================================
if ($UninstallServices) {
  Write-Host '== حذف سرویس‌های رز سفید ==' -ForegroundColor Cyan
  foreach ($name in @('RosePostgres', 'RoseNginx', 'RoseBeat', 'RoseWorker', 'RoseApi', 'RoseRedis')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s) {
      if ($s.Status -eq 'Running') { Stop-Service $name -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
      & sc.exe delete $name | Out-Null
      Write-Host ("   حذف شد: " + $name)
    }
  }
  return
}

# ================================ Stop ================================
if ($Stop) {
  foreach ($name in @('RosePostgres', 'RoseNginx', 'RoseBeat', 'RoseWorker', 'RoseApi', 'RoseRedis')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s -and $s.Status -eq 'Running') { Stop-Service $name -Force -ErrorAction SilentlyContinue; Write-Host ("   متوقف شد: " + $name) }
  }
  return
}

# ================================ Start / Restart ================================
if ($Start -or $Restart) {
  if ($Restart) { & $PSCommandPath -Stop | Out-Null; Start-Sleep -Seconds 3 }
  foreach ($name in @('RosePostgres', 'RoseRedis', 'RoseApi', 'RoseWorker', 'RoseBeat', 'RoseNginx')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s) { try { Start-Service $name -ErrorAction Stop; Write-Host ("   شروع شد: " + $name) -ForegroundColor Green } catch { Write-Warning "$name : $($_.Exception.Message)" } }
  }
  return
}

# ================================ Status ================================
if ($Status) {
  Write-Host '== وضعیت سرویس‌ها ==' -ForegroundColor Cyan
  Get-Service Rose* -ErrorAction SilentlyContinue | Format-Table Name, Status, StartType -AutoSize
  Write-Host '== وضعیت پورت‌ها ==' -ForegroundColor Cyan
  foreach ($port in @($RoseApiPort, $RoseWebPort, 6379, 5432)) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
      $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      Write-Host ("   پورت $port : گوش می‌دهد (" + $p.ProcessName + ")")
    } else {
      Write-Host ("   پورت $port : بسته است")
    }
  }
  Write-Host ''
  Write-Host "تست سلامت:  curl http://127.0.0.1:$RoseWebPort/api/v1/health/"
  return
}

# ================================ Console ================================
if ($Console) {
  Assert-CorePrereq
  Write-Host '== اجرای موقت در پنجره‌های کنسول (برای تست) ==' -ForegroundColor Cyan
  $r = Get-Service RoseRedis -ErrorAction SilentlyContinue
  if ($r -and $r.Status -eq 'Running') { Write-Host '   Redis: سرویس در حال اجرا' }
  else { Start-Process -WorkingDirectory "$stack\redis" -FilePath "$stack\redis\redis-server.exe" -ArgumentList "$stack\redis\redis.conf"; Write-Host '   Redis: در پنجره جدا اجرا شد' }
  Start-Sleep -Seconds 2
  $jobs = @(
    @{ Title='RoseApi';    Cmd="-m daphne -b 0.0.0.0 -p $RoseApiPort config.asgi:application" },
    @{ Title='RoseWorker'; Cmd='-m celery -A config worker --pool=solo --loglevel=INFO --without-gossip --without-mingle' },
    @{ Title='RoseBeat';   Cmd="-m celery -A config beat --loglevel=INFO --schedule=$stack\celerybeat-schedule" }
  )
  foreach ($j in $jobs) {
    $arg = "/k title $($j.Title) && call `"$envCmd`" && cd /d `"$backend`" && `"$venvPy`" $($j.Cmd)"
    Start-Process -FilePath 'cmd.exe' -ArgumentList $arg
    Write-Host ("   " + $j.Title + ": پنجره کنسول باز شد")
  }
  Start-Process -WorkingDirectory "$stack\nginx" -FilePath "$stack\nginx\nginx.exe"
  Write-Host '   Nginx: اجرا شد (برای توقف: C:\rose-stack\nginx\nginx.exe -s quit)'
  Write-Host ''
  Write-Host "وب‌اپ     : http://130.185.73.157:$RoseWebPort/" -ForegroundColor Green
  Write-Host "سلامت API : http://130.185.73.157:$RoseWebPort/api/v1/health/" -ForegroundColor Green
  Write-Host 'برای توقف کامل: پنجره‌ها را ببندید + nginx -s quit'
  return
}

# بدون پارامتر — راهنما
Write-Host 'استفاده: run-rose.ps1 -InstallServices [-WithPostgres] | -Console | -Status | -Start | -Stop | -Restart | -UninstallServices'

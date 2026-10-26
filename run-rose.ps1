#Requires -Version 5.1
<#
.SYNOPSIS
  مدیریت اجرای سامانه رز سفید بدون Docker: سرویس‌های ویندوزی یا پنجره‌های کنسول.

.DESCRIPTION
  سرویس‌ها: RoseRedis → RoseApi (Daphne/ASGI روی 8000) → RoseWorker / RoseBeat (Celery)
  و RoseNginx (پورت 8080 — سرو فرانت‌اند + پروکسی API و WebSocket).

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
  [switch]$Status
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$stack = 'C:\rose-stack'
$repo  = 'C:\rose-attendance'
$backend = "$repo\backend"
$nssm = "$stack\nssm\nssm.exe"
$venvPy = "$stack\venv\Scripts\python.exe"
$envFile = "$stack\rose-backend.env"
$envCmd = "$stack\rose-backend-env.cmd"

# خواندن env
$envPairs = [ordered]@{}
if (Test-Path $envFile) {
  foreach ($line in (Get-Content $envFile)) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $envPairs[$Matches[1]] = $Matches[2] }
  }
} else {
  Write-Error "فایل $envFile یافت نشد — ابتدا install-rose-app.ps1 را اجرا کنید."
  exit 1
}

$services = @(
  [pscustomobject]@{ Name='RoseRedis';  App="$stack\redis\redis-server.exe";  Args="$stack\redis\redis.conf"; Dir="$stack\redis" },
  [pscustomobject]@{ Name='RoseApi';    App=$venvPy; Args='-m daphne -b 0.0.0.0 -p 8000 config.asgi:application'; Dir=$backend },
  [pscustomobject]@{ Name='RoseWorker'; App=$venvPy; Args='-m celery -A config worker --pool=solo --loglevel=INFO --without-gossip --without-mingle'; Dir=$backend },
  [pscustomobject]@{ Name='RoseBeat';   App=$venvPy; Args="-m celery -A config beat --loglevel=INFO --schedule=$stack\celerybeat-schedule"; Dir=$backend },
  [pscustomobject]@{ Name='RoseNginx';  App="$stack\nginx\nginx.exe"; Args=''; Dir="$stack\nginx" }
)

function Assert-Prereq {
  $missing = @()
  foreach ($p in @($nssm, $venvPy, "$stack\redis\redis-server.exe", "$stack\nginx\nginx.exe")) {
    if (-not (Test-Path $p)) { $missing += $p }
  }
  if ($missing.Count -gt 0) {
    Write-Error ("فایل‌های ناقص: " + ($missing -join ', ') + " — ابتدا install-rose-prereq.ps1 و install-rose-app.ps1 را اجرا کنید.")
    exit 1
  }
}

function Install-One($svc) {
  $exists = Get-Service $svc.Name -ErrorAction SilentlyContinue
  if (-not $exists) {
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
}

function Get-PgServiceName {
  $s = Get-Service postgresql* -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($s) { return $s.Name }
  return $null
}

if ($InstallServices) {
  Assert-Prereq
  Write-Host '== نصب و شروع سرویس‌های ویندوزی رز سفید ==' -ForegroundColor Cyan
  foreach ($svc in $services) {
    Write-Host ("   نصب سرویس " + $svc.Name + " ...")
    Install-One $svc
  }
  # وابستگی شروع (پس از دیتابیس و Redis)
  $pgName = Get-PgServiceName
  if ($pgName) { & $nssm set RoseApi DependOnService RoseRedis $pgName | Out-Null }
  else { & $nssm set RoseApi DependOnService RoseRedis | Out-Null }
  & $nssm set RoseWorker DependOnService RoseRedis | Out-Null
  & $nssm set RoseBeat DependOnService RoseRedis | Out-Null

  foreach ($name in @('RoseRedis', 'RoseApi', 'RoseWorker', 'RoseBeat', 'RoseNginx')) {
    try { Start-Service $name -ErrorAction Stop; Write-Host ("   شروع شد: " + $name) -ForegroundColor Green }
    catch { Write-Warning ("شروع " + $name + " ناموفق: " + $_.Exception.Message) }
  }
  Start-Sleep -Seconds 5
  & $nssm status RoseRedis; & $nssm status RoseApi; & $nssm status RoseWorker; & $nssm status RoseBeat; & $nssm status RoseNginx
  Write-Host ''
  Write-Host 'وب‌اپ    : http://130.185.73.157:8080/' -ForegroundColor Green
  Write-Host 'سلامت API : http://130.185.73.157:8080/api/v1/health/' -ForegroundColor Green
  Write-Host ("لاگ‌ها    : " + $stack + "\logs\")
  return
}

if ($UninstallServices) {
  Write-Host '== حذف سرویس‌های رز سفید ==' -ForegroundColor Cyan
  foreach ($name in @('RoseNginx', 'RoseBeat', 'RoseWorker', 'RoseApi', 'RoseRedis')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s) {
      try { & $nssm stop $name | Out-Null } catch { }
      Start-Sleep -Seconds 2
      & $nssm remove $name confirm | Out-Null
      Write-Host ("   حذف شد: " + $name)
    }
  }
  return
}

if ($Stop) {
  foreach ($name in @('RoseNginx', 'RoseBeat', 'RoseWorker', 'RoseApi', 'RoseRedis')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s -and $s.Status -eq 'Running') { & $nssm stop $name | Out-Null; Write-Host ("   متوقف شد: " + $name) }
  }
  return
}

if ($Start -or $Restart) {
  if ($Restart) { & $MyInvocation.MyCommand.Path -Stop | Out-Null; Start-Sleep -Seconds 3 }
  foreach ($name in @('RoseRedis', 'RoseApi', 'RoseWorker', 'RoseBeat', 'RoseNginx')) {
    $s = Get-Service $name -ErrorAction SilentlyContinue
    if ($s) { try { Start-Service $name -ErrorAction Stop; Write-Host ("   شروع شد: " + $name) -ForegroundColor Green } catch { Write-Warning "$name : $($_.Exception.Message)" } }
  }
  return
}

if ($Status) {
  Write-Host '== وضعیت سرویس‌ها ==' -ForegroundColor Cyan
  Get-Service Rose* -ErrorAction SilentlyContinue | Format-Table Name, Status, StartType -AutoSize
  Write-Host '== وضعیت پورت‌ها ==' -ForegroundColor Cyan
  foreach ($port in @(8000, 8080, 6379, 5432)) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
      $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      Write-Host ("   پورت $port : گوش می‌دهد (" + $p.ProcessName + ")")
    } else {
      Write-Host ("   پورت $port : بسته است")
    }
  }
  Write-Host ''
  Write-Host 'تست سلامت:  curl http://127.0.0.1:8080/api/v1/health/'
  return
}

if ($Console) {
  Assert-Prereq
  Write-Host '== اجرای موقت در پنجره‌های کنسول (برای تست) ==' -ForegroundColor Cyan
  # Redis
  $r = Get-Service RoseRedis -ErrorAction SilentlyContinue
  if ($r -and $r.Status -eq 'Running') { Write-Host '   Redis: سرویس در حال اجرا' }
  else { Start-Process -WorkingDirectory "$stack\redis" -FilePath "$stack\redis\redis-server.exe" -ArgumentList "$stack\redis\redis.conf"; Write-Host '   Redis: در پنجره جدا اجرا شد' }
  Start-Sleep -Seconds 2
  # بک‌اند
  $jobs = @(
    @{ Title='RoseApi';    Cmd='-m daphne -b 0.0.0.0 -p 8000 config.asgi:application' },
    @{ Title='RoseWorker'; Cmd='-m celery -A config worker --pool=solo --loglevel=INFO --without-gossip --without-mingle' },
    @{ Title='RoseBeat';   Cmd="-m celery -A config beat --loglevel=INFO --schedule=$stack\celerybeat-schedule" }
  )
  foreach ($j in $jobs) {
    $arg = "/k title $($j.Title) && call `"$envCmd`" && cd /d `"$backend`" && `"$venvPy`" $($j.Cmd)"
    Start-Process -FilePath 'cmd.exe' -ArgumentList $arg
    Write-Host ("   " + $j.Title + ": پنجره کنسول باز شد")
  }
  # Nginx
  Start-Process -WorkingDirectory "$stack\nginx" -FilePath "$stack\nginx\nginx.exe"
  Write-Host '   Nginx: اجرا شد (برای توقف: C:\rose-stack\nginx\nginx.exe -s quit)'
  Write-Host ''
  Write-Host 'وب‌اپ    : http://130.185.73.157:8080/' -ForegroundColor Green
  Write-Host 'سلامت API : http://130.185.73.157:8080/api/v1/health/' -ForegroundColor Green
  Write-Host 'برای توقف کامل: پنجره‌ها را ببندید + nginx -s quit'
  return
}

# بدون پارامتر — راهنما
Write-Host 'استفاده: run-rose.ps1 -InstallServices | -Console | -Status | -Start | -Stop | -Restart | -UninstallServices'

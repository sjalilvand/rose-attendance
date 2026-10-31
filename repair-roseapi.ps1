#requires -Version 5.1
<#
  repair-roseapi.ps1 — تشخیص و تعمیر «کد قدیمی» در سرویس RoseApi (تکنورز / پورت 8085)
  مشکل: دیسک C:\rose-attendance به‌روز است ولی Django در حال اجرا endpointهای جدید را 404 می‌دهد.
  حالت تشخیص:   powershell -ExecutionPolicy Bypass -File C:\repair-roseapi.ps1
  حالت تعمیر:   powershell -ExecutionPolicy Bypass -File C:\repair-roseapi.ps1 -Fix
#>
param([switch]$Fix)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Backend = 'C:\rose-attendance\backend'
$Port    = 3005
$Stack   = 'C:\rose-stack'
$Nssm    = Join-Path $Stack 'nssm\nssm.exe'
$EnvFile = Join-Path $Stack 'rose-backend.env'

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "  [!]    $m" -ForegroundColor Yellow }
function Write-Err2 { param($m) Write-Host "  [X]    $m" -ForegroundColor Red }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Warn2 'این پنجره ادمین نیست — حالت -Fix به دسترسی ادمین نیاز دارد.' }

# ---------- ۱) تعریف سرویس RoseApi ----------
Write-Step '۱/۵ تعریف سرویس RoseApi (از رجیستری)'
$svc = Get-CimInstance Win32_Service -Filter "Name='RoseApi'" -ErrorAction SilentlyContinue
if (-not $svc) { Write-Err2 "سرویس RoseApi پیدا نشد! (PathName: $((Get-CimInstance Win32_Service -Filter `"Name LIKE 'Rose%'`" -EA SilentlyContinue | Select-Object -Expand PathName) -join ' | '))"; return }
Write-Host ("   ImagePath : " + $svc.PathName)
Write-Host ("   State     : " + $svc.State + "   ProcessId: " + $svc.ProcessId)

$svcApp = $null; $svcDir = $null; $svcArgs = $null
$rp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\RoseApi\Parameters' -ErrorAction SilentlyContinue
if ($rp) {
    $svcApp  = $rp.Application
    $svcDir  = $rp.AppDirectory
    $svcArgs = $rp.AppParameters
    Write-Host ("   Application(nssm)   : " + $svcApp)
    Write-Host ("   AppDirectory(nssm)  : " + $svcDir)
    Write-Host ("   AppParameters(nssm) : " + $svcArgs)
} else {
    Write-Warn2 'کلید Parametersی nssm پیدا نشد — سرویس احتمالاً nssm نیست.'
}

# ---------- ۲) کد روی دیسک ----------
Write-Step '۲/۵ بررسی کد روی دیسک'
$dirToCheck = $svcDir
if (-not $dirToCheck -or -not (Test-Path $dirToCheck)) { $dirToCheck = $Backend }
Write-Host ("   پوشهٔ بررسی‌شونده: " + $dirToCheck)

if (Test-Path (Join-Path $dirToCheck '.git')) {
    $head = & git -C $dirToCheck log -1 --oneline 2>$null
    Write-Host ("   git HEAD : " + $head)
}
$urlsFile = Join-Path $dirToCheck 'config\urls.py'
if (Test-Path $urlsFile) {
    $has = Select-String -Path $urlsFile -Pattern 'sync-from-hub' -Quiet
    if ($has) { Write-Ok 'config/urls.py این پوشه شامل endpoint جدید sync-from-hub است' }
    else      { Write-Err2 'config/urls.py این پوشه endpoint جدید را ندارد = کپی قدیمی کد!' }
} else {
    Write-Err2 "config\urls.py در این پوشه نیست: $urlsFile"
}

$backendOk = (Test-Path (Join-Path $Backend 'manage.py'))
$dirMismatch = $false
if ($svcDir) {
    try { $dirMismatch = ((Resolve-Path $svcDir -EA SilentlyContinue).Path -ne (Resolve-Path $Backend -EA SilentlyContinue).Path) } catch { $dirMismatch = $true }
}
if ($dirMismatch) {
    Write-Err2 "AppDirectory سرویس («$svcDir») با مسیر پروژهٔ به‌روز («$Backend») متفاوت است = علت ریشه‌ای نوع A"
}

# ---------- ۳) پروسهٔ گوش‌دهنده روی پورت 3005 ----------
Write-Step '۳/۵ پروسه‌های گوش‌دهنده روی پورت 3005'
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) { Write-Warn2 "هیچ پروسه‌ای روی پورت $Port گوش نمی‌دهد (API از بیرون چطور جواب می‌داد؟)" }
foreach ($c in ($conns | Sort-Object OwningProcess -Unique)) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    if ($p) {
        $cl = $p.CommandLine; if ($cl -and $cl.Length -gt 160) { $cl = $cl.Substring(0,160) + '…' }
        Write-Host ("   PID " + $p.ProcessId + "  " + $p.Name + "  شروع: " + $p.CreationDate)
        Write-Host ("     Cmd: " + $cl)
    }
}

# ---------- ۴) تست مستقیم API ----------
function Invoke-Probe([string]$Url) {
    $bodyFile = Join-Path $env:TEMP 'roseapi_body.txt'
    $code = & curl.exe -s -s -o $bodyFile -w '%{http_code}' -m 8 -X POST $Url -H 'Content-Type: application/json' -d '{}'
    $body = ''
    if (Test-Path $bodyFile) { $body = (Get-Content $bodyFile -Raw -ErrorAction SilentlyContinue); if ($body) { $body = ($body -replace '\s+', ' ') } }
    if ($body -and $body.Length -gt 120) { $body = $body.Substring(0,120) + '…' }
    return @{ Code = "$code"; Body = $body }
}
function Show-Verdict($p, [string]$label) {
    Write-Host ("   " + $label + "  ->  HTTP " + $p.Code + "   " + $p.Body)
    if ($p.Code -eq '404') { Write-Err2 'پروسهٔ در حال اجرا endpoint جدید را ندارد = کد قدیمی' ; return 'old' }
    if ($p.Code -eq '000') { Write-Err2 'API روی این آدرس پاسخ نمی‌دهد' ; return 'dead' }
    Write-Ok 'endpoint جدید در پروسهٔ در حال اجرا موجود است (کد جدید لود شده)' ; return 'new'
}

Write-Step '۴/۵ تست مستقیم endpoint جدید (بدون nginx)'
$r1 = Invoke-Probe "http://127.0.0.1:$Port/api/v1/auth/profile/sync-from-hub/"
$v1 = Show-Verdict $r1 'daphne مستقیم (3005)'

# ---------- ۵) تعمیر ----------
if (-not $Fix) {
    Write-Step '۵/۵ حالت تعمیر اجرا نشد (پرچم -Fix داده نشد)'
    if ($v1 -eq 'old') { Write-Warn2 'برای تعمیر خودکار اجرا کنید:  powershell -ExecutionPolicy Bypass -File C:\repair-roseapi.ps1 -Fix' }
    return
}

Write-Step '۵/۵ تعمیر خودکار (Fix)'

# 5-الف: توقف سرویس
$nssmOk = (Test-Path $Nssm)
try {
    if ($nssmOk) { & $Nssm stop RoseApi 2>&1 | Out-Null } else { Stop-Service RoseApi -Force -ErrorAction SilentlyContinue }
    Write-Ok 'سرویس RoseApi متوقف شد'
} catch { Write-Warn2 ("توقف سرویس: " + $_.Exception.Message) }
Start-Sleep -Seconds 3

# 5-ب: کشتن پروسه‌های سرگردانی روی 3005
$strays = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Sort-Object OwningProcess -Unique
foreach ($c in $strays) {
    try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
        Write-Ok ("پروسهٔ قدیمی روی پورت $Port کشته شد (PID $($c.OwningProcess))")
    } catch { Write-Warn2 ("کشتن PID $($c.OwningProcess): " + $_.Exception.Message) }
}
Start-Sleep -Seconds 2
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Warn2 "پورت $Port هنوز اشغال است — پروسهٔ مقاوم؛ یک بار دیگر اسکریپت را اجرا کنید."
}

# 5-ج: اصلاح AppDirectory در صورت مغایرت
if ($dirMismatch -and $backendOk) {
    if ($nssmOk) {
        & $Nssm set RoseApi AppDirectory $Backend 2>&1 | Out-Null
        Write-Ok ("AppDirectory سرویس به مسیر درست تغییر کرد: " + $Backend)
    } else { Write-Warn2 'nssm پیدا نشد — AppDirectory دستی اصلاح نشد' }
}

# 5-د: مایگریشن با پایتون همان سرویس + متغیرهای محیطی rose-backend.env
$py = $svcApp
if (-not $py -or -not (Test-Path $py)) { $py = Join-Path $Stack 'venv\Scripts\python.exe' }
if ($backendOk -and (Test-Path $py)) {
    if (Test-Path $EnvFile) {
        Get-Content $EnvFile | ForEach-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
                $k = $Matches[1]; $v = $Matches[2].Trim().Trim('"')
                try { Set-Item -Path ("Env:" + $k) -Value $v -ErrorAction SilentlyContinue } catch { }
            }
        }
    }
    Write-Step 'مایگریشن دیتابیس (manage.py migrate) با پایتون سرویس'
    Push-Location $Backend
    try {
        $out = & $py manage.py migrate --noinput 2>&1
        $tail = ($out | Select-Object -Last 6) -join ' | '
        Write-Host ("   " + $tail)
        if ($LASTEXITCODE -eq 0) { Write-Ok 'مایگریشن‌ها اعمال شد' } else { Write-Warn2 'migrate کد خطا داد — خروجی بالا را برای من بفرستید' }
    } finally { Pop-Location }
} else {
    Write-Warn2 'مایگریشن رد شد (manage.py یا python سرویس پیدا نشد)'
}

# 5-ه: شروع دوبارهٔ سرویس
try {
    if ($nssmOk) { & $Nssm start RoseApi 2>&1 | Out-Null } else { Start-Service RoseApi -ErrorAction Stop }
    Write-Ok 'سرویس RoseApi شروع شد'
} catch { Write-Err2 ("شروع سرویس: " + $_.Exception.Message) }

$healthy = $false
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 1
    $code = & curl.exe -s -o NUL -w '%{http_code}' -m 3 "http://127.0.0.1:$Port/api/v1/health/" 2>$null
    if ("$code" -eq '200') { $healthy = $true; break }
}
if ($healthy) { Write-Ok ("سرویس روی پورت $Port سالم بالا آمد (تلاش $i)") } else { Write-Err2 'سرویس بعد از ۲۵ ثانیه health نداد — لاگ nssm را ببینید' }

Write-Step 'تأیید نهایی'
$r2 = Invoke-Probe "http://127.0.0.1:$Port/api/v1/auth/profile/sync-from-hub/"
$v2 = Show-Verdict $r2 'daphne مستقیم (3005)'
$r3 = Invoke-Probe 'http://127.0.0.1:8085/api/v1/auth/profile/sync-from-hub/'
$v3 = Show-Verdict $r3 'از طریق nginx (8085)'

Write-Host ''
if ($v2 -ne 'old' -and $v3 -ne 'old') {
    Write-Host '=================================================================' -ForegroundColor Cyan
    Write-Host '  تعمیر موفق بود — حالا در مرورگر:' -ForegroundColor Cyan
    Write-Host '    ۱) صفحهٔ پروفایل تکنورز (8085/profile) را با Ctrl+F5 رفرش کنید'
    Write-Host '       — self-heal روی /me خودش مشخصات را از رز هاب می‌کشد'
    Write-Host '    ۲) یا دکمهٔ «به‌روزرسانی از رز هاب» را بزنید'
    Write-Host '=================================================================' -ForegroundColor Cyan
} else {
    Write-Host '  هنوز کد قدیمی در حال اجراست — کل خروجی این اسکریپت را برای من بفرستید.' -ForegroundColor Yellow
}

#Requires -Version 5.1
<#
.SYNOPSIS
  جمع‌آوری کامل مشخصات سرور ویندوز برای استقرار سامانه حضور و غیاب «رز سفید».

.DESCRIPTION
  این اسکریپت اطلاعات زیر را گردآوری و در یک فایل گزارش متنی (و یک JSON خلاصه) ذخیره می‌کند:
    - سیستم‌عامل، سخت‌افزار (CPU/RAM/دیسک)، زمان/منطقه زمانی
    - شبکه: آداپتورها، IP داخلی، IP عمومی، دسترسی اینترنت
    - قابلیت مجازی‌سازی (VT-x)، وضعیت Hyper-V و WSL2
    - وضعیت Docker
    - ویژگی‌های ویندوز (Hyper-V / VirtualMachinePlatform / WSL / Containers / IIS)
    - پورت‌های باز TCP/UDP به همراه پروسه مالک
    - بررسی پورت‌های حیاتی پروژه (80 / 443 / 8080 / 8000 / 5432 / 6379 / 3389 ...)
    - سرویس‌های ویندوزی که ممکن است تداخل ایجاد کنند (IIS, SQL Server, Apache, ...)
    - لیست کامل برنامه‌های نصب‌شده (رجیستری)
    - وضعیت فایروال و Windows Defender
  خروجی فایل متنی را برای بررسی کامل در اختیار کارشناس استقرار قرار دهید.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\server-inventory.ps1
  (PowerShell را حتماً Run as Administrator کنید)
#>

[CmdletBinding()]
param(
  [string]$OutDir = ""
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------- helpers ----
function Strip-Nulls([string]$s) {
  if ($null -eq $s) { return '' }
  return ($s -replace "\x00", '')
}

function YesNo($v) { if ($v) { 'YES' } else { 'NO' } }

function Safe([scriptblock]$block) {
  try { return & $block } catch { return "ERROR: $($_.Exception.Message)" }
}

# آیا با دسترسی Administrator اجرا شده است؟
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host ''
Write-Host '== جمع‌آوری مشخصات سرور برای سامانه رز سفید ==' -ForegroundColor Cyan
if (-not $isAdmin) {
  Write-Warning 'با دسترسی Administrator اجرا نشده است؛ برخی بخش‌ها (ویژگی‌های ویندوز، bcdedit) ناقص خواهند بود. بهتر است PowerShell را Run as Administrator کنید.'
}

# محل خروجی: دسکتاپ کاربر در صورت وجود، وگرنه کنار اسکریپت
if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $desktop = [Environment]::GetFolderPath('Desktop')
  if ($desktop -and (Test-Path $desktop)) { $OutDir = $desktop } else { $OutDir = $PSScriptRoot }
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp    = Get-Date -Format 'yyyyMMdd_HHmmss'
$txtPath  = Join-Path $OutDir ("RoseServerReport_" + $stamp + ".txt")
$jsonPath = Join-Path $OutDir ("RoseServerReport_" + $stamp + ".json")

$sb = New-Object System.Text.StringBuilder
function Add-Line($text = '') { [void]$sb.AppendLine($text) }
function Add-Section($title) {
  Add-Line ''
  Add-Line '=============================================================='
  Add-Line ("  " + $title)
  Add-Line '=============================================================='
}

Write-Host '-- ۱/۹ سیستم‌عامل و سخت‌افزار ...' -ForegroundColor Yellow

# ---------------------------------------------------------------- [A] meta ---
Add-Line 'ROSE ATTENDANCE - WINDOWS SERVER INVENTORY REPORT'
Add-Line ('Generated (UTC)   : ' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))
Add-Line ('Generated (local) : ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Line ('ComputerName      : ' + $env:COMPUTERNAME)
Add-Line ('RunAsAdmin        : ' + (YesNo $isAdmin))

$summary = [ordered]@{}

# ------------------------------------------------------------------- [B] OS --
Add-Section '[B] OPERATING SYSTEM'
$os   = Safe { Get-CimInstance Win32_OperatingSystem }
$cs   = Safe { Get-CimInstance Win32_ComputerSystem }
$ubr  = Safe { (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR }
$disp = Safe { (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion }
Add-Line ("Caption           : " + $os.Caption)
Add-Line ("Version/Build     : " + $os.Version + "  (UBR " + $ubr + ")  DisplayVersion: " + $disp)
Add-Line ("Architecture      : " + $os.OSArchitecture)
Add-Line ("InstallDate       : " + $os.InstallDate)
Add-Line ("LastBoot          : " + $os.LastBootUpTime)
Add-Line ("LocalTime         : " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Line ("TimeZone          : " + (Safe { (Get-TimeZone).Id }))
Add-Line ("Manufacturer      : " + $cs.Manufacturer + " / Model: " + $cs.Model)
Add-Line ("DomainJoined      : " + (YesNo $cs.PartOfDomain) + ("   Domain: " + $cs.Domain))
Add-Line ("Hotfixes (count)  : " + (Safe { (Get-HotFix | Measure-Object).Count }))
Add-Line ("Recent hotfixes   : " + ((Safe { Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 5 -ExpandProperty HotFixID }) -join ', '))
$summary.os_caption = "$($os.Caption)"
$summary.os_build   = "$($os.Version).$ubr"

# ------------------------------------------------------------ [C] hardware ---
Add-Section '[C] HARDWARE (CPU / RAM / DISK)'
$cpu = Safe { Get-CimInstance Win32_Processor | Select-Object -First 1 }
Add-Line ("CPU               : " + $cpu.Name)
Add-Line ("Cores/Threads     : " + $cpu.NumberOfCores + " cores / " + $cpu.NumberOfLogicalProcessors + " threads")
$totalRamGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
$freeRamGB  = [math]::Round($os.FreePhysicalMemory * 1KB / 1GB, 2)
Add-Line ("RAM total/free GB : " + $totalRamGB + " / " + $freeRamGB)
Add-Line ('--- Disks ---')
$disks = Safe { Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" }
foreach ($d in $disks) {
  $sz = [math]::Round($d.Size / 1GB, 1); $fr = [math]::Round($d.FreeSpace / 1GB, 1)
  Add-Line ("  Drive " + $d.DeviceID + "  size " + $sz + " GB, free " + $fr + " GB  (" + [math]::Round($d.FreeSpace / $d.Size * 100, 1) + "%)")
}
$pf = Safe { Get-CimInstance Win32_PageFileUsage }
foreach ($p in $pf) { Add-Line ("PageFile          : " + $p.Name + " allocated " + $p.AllocatedBaseSize + " MB, in use " + $p.CurrentUsage + " MB") }
Add-Line ("PowerPlan         : " + (Strip-Nulls (Safe { (powercfg /getactivescheme) -join ' ' })))
$summary.cpu            = "$($cpu.Name)"
$summary.cores          = $cpu.NumberOfLogicalProcessors
$summary.ram_gb         = $totalRamGB
$summary.disk_c_free_gb = ([math]::Round(($disks | Where-Object DeviceID -eq 'C:').FreeSpace / 1GB, 1))

# ------------------------------------------------------------- [D] network ---
Write-Host '-- ۲/۹ شبکه ...' -ForegroundColor Yellow
Add-Section '[D] NETWORK'
Add-Line ('--- Enabled network adapters (IP configuration) ---')
Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' } | ForEach-Object {
  Add-Line ("  Adapter          : " + $_.InterfaceAlias + "  (ifIndex " + $_.InterfaceIndex + ")")
  foreach ($a in $_.IPv4Address) { Add-Line ("    IPv4           : " + $a.IPAddress + "  (prefix " + $a.PrefixLength + ")") }
  if ($_.IPv4DefaultGateway) { Add-Line ("    Gateway        : " + $_.IPv4DefaultGateway.NextHop) }
  Add-Line ("    DNS            : " + (($_.DNSServer | Where-Object AddressFamily -eq 2 | Select-Object -ExpandProperty ServerAddresses) -join ', '))
}
$publicIP = ''
foreach ($svc in @('https://api.ipify.org', 'https://ifconfig.me/ip')) {
  try { $publicIP = ((Invoke-RestMethod -Uri $svc -TimeoutSec 6) | Out-String).Trim(); if ($publicIP) { break } } catch { }
}
Add-Line ("Detected public IP: " + $(if ($publicIP) { $publicIP } else { 'NOT DETECTED (no internet or blocked)' }))
Add-Line ("Expected server IP: 130.185.73.157  (باید با IP عمومی بالا یکسان باشد)")
$ghOk = $false
try { $ghOk = (Test-NetConnection -ComputerName 'github.com' -Port 443 -WarningAction SilentlyContinue).TcpTestSucceeded } catch { }
Add-Line ("Internet github:443: " + (YesNo $ghOk))
$summary.public_ip   = $publicIP
$summary.internet_ok = [bool]$ghOk

# ------------------------------------------- [E] virtualization / Hyper-V ----
Write-Host '-- ۳/۹ مجازی‌سازی و WSL ...' -ForegroundColor Yellow
Add-Section '[E] VIRTUALIZATION / HYPER-V / WSL2'
Add-Line ("VT-x in firmware  : " + (YesNo $cpu.VirtualizationFirmwareEnabled))
Add-Line ("HypervisorPresent : " + (YesNo $cs.HypervisorPresent))
Add-Line ("bcdedit hypervisor: " + (Strip-Nulls (Safe { (bcdedit /enum '{current}' | Select-String 'hypervisorlaunchtype').ToString().Trim() })))
Add-Line ('--- wsl.exe ---')
$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wslCmd) {
  Add-Line ("wsl path          : " + $wslCmd.Source)
  Add-Line ("wsl --status      : " + (Strip-Nulls ((Safe { (& wsl.exe --status 2>&1) -join ' ' }))))
  Add-Line ("wsl --version     : " + (Strip-Nulls ((Safe { (& wsl.exe --version 2>&1) -join ' | ' }))))
  Add-Line ("wsl -l -v         : " + (Strip-Nulls ((Safe { (& wsl.exe -l -v 2>&1) -join ' | ' }))))
} else {
  Add-Line 'wsl.exe           : NOT FOUND (WSL نصب نیست)'
}
$summary.vt_firmware        = [bool]$cpu.VirtualizationFirmwareEnabled
$summary.hypervisor_present = [bool]$cs.HypervisorPresent
$summary.wsl_installed      = [bool]$wslCmd

# --------------------------------------------------------- [F] windows feat --
Add-Section '[F] WINDOWS FEATURES (related)'
$featNames = @(
  'Microsoft-Hyper-V-All',
  'Microsoft-Hyper-V-Hypervisor',
  'VirtualMachinePlatform',
  'Microsoft-Windows-Subsystem-Linux',
  'Containers',
  'IIS-WebServerRole',
  'IIS-WebServer'
)
$featResults = @{}
foreach ($f in $featNames) {
  if ($isAdmin) {
    $state = Safe { (Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue).State }
    $featResults[$f] = "$(if ($state) { $state } else { 'NotFound' })"
  } else {
    $featResults[$f] = 'SKIPPED (needs Administrator)'
  }
  Add-Line ("  " + $f.PadRight(38) + " : " + $featResults[$f])
}
$summary.features = $featResults

# ------------------------------------------------------------- [G] docker ----
Write-Host '-- ۴/۹ Docker ...' -ForegroundColor Yellow
Add-Section '[G] DOCKER'
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
  Add-Line ("docker path       : " + $dockerCmd.Source)
  Add-Line ("docker version    : " + (Strip-Nulls (Safe { (& docker --version 2>&1) -join ' ' })))
  Add-Line ("compose version   : " + (Strip-Nulls (Safe { (& docker compose version 2>&1) -join ' ' })))
  $dInfo = Safe { (& docker info --format '{{.ServerVersion}} | OSType={{.OSType}} | CPUs={{.NCPU}} | Mem={{.MemTotal}}' 2>&1) -join ' ' }
  Add-Line ("docker info       : " + (Strip-Nulls $dInfo))
} else {
  Add-Line 'docker            : NOT FOUND (Docker نصب نیست)'
}
Get-Service *docker* -ErrorAction SilentlyContinue | ForEach-Object {
  Add-Line ("  Service         : " + $_.Name + " -> " + $_.Status)
}
$summary.docker_installed = [bool]$dockerCmd

# ---------------------------------------------------- [H] listening ports ----
Write-Host '-- ۵/۹ پورت‌های باز (TCP/UDP) ...' -ForegroundColor Yellow
Add-Section '[H] LISTENING PORTS (TCP + UDP) with owner process'
$script:procCache = @{}
function Get-ProcName([int]$ownerPid) {
  if (-not $script:procCache.ContainsKey($ownerPid)) {
    $p = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    if ($p) { $script:procCache[$ownerPid] = $p.ProcessName } else { $script:procCache[$ownerPid] = 'Unknown' }
  }
  return $script:procCache[$ownerPid]
}
$tcpRows = @()
Safe { Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue } | ForEach-Object {
  $tcpRows += [pscustomobject]@{ Proto='TCP'; Port=$_.LocalPort; Addr=$_.LocalAddress; OwnerPid=$_.OwningProcess; Proc=(Get-ProcName $_.OwningProcess) }
}
$udpRows = @()
Safe { Get-NetUDPEndpoint -ErrorAction SilentlyContinue } | ForEach-Object {
  $udpRows += [pscustomobject]@{ Proto='UDP'; Port=$_.LocalPort; Addr=$_.LocalAddress; OwnerPid=$_.OwningProcess; Proc=(Get-ProcName $_.OwningProcess) }
}
Add-Line ('--- TCP listeners ---')
$tcpRows | Sort-Object Port, Addr | Get-Unique -AsString | ForEach-Object {
  Add-Line ("  TCP  " + ($_.Port.ToString().PadRight(6)) + $_.Addr.PadRight(24) + $_.Proc.PadRight(24) + "pid=" + $_.OwnerPid)
}
Add-Line ('--- UDP endpoints ---')
$udpRows | Sort-Object Port, Addr | Get-Unique -AsString | ForEach-Object {
  Add-Line ("  UDP  " + ($_.Port.ToString().PadRight(6)) + $_.Addr.PadRight(24) + $_.Proc.PadRight(24) + "pid=" + $_.OwnerPid)
}

# ------------------------------------------------- [I] critical port check ---
Add-Section '[I] CRITICAL PORT CHECK (project needs / common conflicts)'
$critical = @(21, 22, 80, 443, 1433, 3306, 3389, 5432, 6379, 8000, 8080, 9000)
$listenPorts = @($tcpRows | Select-Object -ExpandProperty Port -Unique)
$portState = [ordered]@{}
foreach ($cp in $critical) {
  $inUse = $listenPorts -contains $cp
  $owner = ''
  if ($inUse) { $owner = (($tcpRows | Where-Object Port -eq $cp | Select-Object -ExpandProperty Proc -Unique) -join ',') }
  $label = 'INFO'
  if ($cp -in @(80, 443, 8080, 8000, 5432, 6379)) { $label = 'PROJECT-RELATED' }
  $statusTxt = 'free'
  if ($inUse) { $statusTxt = "OCCUPIED by [$owner]" }
  Add-Line ("  port " + $cp.ToString().PadRight(6) + " : " + $statusTxt.PadRight(34) + $label)
  $portState["$cp"] = $(if ($inUse) { "occupied($owner)" } else { 'free' })
}
$summary.critical_ports = $portState

# ----------------------------------------------------------- [J] services ----
Write-Host '-- ۶/۹ سرویس‌های تداخل‌زا ...' -ForegroundColor Yellow
Add-Section '[J] SERVICES OF INTEREST (potential conflicts / infra)'
$svcPattern = @('W3SVC','WAS','MSSQLSERVER','MSSQL*','MySQL*','Apache*','nginx*','redis*','docker*','LxssManager','vmcompute','vmms','hns','WinNat','iphlpsvc','SharedAccess')
$found = @()
foreach ($sp in $svcPattern) { $found += @(Get-Service $sp -ErrorAction SilentlyContinue) }
if ($found.Count -eq 0) {
  Add-Line '  (هیچ‌کدام از سرویس‌های رایج مرتبط یافت نشد)'
} else {
  $found | Sort-Object Name -Unique | ForEach-Object {
    Add-Line ("  " + $_.Name.PadRight(28) + $_.Status.ToString().PadRight(10) + "StartType=" + $_.StartType)
  }
}
$iisRunning = @($found | Where-Object { ($_.Name -eq 'W3SVC' -or $_.Name -eq 'WAS') -and $_.Status -eq 'Running' }).Count -gt 0
$summary.iis_running = $iisRunning

# ------------------------------------------------- [K] installed programs ----
Write-Host '-- ۷/۹ برنامه‌های نصب‌شده (ممکن است چند ثانیه طول بکشد) ...' -ForegroundColor Yellow
Add-Section '[K] INSTALLED PROGRAMS (registry - full list)'
$uninstallPaths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$apps = foreach ($p in $uninstallPaths) {
  Get-ItemProperty $p -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName } |
    Select-Object DisplayName, DisplayVersion, Publisher, InstallDate
}
$apps = @($apps | Sort-Object DisplayName -Unique)
Add-Line ("Total installed programs: " + ($apps | Measure-Object).Count)
Add-Line ('')
Add-Line ('Name'.PadRight(52) + 'Version'.PadRight(20) + 'Publisher')
Add-Line ('-' * 110)
foreach ($a in $apps) {
  $n = "$($a.DisplayName)"; if ($n.Length -gt 50) { $n = $n.Substring(0, 50) }
  $v = "$($a.DisplayVersion)"; if ($v.Length -gt 18) { $v = $v.Substring(0, 18) }
  $pub = "$($a.Publisher)"
  Add-Line ($n.PadRight(52) + $v.PadRight(20) + $pub)
}
$summary.installed_programs_count = ($apps | Measure-Object).Count

# ------------------------------------------------ [L] firewall / defender ----
Write-Host '-- ۸/۹ فایروال و آنتی‌ویروس ...' -ForegroundColor Yellow
Add-Section '[L] FIREWALL & DEFENDER'
$profiles = Safe { Get-NetFirewallProfile }
$profiles | ForEach-Object {
  Add-Line ("  Profile " + $_.Name.PadRight(10) + " Enabled=" + (YesNo $_.Enabled))
  $summary.firewall = @{}
}
$fwHash = @{}
Safe { Get-NetFirewallProfile } | ForEach-Object { $fwHash[$_.Name] = [bool]$_.Enabled }
$summary.firewall = $fwHash
$fwRules = Safe { Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True -ErrorAction SilentlyContinue | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @('80','443','8080','8000') } }
if ($fwRules -and $fwRules -notmatch 'ERROR') {
  Add-Line '  Inbound allow rules touching 80/443/8080/8000:'
  $fwRules | ForEach-Object { Add-Line ("    - protocol=" + $_.Protocol + " localPort=" + $_.LocalPort) }
} else {
  Add-Line '  (قانون ورودی فعالی برای 80/443/8080/8000 یافت نشد)'
}
$mp = Safe { Get-MpComputerStatus -ErrorAction SilentlyContinue }
if ($mp -isnot [string]) {
  Add-Line ("Defender AV enabled     : " + (YesNo $mp.AntivirusEnabled))
  Add-Line ("Defender RealTime       : " + (YesNo $mp.RealTimeProtectionEnabled))
  Add-Line ("Defender signature age  : " + $mp.AntivirusSignatureAge + " days")
} else {
  Add-Line 'Defender                : status not available'
}

# ------------------------------------------------------------ [M] misc -------
Add-Section '[M] MISC (pending reboot / RDP)'
$rb1 = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
$rb2 = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
Add-Line ("Pending reboot (CBS)     : " + (YesNo $rb1))
Add-Line ("Pending reboot (WU)      : " + (YesNo $rb2))
$rdp = Safe { (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server').fDenyTSConnections }
Add-Line ("RDP enabled              : " + $(if ($rdp -eq 0) { 'YES' } else { 'NO' }))
$summary.pending_reboot = ($rb1 -or $rb2)

# ------------------------------------------------------------ write files ----
Write-Host '-- ۹/۹ نوشتن فایل گزارش ...' -ForegroundColor Yellow
Add-Line ''
Add-Line '=============================================================='
Add-Line '  END OF REPORT - این فایل را کامل برای کارشناس استقرار ارسال کنید'
Add-Line '=============================================================='

[System.IO.File]::WriteAllText($txtPath, $sb.ToString(), (New-Object System.Text.UTF8Encoding($true)))
$summaryJson = $summary | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($jsonPath, $summaryJson, (New-Object System.Text.UTF8Encoding($true)))

Write-Host ''
Write-Host 'گزارش کامل شد ✓' -ForegroundColor Green
Write-Host ('  گزارش متنی : ' + $txtPath)
Write-Host ('  خلاصه JSON : ' + $jsonPath)
Write-Host ''
Write-Host 'هر دو فایل را برای کارشناس استقرار ارسال کنید (ترجیحاً متن کامل).' -ForegroundColor Cyan
try { notepad $txtPath } catch { }

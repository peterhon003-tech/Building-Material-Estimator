# ============================================================
#  Fire Board Estimator - Windows setup (run once after install)
#
#  Run in PowerShell as administrator, signed in as the SAME Windows
#  user that owns the WSL Ubuntu:
#    powershell -ExecutionPolicy Bypass -File C:\fireboard_ops\windows_setup.ps1
#
#  - Firewall: allow port 8000 from the local network
#  - Task "Fireboard WSL": start WSL at power-on (no sign-in needed)
#  - Task "Fireboard Port 8000": forward this PC's port 8000 to WSL
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================
#
#  Options:
#    -LocalOnly   Only this PC can open the site (http://localhost:8000).
#                 Sets WEB_PORT=127.0.0.1:8000, removes firewall rule and
#                 port forward, and only sets up auto-start.
#  Without -LocalOnly the mode follows WEB_PORT in /opt/fireboard/.env
#  (the installer writes 127.0.0.1:8000 when you answered "y").
#    -Distro <name>        WSL distro to use (default: the one with /opt/fireboard)
#    -PasswordFile <path>  read the Windows password from this file and delete it
#                          (used by FireboardSetup.exe; otherwise a dialog asks)
#Requires -RunAsAdministrator
param(
    [switch]$LocalOnly,
    [string]$Distro = "",
    [string]$PasswordFile = ""
)

$Ops  = $PSScriptRoot
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$WslExe = Find-Wsl
if (-not $WslExe) { Write-Host "[ERROR] wsl.exe not found. Install WSL first." -ForegroundColor Red; exit 1 }
$Port = 8000

# ---------- 1. Find the WSL distro that has the system ----------
if (-not $Distro) {
    foreach ($line in (& $WslExe -l -q)) {
        $d = ($line -replace "`0", "").Trim()
        if (-not $d -or $d -like "docker-desktop*") { continue }
        & $WslExe -d $d -u root -- test -f /opt/fireboard/docker-compose.yml 2>$null
        if ($LASTEXITCODE -eq 0) { $Distro = $d; break }
    }
} else {
    & $WslExe -d $Distro -u root -- test -f /opt/fireboard/docker-compose.yml 2>$null
    if ($LASTEXITCODE -ne 0) { $Distro = "" }
}
if (-not $Distro) {
    Write-Host "[ERROR] No WSL distro has /opt/fireboard. Run the installer in Ubuntu first." -ForegroundColor Red
    exit 1
}
Write-Host ">> WSL distro: $Distro"

# Local-only? Forced by -LocalOnly, otherwise read from .env
if ($LocalOnly) {
    & $WslExe -d $Distro -u root -- sh -c "sed -i 's/^WEB_PORT=.*/WEB_PORT=127.0.0.1:$Port/' /opt/fireboard/.env && cd /opt/fireboard && docker compose up -d"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Could not switch the site to this PC only." -ForegroundColor Red
        exit 1
    }
} else {
    & $WslExe -d $Distro -u root -- grep -q "^WEB_PORT=127.0.0.1:" /opt/fireboard/.env 2>$null
    $LocalOnly = ($LASTEXITCODE -eq 0)
}

if ($LocalOnly) {
    Write-Host ">> Mode: this PC only (other computers cannot connect)"
    # Remove anything that lets other computers in
    foreach ($line in (netsh interface portproxy show v4tov4)) {
        if ($line -match '^\s*(\S+)\s+(\d+)\s+\S+\s+\d+\s*$' -and $Matches[2] -eq "$Port") {
            netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$($Matches[1]) | Out-Null
        }
    }
    Get-NetFirewallRule -DisplayName "Fireboard $Port" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
        Get-NetFirewallHyperVRule -Name "Fireboard$Port" -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule
    }
    Unregister-ScheduledTask -TaskName "Fireboard Port $Port" -Confirm:$false -ErrorAction SilentlyContinue
    # http://localhost:8000 needs WSL localhost forwarding (on by default)
    $wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
    if ((Test-Path $wslconfig) -and (Select-String -Path $wslconfig -Pattern "localhostForwarding\s*=\s*false" -Quiet)) {
        Write-Host "[WARNING] $wslconfig has localhostForwarding=false. Remove that line, then run: wsl --shutdown" -ForegroundColor Yellow
    }
}

# ---------- 2. Firewall ----------
if (-not $LocalOnly) {
    if (-not (Get-NetFirewallRule -DisplayName "Fireboard $Port" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Fireboard $Port" -Direction Inbound -Protocol TCP `
            -LocalPort $Port -RemoteAddress LocalSubnet -Action Allow | Out-Null
    }
    if (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
        if (-not (Get-NetFirewallHyperVRule -Name "Fireboard$Port" -ErrorAction SilentlyContinue)) {
            New-NetFirewallHyperVRule -Name "Fireboard$Port" -DisplayName "Fireboard $Port" -Direction Inbound `
                -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts $Port | Out-Null
        }
    }
    Write-Host ">> Firewall: port $Port allowed from the local network"
}

# ---------- 3. Scheduled tasks ----------
$user = "$env:USERDOMAIN\$env:USERNAME"
if ($PasswordFile) {
    $pw = (Get-Content -LiteralPath $PasswordFile -Encoding UTF8 -Raw).TrimEnd("`r", "`n")
    Remove-Item -LiteralPath $PasswordFile -Force -ErrorAction SilentlyContinue
} else {
    $cred = Get-Credential -UserName $user -Message "Windows password of $user (tasks run at power-on without sign-in). A PIN does not work."
    if (-not $cred) { Write-Host "[ERROR] No password given." -ForegroundColor Red; exit 1 }
    $pw = $cred.GetNetworkCredential().Password
}
if (-not $pw) { Write-Host "[ERROR] No password given." -ForegroundColor Red; exit 1 }

$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# wsl.exe started by a task with no console exits at once (-1), so run it through
# cmd.exe with its output in a log file; retry up to 10 times, 30 s apart.
$wslLog = Join-Path $Ops "wsl_task.log"
$a1 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "set WSL_UTF8=1&& for /l %i in (1,1,10) do (echo %date% %time% start >> "{0}" & "{2}" -d {1} -u root -- sleep infinity >> "{0}" 2>&1 & ping -n 31 127.0.0.1 >nul)"' -f $wslLog, $Distro, $WslExe)
$t1 = New-ScheduledTaskTrigger -AtStartup
$t1.Delay = "PT1M"
try {
    Register-ScheduledTask -TaskName "Fireboard WSL" -Action $a1 -Trigger $t1 -Settings $settings `
        -User $user -Password $pw -RunLevel Highest -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "[ERROR] Could not create the startup task. Is the Windows password correct? $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}

if (-not $LocalOnly) {
$a2 = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Ops\wsl_portproxy.ps1`" -Distro `"$Distro`" -Port $Port"
$t2 = New-ScheduledTaskTrigger -AtStartup
$t2.Delay = "PT1M"
Register-ScheduledTask -TaskName "Fireboard Port $Port" -Action $a2 -Trigger $t2 -Settings $settings `
    -User $user -Password $pw -RunLevel Highest -Force | Out-Null
Write-Host ">> Task created: 'Fireboard Port $Port'"
}
Write-Host ">> Task created: 'Fireboard WSL'"

# ---------- 4. Start now ----------
Start-ScheduledTask -TaskName "Fireboard WSL"
Start-Sleep -Seconds 15
Write-Host ""
if ($LocalOnly) {
    Write-Host "Done. Open on THIS PC only: http://localhost:$Port" -ForegroundColor Green
    Write-Host "Test: restart this PC, sign in, wait 2 minutes, then open http://localhost:$Port"
} else {
    & "$Ops\wsl_portproxy.ps1" -Distro $Distro -Port $Port
    Get-Content "$Ops\wsl_portproxy.log" -Tail 1
    Write-Host "Done. From another computer open: http://<this PC IP>:$Port" -ForegroundColor Green
    Write-Host "Test: restart this PC, do NOT sign in, wait 3 minutes, then open the site from another computer."
}

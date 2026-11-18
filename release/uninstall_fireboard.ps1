# ============================================================
#  Fire Board Estimator - remove the system from this PC
#
#  Run in PowerShell as administrator, signed in as the Windows user
#  that owns the WSL distro:
#    powershell -ExecutionPolicy Bypass -File uninstall_fireboard.ps1 -Distro Fireboard
#
#  Removes: scheduled tasks, port forward, firewall rules, and the WSL
#  distro (ALL data inside it: database, Docker images, settings).
#  Options:
#    -Distro <name>     WSL distro to remove (default: Fireboard)
#    -RemoveBackups     also delete C:\fireboard_backup (or -BackupDir)
#    -RemoveWsl         also uninstall the WSL package (wsl --uninstall).
#                       Windows features are NOT turned off: turning off
#                       "Virtual Machine Platform" can delete its files, and turning
#                       it on again then needs a download from Windows Update.
#    -DisableFeatures   also turn off the Windows features "Windows Subsystem for
#                       Linux" and "Virtual Machine Platform" (not recommended)
#    -KeepOpsDir        do not delete -OpsDir (used by the Setup.exe uninstaller)
#    -Yes               do not ask for confirmation
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================
#Requires -RunAsAdministrator
param(
    [string]$Distro = "Fireboard",
    [string]$BackupDir = "C:\fireboard_backup",
    [string]$OpsDir = "C:\fireboard_ops",
    [int]$Port = 8000,
    [switch]$RemoveBackups,
    [switch]$RemoveWsl,
    [switch]$DisableFeatures,
    [switch]$KeepOpsDir,
    [switch]$Yes
)

function Step($msg) { Write-Host ">> $msg" }
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

if (-not $Yes) {
    Write-Host "This removes the Fire Board system and ALL data in WSL distro '$Distro'." -ForegroundColor Yellow
    if ($RemoveBackups) { Write-Host "Backups in $BackupDir will also be DELETED." -ForegroundColor Yellow }
    if ($RemoveWsl)     { Write-Host "The WSL package will also be uninstalled (Windows features stay on)." -ForegroundColor Yellow }
    if ($DisableFeatures) { Write-Host "Windows features WSL and Virtual Machine Platform will be TURNED OFF. Turning them on again may need Windows Update." -ForegroundColor Yellow }
    $answer = Read-Host "Type YES to continue"
    if ($answer -ne "YES") { Write-Host "Cancelled."; exit 1 }
}

# 1. Scheduled tasks
Step "Removing scheduled tasks"
foreach ($t in @("Fireboard WSL", "Fireboard Port $Port")) {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}

# 2. Port forward and firewall rules
Step "Removing port forward and firewall rules"
foreach ($line in (netsh interface portproxy show v4tov4)) {
    if ($line -match '^\s*(\S+)\s+(\d+)\s+\S+\s+\d+\s*$' -and $Matches[2] -eq "$Port") {
        netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$($Matches[1]) | Out-Null
    }
}
Get-NetFirewallRule -DisplayName "Fireboard*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
    Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "Fireboard*" } | Remove-NetFirewallHyperVRule
}

# 3. WSL distro
$wsl = Find-Wsl
if ($wsl) {
    $names = @(& $wsl -l -q 2>$null | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ })
    if ($names -contains $Distro) {
        Step "Removing WSL distro '$Distro' (all data inside it)"
        & $wsl --terminate $Distro 2>$null | Out-Null
        & $wsl --unregister $Distro
    } else {
        Step "WSL distro '$Distro' not found - skipped"
    }
}

# 4. Files
if (-not $KeepOpsDir -and (Test-Path $OpsDir)) {
    Step "Deleting $OpsDir"
    Remove-Item -Recurse -Force $OpsDir -ErrorAction SilentlyContinue
}
if ($RemoveBackups -and (Test-Path $BackupDir)) {
    Step "Deleting backups in $BackupDir"
    Remove-Item -Recurse -Force $BackupDir -ErrorAction SilentlyContinue
}

# 5. WSL package (Windows features stay on unless -DisableFeatures)
if ($RemoveWsl -and $wsl) {
    Step "Uninstalling the WSL package"
    & $wsl --shutdown 2>$null | Out-Null
    & $wsl --uninstall 2>$null | Out-Null
    Write-Host "WSL package removed. The Windows features are still on." -ForegroundColor Green
}
if ($DisableFeatures) {
    Step "Turning off Windows features (WSL, Virtual Machine Platform)"
    dism.exe /online /disable-feature /featurename:Microsoft-Windows-Subsystem-Linux /norestart | Out-Null
    dism.exe /online /disable-feature /featurename:VirtualMachinePlatform /norestart | Out-Null
    Write-Host "Features turned off. Restart the PC to finish." -ForegroundColor Green
}

Write-Host "Done." -ForegroundColor Green
exit 0

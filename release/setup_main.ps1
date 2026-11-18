# ============================================================
#  Fire Board Estimator - main install step for FireboardSetup.exe
#
#  Called by the Inno Setup wizard after it has copied its files to
#  -AppDir. Runs as administrator, as the Windows user who started setup.
#  Writes everything to <AppDir>\setup.log. Exit code 0 = success.
#
#  1. create a WSL distro "Fireboard" from fireboard-base.tar
#     (Ubuntu + Docker Engine + systemd, prepared by build_installer.ps1)
#  2. run fireboard-install.run inside it (images + all data)
#  3. lock the backup folder to this user, SYSTEM and administrators
#  4. windows_setup.ps1: start-up task (+ firewall / port forward if network)
#  5. check that http://localhost:8000 answers
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [ValidateSet("Local", "Network")][string]$Mode = "Local",
    [string]$BackupDir = "C:\fireboard_backup",
    [Parameter(Mandatory = $true)][string]$PasswordFile,
    [string]$Distro = "Fireboard",
    [string]$ProgressFile = ""     # "<percent> <step>" for the Setup.exe progress page
)
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

$ErrorActionPreference = "Continue"
$Log  = Join-Path $AppDir "setup.log"
$Wsl  = Find-Wsl
$Port = 8000

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    $line | Out-File -FilePath $Log -Append -Encoding utf8
}
function Progress($pct, $step) {
    if ($ProgressFile) {
        try { [System.IO.File]::WriteAllText($ProgressFile, "$pct $step") } catch { }
    }
}
function Fail($code, $msg) {
    Log "[FAILED] $msg"
    Progress 100 "failed $code"
    Remove-Item -LiteralPath $PasswordFile -Force -ErrorAction SilentlyContinue
    exit $code
}
function ToWslPath($winPath) {
    $full = [System.IO.Path]::GetFullPath($winPath)
    return "/mnt/" + $full.Substring(0, 1).ToLower() + ($full.Substring(2) -replace '\\', '/')
}
# Run a program with its output appended to the log as UTF-8; returns its exit code
function RunLogged([string]$exe, [string[]]$exeArgs) {
    & $exe @exeArgs 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $Log -Append -Encoding utf8
    return $LASTEXITCODE
}
function RunWsl([string[]]$wslArgs) { return (RunLogged $Wsl $wslArgs) }

trap { Fail 99 "Unexpected error: $_" }

$env:WSL_UTF8 = "1"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

Log "========== Fireboard setup started (mode=$Mode, backup=$BackupDir) =========="

# ---------- 1. WSL ready? ----------
Progress 2 check_wsl
if (-not $Wsl) { Fail 10 "wsl.exe not found (WSL package not installed). Restart the PC and run setup again." }
if ((RunWsl @("--version")) -ne 0) { Fail 10 "WSL is not ready (wsl --version failed). Restart the PC and run setup again." }

$names = @(& $Wsl -l -q 2>$null | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ })
if ($names -contains $Distro) { Fail 11 "WSL distro '$Distro' already exists. Uninstall Fireboard first." }

# ---------- 2. Create the distro ----------
$base = Join-Path $AppDir "fireboard-base.tar"
if (-not (Test-Path $base)) { Fail 12 "Missing $base" }
$vmDir = Join-Path $env:LOCALAPPDATA "Fireboard\wsl"     # per-user folder: other users cannot read it
New-Item -ItemType Directory -Path $vmDir -Force | Out-Null
Progress 5 import
Log "Importing WSL distro '$Distro' into $vmDir (a few minutes)"
if ((RunWsl @("--import", $Distro, $vmDir, $base, "--version", "2")) -ne 0) { Fail 13 "wsl --import failed. Is virtualization enabled? (Task Manager > Performance > CPU > Virtualization)" }

# Start it and wait for Docker (systemd starts it)
Progress 25 start_docker
Log "Starting the distro and waiting for Docker"
$ok = $false
for ($i = 0; $i -lt 60 -and -not $ok; $i++) {
    & $Wsl -d $Distro -u root --exec docker info *> $null
    if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep -Seconds 3 }
}
if (-not $ok) { Fail 14 "Docker did not start inside the distro" }

# ---------- 3. Install the system and data ----------
$run = Join-Path $AppDir "fireboard-install.run"
if (-not (Test-Path $run)) { Fail 15 "Missing $run" }
$envFile = Join-Path $AppDir "install.env"
$localOnly = if ($Mode -eq "Local") { "y" } else { "n" }
$envText = "FB_LOCAL_ONLY='$localOnly'`nFB_BACKUP_WIN='$BackupDir'`nFB_OPS_WIN='$AppDir'`nFB_PROGRESS_WIN='$ProgressFile'`n"
[System.IO.File]::WriteAllText($envFile, $envText, (New-Object System.Text.UTF8Encoding($false)))
Progress 30 extract
Log "Running the installer inside WSL (5-15 minutes)"
$rc = RunWsl @("-d", $Distro, "-u", "root", "--exec", "env", "FB_ENV_FILE=$(ToWslPath $envFile)", "sh", (ToWslPath $run))
Remove-Item -LiteralPath $envFile -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { Fail 16 "The installer inside WSL failed (exit $rc). See the messages above." }

Progress 87 lock_backup
# ---------- 4. Backup folder: only this user, SYSTEM and administrators ----------
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
$me = "$env:USERDOMAIN\$env:USERNAME"
RunLogged "icacls.exe" @($BackupDir, "/inheritance:r", "/grant:r", "${me}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F") | Out-Null
Log "Backup folder locked to $me, SYSTEM and Administrators"

# ---------- 5. Start-up task, firewall, port forward ----------
$ws = Join-Path $AppDir "windows_setup.ps1"
$wsArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ws, "-Distro", $Distro, "-PasswordFile", $PasswordFile)
if ($Mode -eq "Local") { $wsArgs += "-LocalOnly" }
Progress 90 tasks
Log "Running windows_setup.ps1"
$rc = RunLogged (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") $wsArgs
Remove-Item -LiteralPath $PasswordFile -Force -ErrorAction SilentlyContinue
if ($rc -eq 2) { Fail 17 "Could not create the start-up task: wrong Windows password? Run windows_setup.ps1 again." }
if ($rc -ne 0) { Fail 18 "windows_setup.ps1 failed (exit $rc)" }

# ---------- 6. Check the site ----------
Progress 95 check_site
Log "Checking http://localhost:$Port"
$up = $false
for ($i = 0; $i -lt 40 -and -not $up; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/accounts/login/" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $up = $true }
    } catch { Start-Sleep -Seconds 3 }
}
if ($up) { Log "[OK] Site answers on http://localhost:$Port" }
else     { Log "[WARNING] http://localhost:$Port did not answer yet. Restart the PC and try again." }

Log "========== Fireboard setup finished =========="
Progress 100 "done 0"
exit 0

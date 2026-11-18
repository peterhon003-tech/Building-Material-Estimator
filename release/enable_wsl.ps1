# ============================================================
#  Fire Board Estimator - make sure WSL can run (called by FireboardSetup.exe)
#
#  1. BIOS virtualization must be on (cannot be changed by software)
#  2. Windows features "Windows Subsystem for Linux" and
#     "Virtual Machine Platform": skipped if already on; each dism call
#     has a time limit so setup never waits forever
#  3. WSL package (wsl.x64.msi bundled in the setup)
#
#  Progress file (read by setup): "<percent> <step>", last line
#  "100 done 0" (ready), "100 done 3010" (restart needed) or
#  "100 failed <code>": 20 = dism timed out, 21 = dism error,
#  22 = WSL package error, 23 = virtualization off in BIOS
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================
param(
    [Parameter(Mandatory = $true)][string]$Msi,
    [Parameter(Mandatory = $true)][string]$Log,
    [Parameter(Mandatory = $true)][string]$ProgressFile,
    [int]$TimeoutMinutes = 15
)

$ErrorActionPreference = "Continue"
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $Log -Append -Encoding utf8 }
function Progress($pct, $step) { try { [System.IO.File]::WriteAllText($ProgressFile, "$pct $step") } catch { } }
function Finish($word, $code) { Log "RESULT: $word $code"; Progress 100 "$word $code"; exit 0 }
trap { Log "Unexpected error: $_"; Finish "failed" 21 }

Log "========== enable_wsl started =========="

# ---------- 1. Virtualization ----------
Progress 2 check_virt
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
Log "VirtualizationFirmwareEnabled=$($cpu.VirtualizationFirmwareEnabled) HypervisorPresent=$($cs.HypervisorPresent)"
if (-not $cpu.VirtualizationFirmwareEnabled -and -not $cs.HypervisorPresent) { Finish "failed" 23 }

# ---------- 2. Windows features ----------
$reboot = $false
function Enable-Feature($name, $pct, $step) {
    Progress $pct $step
    $state = (Get-WindowsOptionalFeature -Online -FeatureName $name).State
    Log "$name state: $state"
    if ("$state" -eq "Enabled") { return 0 }
    if ("$state" -eq "EnablePending") { return 3010 }

    $out = Join-Path $env:TEMP "fireboard_dism_$name.txt"
    $p = Start-Process -FilePath "dism.exe" -PassThru -NoNewWindow `
        -ArgumentList "/online", "/enable-feature", "/featurename:$name", "/all", "/norestart" `
        -RedirectStandardOutput $out
    $null = $p.Handle     # keep the handle so ExitCode is available later
    if (-not $p.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        Log "dism for $name did not finish in $TimeoutMinutes minutes - stopping it"
        Get-Process dism, DismHost -ErrorAction SilentlyContinue | Stop-Process -Force
        return -2
    }
    if (Test-Path $out) { Get-Content $out | Where-Object { $_ -notmatch '^\s*\[=*' } | Out-File -FilePath $Log -Append -Encoding utf8 }
    Log "dism $name exit code $($p.ExitCode)"
    return $p.ExitCode
}

foreach ($f in @(@("Microsoft-Windows-Subsystem-Linux", 10, "wsl_feature"), @("VirtualMachinePlatform", 40, "vmp_feature"))) {
    $rc = Enable-Feature $f[0] $f[1] $f[2]
    if ($rc -eq -2) { Finish "failed" 20 }
    if ($rc -eq 3010) { $reboot = $true }
    elseif ($rc -ne 0) { Finish "failed" 21 }
}

# ---------- 3. WSL package ----------
Progress 70 wsl_package
$p = Start-Process -FilePath "msiexec.exe" -PassThru -WindowStyle Hidden `
    -ArgumentList "/i", "`"$Msi`"", "/quiet", "/norestart"
$null = $p.Handle
if (-not $p.WaitForExit(10 * 60 * 1000)) {
    Log "msiexec did not finish in 10 minutes"
    Finish "failed" 22
}
Log "msiexec exit code $($p.ExitCode)"
if ($p.ExitCode -in 3010, 1641) { $reboot = $true }
elseif ($p.ExitCode -ne 0) { Finish "failed" 22 }

# ---------- 4. Ready? ----------
Progress 95 check_wsl
$wsl = Find-Wsl
$ok = $false
if ($wsl) { & $wsl --version *> $null; $ok = ($LASTEXITCODE -eq 0) }
Log "wsl --version ok=$ok reboot=$reboot"
if ($reboot -or -not $ok) { Finish "done" 3010 }
Finish "done" 0

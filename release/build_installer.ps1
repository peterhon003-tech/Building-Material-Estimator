# ============================================================
#  Fire Board Estimator - build FireboardSetup-<version>.exe
#
#  Run on the machine with the LIVE system, in normal PowerShell:
#    powershell -ExecutionPolicy Bypass -File C:\fireboard\release\build_installer.ps1
#
#  Needs (once):
#    - Inno Setup 6 or 7 (https://jrsoftware.org/isdl.php)
#    - An Ubuntu 24.04 WSL image (*.wsl) from https://releases.ubuntu.com/noble/
#      saved in C:\fireboard_build\  (only for the first build, or -RebuildBase)
#    - Internet (first build only: apt and Docker for the base image, and the
#      WSL package wsl.*.x64.msi from github.com/microsoft/WSL/releases)
#
#  Steps:
#    1. Base image (first time / -RebuildBase): Ubuntu + Docker Engine + cron,
#       systemd on, root user -> C:\fireboard_build\fireboard-base.tar
#    2. Copy C:\fireboard\release to /opt/fireboard in the live distro and run
#       pack_fireboard.sh (latest images + ALL data) -> .run file
#    3. Compile fireboard.iss -> C:\fireboard_release\FireboardSetup-<version>.exe
#
#  Options: -ProdDistro Ubuntu  -BuildDir C:\fireboard_build  -OutDir C:\fireboard_release
#           -RebuildBase  -SkipPack (use the newest existing .run)  -Iscc <path to ISCC.exe>
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================
param(
    [string]$ProdDistro = "Ubuntu",
    [string]$BuildDir = "C:\fireboard_build",
    [string]$OutDir = "C:\fireboard_release",
    [string]$SrcDir = "C:\fireboard",
    [string]$Iscc = "",
    [switch]$RebuildBase,
    [switch]$SkipPack
)

$ErrorActionPreference = "Continue"   # native wsl.exe errors are checked with $LASTEXITCODE
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$Wsl = Find-Wsl
if (-not $Wsl) { Write-Host "[ERROR] wsl.exe not found. Install WSL first." -ForegroundColor Red; exit 1 }
$env:WSL_UTF8 = "1"
$TempDistro = "FireboardBuild"

function Step($msg) { Write-Host ""; Write-Host ">> $msg" -ForegroundColor Cyan }
function Die($msg)  { Write-Host ""; Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }
function ToWslPath($winPath) {
    $full = [System.IO.Path]::GetFullPath($winPath)
    return "/mnt/" + $full.Substring(0, 1).ToLower() + ($full.Substring(2) -replace '\\', '/')
}
function Distros { @(& $Wsl -l -q 2>$null | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ }) }

# ---------- 0. Checks ----------
if (-not $Iscc) {
    # Inno Setup 6 or 7, 32- or 64-bit, all users or current user: newest version first
    $Iscc = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA "Programs")) |
        Where-Object { $_ -and (Test-Path $_) } |
        ForEach-Object { Get-ChildItem -Path $_ -Directory -Filter "Inno Setup *" -ErrorAction SilentlyContinue } |
        ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
        Where-Object { Test-Path $_ } |
        Sort-Object -Descending | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { Die "Inno Setup (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php or use -Iscc <path to ISCC.exe>" }
Write-Host "Using $Iscc"
$Rel = Join-Path $SrcDir "release"
foreach ($f in "fireboard.iss", "setup_main.ps1", "enable_wsl.ps1", "windows_setup.ps1", "uninstall_fireboard.ps1", "pack_fireboard.sh", "install.sh") {
    if (-not (Test-Path (Join-Path $Rel $f))) { Die "Missing $Rel\$f" }
}
if (-not (Test-Path (Join-Path $SrcDir "wsl_portproxy.ps1"))) { Die "Missing $SrcDir\wsl_portproxy.ps1" }
if ((Distros) -notcontains $ProdDistro) { Die "WSL distro '$ProdDistro' (the live system) not found. Use -ProdDistro <name>." }
New-Item -ItemType Directory -Path $BuildDir, $OutDir -Force | Out-Null

# ---------- 1. Base image ----------
$Base = Join-Path $BuildDir "fireboard-base.tar"
if ($RebuildBase -or -not (Test-Path $Base)) {
    Step "1/3 Building the base image (Ubuntu + Docker). Needs internet, about 5-10 minutes."
    $img = Get-ChildItem $BuildDir -File | Where-Object { $_.Extension -in ".wsl", ".gz" -and $_.Name -notlike "fireboard-*" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $img) { Die "Put an Ubuntu 24.04 WSL image (*.wsl) from https://releases.ubuntu.com/noble/ into $BuildDir" }

    # wsl --import wants .tar or .tar.gz: copy with the right extension
    $fs = [System.IO.File]::OpenRead($img.FullName)
    $b0 = $fs.ReadByte(); $b1 = $fs.ReadByte(); $fs.Close()
    $ext = if ($b0 -eq 0x1F -and $b1 -eq 0x8B) { ".tar.gz" } else { ".tar" }
    $src = Join-Path $BuildDir ("ubuntu-src" + $ext)
    Copy-Item $img.FullName $src -Force -ErrorAction Stop

    if ((Distros) -contains $TempDistro) { & $Wsl --unregister $TempDistro | Out-Null }
    $vm = Join-Path $BuildDir "vm"
    New-Item -ItemType Directory -Path $vm -Force | Out-Null
    & $Wsl --import $TempDistro $vm $src --version 2
    if ($LASTEXITCODE -ne 0) { Die "wsl --import of $($img.Name) failed" }
    Remove-Item $src -Force

    # Phase 1: wsl.conf (systemd, root), no first-run wizard
    $phase1 = "printf '[boot]\nsystemd=true\n[user]\ndefault=root\n' > /etc/wsl.conf; rm -f /etc/wsl-distribution.conf; mkdir -p /etc/cloud; touch /etc/cloud/cloud-init.disabled"
    & $Wsl -d $TempDistro -u root --exec sh -c $phase1
    if ($LASTEXITCODE -ne 0) { Die "Base image phase 1 failed" }
    & $Wsl --terminate $TempDistro | Out-Null

    # Phase 2: packages (systemd is now running)
    $phase2 = "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq ca-certificates curl cron rsync; curl -fsSL https://get.docker.com | sh; systemctl enable docker containerd cron; apt-get clean; rm -rf /var/lib/apt/lists/*"
    & $Wsl -d $TempDistro -u root --exec sh -c $phase2
    if ($LASTEXITCODE -ne 0) { Die "Base image phase 2 failed (apt / Docker install). Check the internet connection." }
    & $Wsl --terminate $TempDistro | Out-Null

    Step "Exporting the base image to $Base"
    if (Test-Path $Base) { Remove-Item $Base -Force }
    & $Wsl --export $TempDistro $Base
    if ($LASTEXITCODE -ne 0) { Die "wsl --export failed" }
    & $Wsl --unregister $TempDistro | Out-Null
    Remove-Item $vm -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Step "1/3 Using the existing base image $Base (use -RebuildBase to make a new one)"
}

# ---------- 2. Pack the live system ----------
if (-not $SkipPack) {
    Step "2/3 Packing the live system from WSL distro '$ProdDistro' (images + ALL data)"
    $copy = "set -e; cp -r '$(ToWslPath $Rel)/.' /opt/fireboard/release/; cp '$(ToWslPath $SrcDir)/wsl_portproxy.ps1' '$(ToWslPath $SrcDir)/backup_fireboard.sh' /opt/fireboard/; chown -R root:root /opt/fireboard"
    & $Wsl -d $ProdDistro -u root --exec sh -c $copy
    if ($LASTEXITCODE -ne 0) { Die "Could not copy the release files into /opt/fireboard" }
    & $Wsl -d $ProdDistro -u root --exec sh /opt/fireboard/release/pack_fireboard.sh
    if ($LASTEXITCODE -ne 0) { Die "pack_fireboard.sh failed (see above)" }
} else {
    Step "2/3 Skipping pack: using the newest .run in $OutDir"
}
$run = Get-ChildItem $OutDir -Filter "fireboard-install-*.run" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $run) { Die "No fireboard-install-*.run in $OutDir" }
$version = $run.BaseName -replace '^fireboard-install-', ''

# ---------- WSL package (installed on the target PC if WSL is missing) ----------
$wslMsi = Get-ChildItem $BuildDir -File -Filter "wsl*x64*.msi" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wslMsi) {
    Step "Downloading the WSL package from github.com/microsoft/WSL"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/microsoft/WSL/releases/latest" -UseBasicParsing
        $asset = $rel.assets | Where-Object { $_.name -like "*x64.msi" } | Select-Object -First 1
        if (-not $asset) { throw "no x64 .msi in release $($rel.tag_name)" }
        $dest = Join-Path $BuildDir $asset.name
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -UseBasicParsing
        $wslMsi = Get-Item $dest
        Write-Host "Saved $dest"
    } catch {
        Die "Could not download the WSL package ($($_.Exception.Message)). Download wsl.x.y.z.0.x64.msi from https://github.com/microsoft/WSL/releases into $BuildDir and run again."
    }
} else {
    Write-Host "Using WSL package $($wslMsi.Name) (delete it from $BuildDir to download the latest)"
}

# ---------- 3. Compile ----------
Step "3/3 Compiling FireboardSetup-$version.exe (compression takes several minutes)"
$stage = Join-Path $BuildDir "stage"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item $Base (Join-Path $stage "fireboard-base.tar") -Force -ErrorAction Stop
Copy-Item $run.FullName (Join-Path $stage "fireboard-install.run") -Force -ErrorAction Stop
Copy-Item $wslMsi.FullName (Join-Path $stage "wsl.x64.msi") -Force -ErrorAction Stop
try {
    & $Iscc "/DVersion=$version" "/DStageDir=$stage" "/DOutDir=$OutDir" (Join-Path $Rel "fireboard.iss")
    if ($LASTEXITCODE -ne 0) { Die "Inno Setup compile failed (see above)" }
} finally {
    Remove-Item (Join-Path $stage "fireboard-install.run") -Force -ErrorAction SilentlyContinue   # contains ALL data
}

$exe = Join-Path $OutDir "FireboardSetup-$version.exe"
$size = [math]::Round((Get-Item $exe).Length / 1MB)
Write-Host ""
Write-Host "Done: $exe ($size MB)" -ForegroundColor Green
Write-Host "It contains ALL data (prices, user accounts). Keep it safe and delete it after installing."
Write-Host "You can also delete $($run.FullName) now."

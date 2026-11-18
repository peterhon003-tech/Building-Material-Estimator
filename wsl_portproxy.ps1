# ============================================================
#  Fire Board Estimator - forward port 8000 to WSL (Windows 10)
#
#  WSL2 gets a new internal IP every time it starts, so this
#  script finds the current IP and points Windows port 8000 to it.
#
#  The forward listens on this PC's network IP only (not localhost),
#  so Docker Desktop can still use http://localhost:8000 on this PC
#  (set WEB_PORT=127.0.0.1:8000 in C:\fireboard\.env).
#
#  Run as administrator, after WSL (Ubuntu) has started.
#  Results are written to wsl_portproxy.log in the same folder.
# ============================================================

param(
    [string]$Distro = "Ubuntu",
    [int]$Port = 8000,
    [string]$ListenIp = ""   # empty = this PC's main network IP; or fix it, e.g. "192.168.1.20"
)
$Log    = Join-Path $PSScriptRoot "wsl_portproxy.log"
# wsl.exe: the WSL package installs it in Program Files\WSL; the one in System32 may be missing
function Find-Wsl {
    foreach ($p in @((Join-Path $env:ProgramFiles "WSL\wsl.exe"), (Join-Path $env:SystemRoot "System32\wsl.exe"))) {
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $Log -Append -Encoding utf8
}

# This PC's network IP (the adapter that has a default gateway)
if (-not $ListenIp) {
    $ListenIp = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Select-Object -First 1
}
if (-not $ListenIp) {
    Write-Log "[FAILED] Could not find this PC's network IP. Use -ListenIp 192.168.x.x"
    exit 1
}

$WslExe = Find-Wsl
if (-not $WslExe) { Write-Log "[FAILED] wsl.exe not found"; exit 1 }

# Wait up to 2 minutes for WSL to report its IP address (eth0)
$ip = $null
for ($i = 0; $i -lt 24 -and -not $ip; $i++) {
    $out = & $WslExe -d $Distro -- ip -4 -o addr show eth0 2>$null
    if ($out -match 'inet (\d+\.\d+\.\d+\.\d+)') { $ip = $Matches[1] } else { Start-Sleep -Seconds 5 }
}
if (-not $ip) {
    Write-Log "[FAILED] Could not get the WSL IP address. Is Ubuntu running?"
    exit 1
}

# Remove any old forward on this port (any listen address)
foreach ($line in (netsh interface portproxy show v4tov4)) {
    if ($line -match '^\s*(\S+)\s+(\d+)\s+\S+\s+\d+\s*$' -and $Matches[2] -eq "$Port") {
        netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$($Matches[1]) | Out-Null
    }
}

netsh interface portproxy add v4tov4 listenport=$Port listenaddress=$ListenIp connectport=$Port connectaddress=$ip | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "[FAILED] netsh portproxy failed (run as administrator?)"
    exit 1
}
Write-Log "[OK] $ListenIp`:$Port -> $ip`:$Port"
exit 0

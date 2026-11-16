# ============================================================
#  Fire Board Estimator - forward port 8000 to WSL (Windows 10)
#
#  WSL2 gets a new internal IP every time it starts, so this
#  script finds the current IP and points Windows port 8000 to it.
#  Run as administrator, after WSL (Ubuntu) has started.
#  Results are written to wsl_portproxy.log in the same folder.
# ============================================================

$Distro = "Ubuntu"
$Port   = 8000
$Log    = Join-Path $PSScriptRoot "wsl_portproxy.log"

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $Log -Append -Encoding utf8
}

# Wait up to 2 minutes for WSL to report its IP address (eth0)
$ip = $null
for ($i = 0; $i -lt 24 -and -not $ip; $i++) {
    $out = wsl.exe -d $Distro -- ip -4 -o addr show eth0 2>$null
    if ($out -match 'inet (\d+\.\d+\.\d+\.\d+)') { $ip = $Matches[1] } else { Start-Sleep -Seconds 5 }
}
if (-not $ip) {
    Write-Log "[FAILED] Could not get the WSL IP address. Is Ubuntu running?"
    exit 1
}

netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 | Out-Null
netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$ip | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "[FAILED] netsh portproxy failed (run as administrator?)"
    exit 1
}
Write-Log "[OK] Port $Port -> $ip`:$Port"
exit 0

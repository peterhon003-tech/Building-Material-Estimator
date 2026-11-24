# ============================================================
#  Fire Board Estimator - limit who can connect (Windows 10)
#
#  Makes the firewall rule "Fireboard 8000" accept connections ONLY
#  from the office network (e.g. 192.168.0.0/24), not from everywhere
#  and not from VPN networks.
#  It also lists any OTHER firewall rules that open the same port,
#  so you can check them.
#
#  Run as administrator:
#    powershell -ExecutionPolicy Bypass -File C:\fireboard\firewall_fireboard.ps1
#  or give the office network yourself:
#    ... -File C:\fireboard\firewall_fireboard.ps1 -RemoteAddress 192.168.0.0/24
#
#  Results are written to firewall_fireboard.log in the same folder.
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================

param(
    [int]$Port = 8000,
    [string]$RemoteAddress = ""   # empty = the office network of this PC's main network card
)
$Log  = Join-Path $PSScriptRoot "firewall_fireboard.log"
$Rule = "Fireboard $Port"

function Write-Log($msg) {
    Write-Host $msg
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $Log -Append -Encoding utf8
}

# ---------- 0. Must be administrator ----------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "[FAILED] Please run PowerShell as administrator." -ForegroundColor Red
    exit 1
}

# ---------- 1. Find the office network ----------
if (-not $RemoteAddress) {
    $cfg = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        Select-Object -First 1
    if (-not $cfg) {
        Write-Log "[FAILED] Could not find the office network. Use -RemoteAddress 192.168.x.0/24"
        exit 1
    }
    $addr   = $cfg.IPv4Address | Select-Object -First 1
    $ip     = $addr.IPAddress
    $prefix = [int]$addr.PrefixLength

    # network address = IP with the host part set to 0
    $b = [System.Net.IPAddress]::Parse($ip).GetAddressBytes(); [Array]::Reverse($b)
    $ipInt = [BitConverter]::ToUInt32($b, 0)
    $mask  = if ($prefix -eq 0) { [uint32]0 } else { [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $prefix)) }
    $net   = [uint32]($ipInt -band $mask)
    $nb = [BitConverter]::GetBytes($net); [Array]::Reverse($nb)
    $RemoteAddress = "$([System.Net.IPAddress]::new($nb))/$prefix"

    Write-Host ""
    Write-Host "Network card : $($cfg.InterfaceAlias) ($($cfg.InterfaceDescription))"
    Write-Host "This PC      : $ip"
    Write-Host "Office network to allow: $RemoteAddress" -ForegroundColor Yellow
    Write-Host "(If this is your VPN and not the office network, answer N and run again with -RemoteAddress.)"
    $ans = Read-Host "Allow port $Port only from $RemoteAddress ? (Y/N)"
    if ($ans -notmatch '^[Yy]') { Write-Host "Cancelled. Nothing changed."; exit 1 }
}

# ---------- 2. Create or update our rule ----------
$existing = Get-NetFirewallRule -DisplayName $Rule -ErrorAction SilentlyContinue
if ($existing) {
    $existing | Set-NetFirewallRule -Enabled True -Action Allow -Direction Inbound -Profile Any `
        -RemoteAddress $RemoteAddress
    $existing | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
} else {
    New-NetFirewallRule -DisplayName $Rule -Direction Inbound -Protocol TCP -LocalPort $Port `
        -RemoteAddress $RemoteAddress -Action Allow -Profile Any | Out-Null
}
Write-Log "[OK] Rule '$Rule': TCP $Port allowed only from $RemoteAddress"

# ---------- 3. Other rules that also open this port ----------
$others = Get-NetFirewallPortFilter -Protocol TCP -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -contains "$Port" -or $_.LocalPort -contains "Any" } |
    Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Enabled -eq "True" -and $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" -and
                   $_.DisplayName -ne $Rule }
$wide = @()
foreach ($r in $others) {
    $remote = ($r | Get-NetFirewallAddressFilter).RemoteAddress -join ","
    $ports  = ($r | Get-NetFirewallPortFilter).LocalPort -join ","
    if ($ports -eq "Any" -and $remote -ne "Any") { continue }   # only report rules that really matter
    $wide += "  - $($r.DisplayName)   (ports: $ports, from: $remote)"
}
if ($wide.Count -gt 0) {
    Write-Log "[CHECK] Other firewall rules also allow incoming TCP on port $Port or on all ports:"
    $wide | ForEach-Object { Write-Log $_ }
    Write-Log "        If you do not know them, ask before disabling. Rules for Docker Desktop"
    Write-Log "        are normal on the test PC; keep the test site on 127.0.0.1 (see README)."
} else {
    Write-Log "[OK] No other rule opens port $Port."
}
exit 0

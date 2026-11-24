# ============================================================
#  Fire Board Estimator - HTTPS front door on Windows (Caddy)
#
#  Replaces the Windows "port proxy" with Caddy running on Windows,
#  so the website can see each colleague's real IP address
#  (shown in Admin -> Failed log-ins, and in the access log).
#
#    colleague --https--> Windows Caddy (port 8000) --> WSL website (127.0.0.1:8443)
#
#  BEFORE running this: in Ubuntu, in /opt/fireboard/.env set
#    WEB_PORT=127.0.0.1:8443
#    FB_TRUSTED_PROXIES=private_ranges
#  and run: sudo docker compose up -d
#
#  Run as administrator (after the Ubuntu step above):
#    powershell -ExecutionPolicy Bypass -File C:\fireboard\windows_caddy_setup.ps1
#  Options:
#    -ListenIp 192.168.0.98   this PC's office IP (default: found automatically)
#    -Remove                  undo: remove Caddy, turn the old port proxy back on
#                             (then set WEB_PORT=8000 again in Ubuntu)
#
#  Files: C:\fireboard_caddy  (caddy.exe, Caddyfile, data = certificates, logs)
#  Results are written to C:\fireboard_caddy\setup.log
#  This file is plain ASCII on purpose (Windows PowerShell 5.1).
# ============================================================

param(
    [int]$Port = 8000,              # the port colleagues use (unchanged)
    [int]$UpstreamPort = 8443,      # WSL website, only on 127.0.0.1
    [string]$ListenIp = "",
    [string]$Dir = "C:\fireboard_caddy",
    [switch]$Remove
)
$Service  = "FireboardCaddy"
$OldTask  = "Fireboard Port $Port"
$Exe      = Join-Path $Dir "caddy.exe"
$Conf     = Join-Path $Dir "Caddyfile"
$Data     = Join-Path $Dir "data"
$Logs     = Join-Path $Dir "logs"
if ($Dir -match '\s') { Write-Host "[FAILED] -Dir must not contain spaces." -ForegroundColor Red; exit 1 }
New-Item -ItemType Directory -Force -Path $Dir, $Logs | Out-Null
$Log      = Join-Path $Dir "setup.log"

function Write-Log($msg) {
    Write-Host $msg
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $Log -Append -Encoding utf8
}
function Die($msg) { Write-Log "[FAILED] $msg"; exit 1 }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "[FAILED] Please run PowerShell as administrator." -ForegroundColor Red; exit 1 }

function Remove-CaddyService {
    if (Get-Service -Name $Service -ErrorAction SilentlyContinue) {
        Stop-Service -Name $Service -Force -ErrorAction SilentlyContinue
        & sc.exe delete $Service | Out-Null
        Start-Sleep -Seconds 2
    }
}

# ---------- Undo ----------
if ($Remove) {
    Remove-CaddyService
    Write-Log "[OK] Service $Service removed."
    if (Get-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue) {
        Enable-ScheduledTask -TaskName $OldTask | Out-Null
        Start-ScheduledTask -TaskName $OldTask
        Write-Log "[OK] Old port proxy task '$OldTask' turned on again."
    }
    Write-Log "Now in Ubuntu set WEB_PORT=8000 in /opt/fireboard/.env, delete the line FB_TRUSTED_PROXIES, and run: sudo docker compose up -d"
    exit 0
}

# ---------- 1. This PC's office IP ----------
if (-not $ListenIp) {
    $ListenIp = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
        ForEach-Object { $_.IPv4Address.IPAddress } | Select-Object -First 1
}
if (-not $ListenIp) { Die "Could not find this PC's IP. Use -ListenIp 192.168.x.x" }
Write-Host ""
Write-Host "Colleagues will open: https://$ListenIp`:$Port" -ForegroundColor Yellow
$ans = Read-Host "Is $ListenIp this PC's OFFICE IP (not VPN)? (Y/N)"
if ($ans -notmatch '^[Yy]') { Write-Host "Cancelled. Turn off VPN, or run again with -ListenIp."; exit 1 }

# ---------- 2. The WSL website must answer on 127.0.0.1:UpstreamPort ----------
$ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $UpstreamPort -WarningAction SilentlyContinue
if (-not $ok.TcpTestSucceeded) {
    Die ("Nothing answers on 127.0.0.1:$UpstreamPort. In Ubuntu set WEB_PORT=127.0.0.1:$UpstreamPort " +
         "in /opt/fireboard/.env, run: sudo docker compose up -d, then run this again.")
}
Write-Log "[OK] WSL website answers on 127.0.0.1:$UpstreamPort"

# ---------- 3. Get caddy.exe (official download) ----------
if (-not (Test-Path $Exe)) {
    Write-Log "Downloading Caddy for Windows ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zipUrl = "https://caddyserver.com/api/download?os=windows&arch=amd64"
    try { Invoke-WebRequest -Uri $zipUrl -OutFile $Exe -UseBasicParsing -ErrorAction Stop }
    catch { Remove-Item $Exe -ErrorAction SilentlyContinue; Die "Download failed. Download caddy.exe yourself from https://caddyserver.com/download (Windows amd64) and put it in $Dir" }
}
$ver = cmd /c "`"$Exe`" version 2>&1"
Write-Log "[OK] Caddy $ver"

# ---------- 4. Caddyfile ----------
$UpPath = "127.0.0.1:$UpstreamPort"
$DataFwd = $Data -replace '\\', '/'
$LogFwd  = ($Logs -replace '\\', '/') + "/access.log"
$caddyfile = @"
# Created by windows_caddy_setup.ps1 - run the script again to change it.
{
	admin off
	local_certs
	skip_install_trust
	auto_https disable_redirects
	storage file_system $DataFwd
	default_sni $ListenIp
	servers :$Port {
		listener_wrappers {
			http_redirect
			tls
		}
	}
}

https://localhost:$Port, https://127.0.0.1:$Port, https://$ListenIp`:$Port {
	encode gzip
	header -Server
	log {
		output file $LogFwd {
			roll_size 20MiB
			roll_keep 10
		}
	}
	# The WSL website (its own HTTPS on this PC only). The connection never leaves this PC.
	reverse_proxy https://$UpPath {
		# Keep the address the colleague typed (e.g. 192.168.0.98:8000); without this the
		# WSL side would see 127.0.0.1:8443, not recognise it and answer with an empty page.
		header_up Host {hostport}
		transport http {
			tls_insecure_skip_verify
			tls_server_name localhost
		}
	}
}
"@
Set-Content -Path $Conf -Value $caddyfile -Encoding ascii
cmd /c "`"$Exe`" validate --config `"$Conf`" --adapter caddyfile >> `"$Log`" 2>&1"
if ($LASTEXITCODE -ne 0) { Die "Caddyfile check failed - see $Log" }
Write-Log "[OK] Caddyfile written: $Conf"

# ---------- 5. Turn off the old port proxy ----------
if (Get-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $OldTask | Out-Null
    Write-Log "[OK] Old task '$OldTask' disabled (run with -Remove to turn it back on)."
}
foreach ($line in (netsh interface portproxy show v4tov4)) {
    if ($line -match '^\s*(\S+)\s+(\d+)\s+\S+\s+\d+\s*$' -and $Matches[2] -eq "$Port") {
        netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$($Matches[1]) | Out-Null
        Write-Log "[OK] Port proxy $($Matches[1]):$Port removed."
    }
}

# ---------- 6. Windows service (starts at power-on, restarts if it stops) ----------
Remove-CaddyService
$bin = "$Exe run --config $Conf --adapter caddyfile"     # no spaces in the paths (checked above)
& sc.exe create $Service binPath= $bin start= delayed-auto DisplayName= "Fireboard HTTPS (Caddy)" | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Could not create the service $Service" }
& sc.exe description $Service "Fire Board Estimator: HTTPS on port $Port, forwards to WSL 127.0.0.1:$UpstreamPort" | Out-Null
& sc.exe failure $Service reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
New-Item -ItemType Directory -Force -Path $Data | Out-Null
# certificates and private keys: only SYSTEM and administrators
& icacls $Data /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
Start-Service -Name $Service -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
if ((Get-Service -Name $Service).Status -ne "Running") { Die "Service $Service did not start. Check $Logs and Windows Event Viewer." }
Write-Log "[OK] Service $Service running."

# ---------- 7. Check and copy the root certificate for colleagues' PCs ----------
$root = Join-Path $Data "pki\authorities\local\root.crt"
for ($i = 0; $i -lt 15 -and -not (Test-Path $root); $i++) { Start-Sleep -Seconds 2 }
if (Test-Path $root) {
    $pub = Join-Path $Dir "fireboard-root.crt"
    Copy-Item $root $pub -Force
    Write-Log "[OK] Root certificate for colleagues: $pub  (install it on each PC, see README_https.txt)"
} else {
    Write-Log "[CHECK] Root certificate not created yet. Open https://$ListenIp`:$Port once, then look in $Data\pki\authorities\local"
}
$t = Test-NetConnection -ComputerName $ListenIp -Port $Port -WarningAction SilentlyContinue
if ($t.TcpTestSucceeded) { Write-Log "[OK] Port $Port is open. Open https://$ListenIp`:$Port" }
else { Write-Log "[CHECK] Port $Port does not answer yet. Check $Logs\access.log and the firewall rule 'Fireboard $Port'." }
exit 0

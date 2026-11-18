#!/bin/sh
# 防火板計價系統：在 WSL Ubuntu 安裝（由 .run 安裝檔自動執行，參數 = 解壓後的資料夾）
set -eu

SRC="$1"
APP_DIR=/opt/fireboard
OPS_DIR=/mnt/c/fireboard_ops
BACKUP_DIR=/mnt/c/fireboard_backup
PORT=8000
VERSION=$(cat "$SRC/VERSION")

# 自動安裝（Windows 安裝程式 FireboardSetup.exe 使用）：
# FB_ENV_FILE 指向設定檔，可設定 FB_LOCAL_ONLY（y / n）、FB_HOSTS、FB_BACKUP_WIN、FB_OPS_WIN。
# 有設定 FB_LOCAL_ONLY 時不會詢問任何問題。
if [ -n "${FB_ENV_FILE:-}" ]; then
    [ -f "$FB_ENV_FILE" ] || { echo "[錯誤] 找不到設定檔 $FB_ENV_FILE" >&2; exit 1; }
    sed 's/\r$//' "$FB_ENV_FILE" > /tmp/fireboard-install.env
    . /tmp/fireboard-install.env
    rm -f /tmp/fireboard-install.env
fi
FB_LOCAL_ONLY=${FB_LOCAL_ONLY:-}
FB_HOSTS=${FB_HOSTS:-}
[ -z "${FB_BACKUP_WIN:-}" ] || BACKUP_DIR=$(wslpath -u "$FB_BACKUP_WIN")
[ -z "${FB_OPS_WIN:-}" ] || OPS_DIR=$(wslpath -u "$FB_OPS_WIN")
PROGRESS_FILE=""
[ -z "${FB_PROGRESS_WIN:-}" ] || PROGRESS_FILE=$(wslpath -u "$FB_PROGRESS_WIN")

# 進度（給 Windows 安裝程式顯示百分比）：progress <百分比> <步驟代號>
progress() {
    if [ -n "$PROGRESS_FILE" ]; then printf '%s %s\n' "$1" "$2" > "$PROGRESS_FILE" || true; fi
}

say() { printf '\n>> %s\n' "$*"; }
die() { printf '\n[錯誤] %s\n' "$*" >&2; exit 1; }
rand() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

say "防火板計價系統安裝（版本 $VERSION）"
progress 34 prepare

# ---------- 1. 檢查環境 ----------
[ "$(ps -p 1 -o comm= | tr -d ' ')" = "systemd" ] || die "WSL 未開啟 systemd。
   請在 Ubuntu 執行：printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf
   再在 PowerShell 執行：wsl --shutdown，然後重新執行安裝檔。"
[ -d /mnt/c ] || die "找不到 /mnt/c。這個安裝檔要在 Windows 的 WSL Ubuntu 內執行。"
if docker volume inspect fireboard_pgdata >/dev/null 2>&1; then
    die "這部電腦已有防火板系統的數據（Docker volume fireboard_pgdata）。為免覆蓋數據，安裝已停止。"
fi
[ ! -e "$APP_DIR/docker-compose.yml" ] || die "$APP_DIR 已有系統檔案。為免覆蓋，安裝已停止。"

# ---------- 2. Docker Engine ----------
if ! command -v docker >/dev/null 2>&1; then
    say "安裝 Docker Engine（需要互聯網，約 2 至 5 分鐘）"
    command -v curl >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq curl; } \
        || die "未能安裝 curl。請先執行 sudo apt-get update，修正錯誤後再試。"
    curl -fsSL https://get.docker.com | sh || die "Docker 安裝失敗。請先執行 sudo apt-get update，修正錯誤後再試。"
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "Docker 未能啟動。請執行 systemctl status docker 查看原因。"
command -v curl >/dev/null 2>&1 || apt-get install -y -qq curl >/dev/null 2>&1 || true

# ---------- 3. 使用範圍及網站地址 ----------
if [ -n "$FB_LOCAL_ONLY" ]; then
    LOCAL="$FB_LOCAL_ONLY"
else
    printf '\n只限這部電腦使用？其他電腦將不能打開網站。\n輸入 y = 只限本機；直接按 Enter = 公司網絡可用：'
    LOCAL=""
    read -r LOCAL || true
fi
case "$LOCAL" in
    y|Y|yes|YES)
        LOCAL_ONLY=1
        WEB_BIND="127.0.0.1:$PORT"
        ALLOWED="localhost,127.0.0.1"
        ;;
    *)
        LOCAL_ONLY=0
        WEB_BIND="$PORT"
        WIN_IP=$(powershell.exe -NoProfile -Command '(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1).IPv4Address.IPAddress' 2>/dev/null | tr -d '\r' | head -n 1) || WIN_IP=""
        WIN_NAME=$(hostname)
        DEFAULT=$(printf '%s,%s' "$WIN_IP" "$WIN_NAME" | sed 's/^,//; s/,$//')
        if [ -n "$FB_LOCAL_ONLY" ]; then
            HOSTS="$FB_HOSTS"
        else
            printf '\n同事用甚麼地址打開網站（這部電腦的 IP 或名稱，多個用逗號分隔）\n直接按 Enter 使用 [%s]：' "$DEFAULT"
            HOSTS=""
            read -r HOSTS || true
        fi
        [ -n "$HOSTS" ] || HOSTS="$DEFAULT"
        HOSTS=$(printf '%s' "$HOSTS" | tr -d ' ')
        ALLOWED="localhost,127.0.0.1${HOSTS:+,$HOSTS}"
        ;;
esac
ORIGINS=$(printf '%s\n' "$ALLOWED" | tr ',' '\n' | sed '/^$/d' | sed "s|.*|http://&:$PORT|" | paste -sd, -)

# ---------- 4. 程式設定 ----------
say "建立 $APP_DIR"
progress 38 prepare
mkdir -p "$APP_DIR"
cp "$SRC/docker-compose.yml" "$SRC/backup_fireboard.sh" "$SRC/VERSION" "$APP_DIR/"
umask 077
cat > "$APP_DIR/.env" <<EOF
# 由安裝檔產生（$VERSION）。不要放入 git 或傳給他人。
DJANGO_SECRET_KEY=$(rand 50)
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$ALLOWED
DJANGO_CSRF_TRUSTED_ORIGINS=$ORIGINS
POSTGRES_DB=fireboard
POSTGRES_USER=fireboard
POSTGRES_PASSWORD=$(rand 32)
POSTGRES_HOST=db
POSTGRES_PORT=5432
WEB_PORT=$WEB_BIND
EOF
umask 022
chown -R root:root "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 700 "$APP_DIR/backup_fireboard.sh"
sed -i "s|^BACKUP_DIR=.*|BACKUP_DIR=\"$BACKUP_DIR\"      # 由安裝檔設定|" "$APP_DIR/backup_fireboard.sh"

# ---------- 5. Docker image ----------
say "載入 Docker image（約 1 至 3 分鐘）"
progress 42 load_images
docker load -i "$SRC/images.tar" || die "載入 Docker image 失敗。"

# ---------- 6. 數據庫及數據 ----------
cd "$APP_DIR"
say "啟動數據庫"
progress 60 start_db
docker compose up -d db
i=0
until docker compose exec -T db sh -c 'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -lt 90 ] || die "數據庫未能啟動。請執行：cd $APP_DIR && docker compose logs db"
    sleep 2
done

say "還原數據"
progress 65 restore
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$SRC/db.dump" \
    || die "還原數據失敗。請把以上訊息交給系統管理員。"

# ---------- 7. 網站 ----------
say "啟動網站（約 1 分鐘）"
progress 75 start_web
docker compose up -d web
i=0
until curl -fsS -o /dev/null "http://localhost:$PORT/accounts/login/" 2>/dev/null; do
    i=$((i + 1))
    [ "$i" -lt 90 ] || die "網站未能啟動。請執行：cd $APP_DIR && docker compose logs web"
    sleep 2
done

# ---------- 8. 每小時備份 ----------
progress 84 backup_job
say "設定每小時備份到 ${FB_BACKUP_WIN:-C:\\fireboard_backup}"
mkdir -p "$BACKUP_DIR"
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'backup_fireboard.sh' > "$CRON_TMP" || true
echo "5 * * * * $APP_DIR/backup_fireboard.sh" >> "$CRON_TMP"
crontab "$CRON_TMP"
rm -f "$CRON_TMP"
systemctl enable --now cron >/dev/null 2>&1 || true

# ---------- 9. Windows 設定檔 ----------
mkdir -p "$OPS_DIR"
cp "$SRC/windows_setup.ps1" "$SRC/wsl_portproxy.ps1" "$SRC/README_install.txt" "$OPS_DIR/"

if [ "$LOCAL_ONLY" = 1 ]; then
    SCOPE="只限這部電腦（其他電腦不能連入）"
    NEXT="設定開機自動啟動"
else
    SCOPE="公司網絡可用"
    NEXT="讓其他電腦連入，並在開機時自動啟動"
fi

say "安裝完成（版本 $VERSION）"
cat <<EOF

   使用範圍：  $SCOPE
   本機測試：  http://localhost:$PORT
   帳戶和密碼：與原本電腦相同

   最後一步（$NEXT）：
   以系統管理員身分開 PowerShell，執行：
     powershell -ExecutionPolicy Bypass -File C:\\fireboard_ops\\windows_setup.ps1

   安裝檔內有全部數據，完成後請刪除安裝檔。
EOF

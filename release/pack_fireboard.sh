#!/bin/sh
# ============================================================
#  防火板計價系統：製作單一安裝檔（在現有的正式系統上執行）
#
#  用法（Ubuntu）：sudo sh /opt/fireboard/release/pack_fireboard.sh
#  產生：C:\fireboard_release\fireboard-install-YYYY-MM-DD_HHMM.run
#
#  安裝檔包括：已建好的網站 image、PostgreSQL image、全部數據
#  （材料、價錢、配方、用戶、報價、紀錄）、備份腳本和 Windows 設定檔。
#  不包括 .env（新電腦會產生新的密鑰和數據庫密碼）。
# ============================================================
set -eu

APP_DIR=/opt/fireboard
REL="$APP_DIR/release"
OUT_DIR=/mnt/c/fireboard_release

die() { printf '\n[錯誤] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "請用 sudo 執行：sudo sh $0"
cd "$APP_DIR"
docker info >/dev/null 2>&1 || die "Docker 未運行。"
[ -n "$(docker compose ps -q --status running db)" ] || die "數據庫未運行。請先執行：docker compose up -d"
[ -n "$(docker compose ps -q --status running web)" ] || die "網站未運行。請先執行：docker compose up -d"
for f in docker-compose.release.yml installer_header.sh install.sh windows_setup.ps1 README_install.txt; do
    [ -f "$REL/$f" ] || die "缺少 $REL/$f"
done
for f in backup_fireboard.sh wsl_portproxy.ps1; do
    [ -f "$APP_DIR/$f" ] || die "缺少 $APP_DIR/$f"
done

STAMP=$(date +%Y-%m-%d_%H%M)
TAG="fireboard-web:$STAMP"
WORK=$(mktemp -d /tmp/fireboard-pack.XXXXXX)
trap 'rm -rf "$WORK"' EXIT INT TERM
P="$WORK/payload"
mkdir "$P"

echo ">> 1/5 標記現正運行的網站 image：$TAG"
# 用容器建立時的 image 名稱（例如 fireboard-web）；新版 Docker（containerd 儲存）不接受用 sha256 編號標記
WEB_CID=$(docker compose ps -q web)
WEB_REF=$(docker inspect --format '{{.Config.Image}}' "$WEB_CID")
docker tag "$WEB_REF" "$TAG" 2>/dev/null \
    || docker tag "$(docker inspect --format '{{.Image}}' "$WEB_CID")" "$TAG" \
    || die "未能標記網站 image（$WEB_REF）。請先執行：cd $APP_DIR && docker compose up -d --build"
PG_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$(docker compose ps -q db)")

echo ">> 2/5 匯出數據庫"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$P/db.dump" \
    || die "pg_dump 失敗"
docker compose exec -T db pg_restore --list < "$P/db.dump" >/dev/null 2>&1 \
    || die "數據庫匯出檔損壞"

echo ">> 3/5 匯出 Docker image（$TAG、$PG_IMAGE，約 1 至 3 分鐘）"
docker save -o "$P/images.tar" "$TAG" "$PG_IMAGE"

echo ">> 4/5 加入安裝檔案"
sed -e "s|@WEB_IMAGE@|$TAG|" -e "s|@PG_IMAGE@|$PG_IMAGE|" -e 's/\r$//' \
    "$REL/docker-compose.release.yml" > "$P/docker-compose.yml"
for f in install.sh README_install.txt; do sed 's/\r$//' "$REL/$f" > "$P/$f"; done
sed 's/\r$//' "$APP_DIR/backup_fireboard.sh" > "$P/backup_fireboard.sh"
cp "$REL/windows_setup.ps1" "$APP_DIR/wsl_portproxy.ps1" "$P/"
echo "$STAMP" > "$P/VERSION"

echo ">> 5/5 製作安裝檔（壓縮需時數分鐘）"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/fireboard-install-$STAMP.run"
sed 's/\r$//' "$REL/installer_header.sh" > "$OUT.tmp"
tar -C "$P" -czf - . >> "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
( cd "$OUT_DIR" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
FILES=$(docker run --rm --entrypoint ls "$TAG" -A /app | tr '\n' ' ')
docker rmi "$TAG" >/dev/null 2>&1 || true

SIZE=$(du -h "$OUT" | cut -f1)
cat <<EOF

完成：C:\\fireboard_release\\fireboard-install-$STAMP.run（$SIZE）

網站 image 內的檔案（請確認沒有不應帶走的檔案，例如 Excel、數據匯出檔）：
$FILES

安裝檔內有全部數據（包括價錢和用戶帳戶），請小心保管，不要電郵或放在共用資料夾。
EOF

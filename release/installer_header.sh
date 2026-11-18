#!/bin/sh
# 防火板計價系統安裝檔（自動解壓）。用法：sudo sh fireboard-install-XXXX.run
set -eu
[ "$(id -u)" = 0 ] || { echo "請用 sudo 執行：sudo sh $0"; exit 1; }
LINE=$(awk '/^__PAYLOAD_BELOW__$/ { print NR + 1; exit 0 }' "$0")
TMP=$(mktemp -d /tmp/fireboard-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT INT TERM
echo ">> 解壓安裝檔（約 1 分鐘）..."
tail -n +"$LINE" "$0" | tar -xz -C "$TMP" || { echo "[錯誤] 安裝檔損壞，請重新複製。"; exit 1; }
sh "$TMP/install.sh" "$TMP"
exit 0
__PAYLOAD_BELOW__

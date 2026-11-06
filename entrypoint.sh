#!/bin/sh
set -e

echo ">> 等待數據庫"
python wait_for_db.py

echo ">> 更新數據庫結構"
python manage.py migrate --noinput

echo ">> 收集靜態檔案"
python manage.py collectstatic --noinput

echo ">> 載入初始數據（只新增，不覆蓋）"
python manage.py seed_data

echo ">> 啟動網站"
# gthread：每個 worker 用多個線程處理連線。瀏覽器預先開啟但閒置的連線
# 不會再佔用整個 worker，避免 WORKER TIMEOUT 和偶發的 Internal Server Error。
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --worker-class gthread --workers 2 --threads 4 \
  --timeout 60 --keep-alive 5 \
  --access-logfile -

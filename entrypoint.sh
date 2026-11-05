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
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -

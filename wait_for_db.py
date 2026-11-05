"""啟動前等待 PostgreSQL 可以連接，並把常見問題用中文顯示出來。"""
import os
import socket
import sys
import time

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))

if not os.environ.get("POSTGRES_DB"):
    print(">> 未設定 POSTGRES_DB，使用 SQLite，跳過等待數據庫")
    sys.exit(0)

for attempt in range(1, 31):
    try:
        addr = socket.gethostbyname(host)
    except socket.gaierror as e:
        print(f">> [{attempt}/30] 找不到數據庫主機「{host}」（{e}）")
        time.sleep(2)
        continue
    try:
        with socket.create_connection((addr, port), timeout=3):
            print(f">> 數據庫已可連接：{host} ({addr}:{port})")
            sys.exit(0)
    except OSError as e:
        print(f">> [{attempt}/30] 已找到 {host} ({addr})，但未能連接埠 {port}：{e}")
        time.sleep(2)

print(f""">> 等待 60 秒後仍未能連接數據庫「{host}:{port}」。請檢查：
   1. .env 的 POSTGRES_HOST 是否為 db
   2. 執行 docker compose ps，db 是否顯示 healthy
   3. 執行 docker compose down 再 docker compose up -d --build（不要加 -v）
   4. 重新啟動 Docker Desktop""")
sys.exit(1)

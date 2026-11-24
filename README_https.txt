防火板計價系統 - HTTPS（加密連線）說明
==========================================

網站現在經 Caddy 用 HTTPS 加密，登入密碼和報價資料在公司網絡上不會再以明文傳送。

網址
----
  正式版：https://192.168.0.98:8000   （埠號不變，只是 http 改成 https）
  測試版：https://localhost:8001
  打 http:// 也可以，會自動轉去 https://。

.env 要加的設定（只在正式版 /opt/fireboard/.env）
-------------------------------------------------
  FB_SERVER_NAME=192.168.0.98
  （同事打開網站用的 IP。沒有填會用 127.0.0.1，同事會見到憑證錯誤。）
  測試版 C:\fireboard\.env 不用填。

為甚麼瀏覽器會說「不安全」/「你的連線不是私人連線」
-------------------------------------------------
憑證由 Caddy 自己的「私人 CA」發出，瀏覽器未認識它。
連線其實已經加密，但要在每部電腦安裝一次「根憑證」，瀏覽器才會信任，警告才會消失。

1. 取出根憑證（在正式版的 Ubuntu 執行一次）
   cd /opt/fireboard
   sudo docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt /mnt/c/fireboard_backup/fireboard-root.crt
   → 檔案在 Windows 的 C:\fireboard_backup\fireboard-root.crt
   這個檔案只是「公開」的根憑證，可以複製給同事；不要複製 caddy 的其他檔案。

2. 在每部電腦安裝（包括你自己的電腦）
   a. 雙擊 fireboard-root.crt → 「安裝憑證」
   b. 存放位置選「本機電腦」→ 下一步（需要管理員權限）
   c. 選「將所有憑證放入以下的存放區」→ 瀏覽 → 「受信任的根憑證授權單位」→ 確定
   d. 下一步 → 完成 → 關閉所有瀏覽器視窗再開
   Chrome 和 Edge 會用 Windows 的憑證。Firefox：在網址列打 about:config，
   把 security.enterprise_roots.enabled 設為 true。

3. 測試版（localhost:8001）有自己的根憑證，在 C:\fireboard 執行：
   docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt C:\fireboard_backup\fireboard-test-root.crt
   只需安裝在你自己的電腦。

做了步驟 5（Windows 版 Caddy）之後
-------------------------------
同事連入的是 Windows 版 Caddy，根憑證改為 C:\fireboard_caddy\fireboard-root.crt，
上面第 1 步的檔案不用再發給同事。安裝方法（第 2 步）一樣。

注意
----
- 不要刪除 Docker volume「caddy_data」，否則會產生新的根憑證，各電腦要重新安裝。
- 舊書籤 http://192.168.0.98:8000 仍然可用，會自動轉去 https://。

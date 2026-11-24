防火板計價系統 - 安全加強（步驟 1 至 4）
==========================================

步驟 1  HTTPS 加密連線
  - 新增 Caddy（docker-compose.yml 的 caddy），網址改為 https://，埠號不變。
  - 網站（web）不再直接對外開放，只經 Caddy 連入。
  - 登入 cookie 只經加密連線傳送（SESSION_COOKIE_SECURE、CSRF_COOKIE_SECURE）。
  - 詳情及安裝根憑證：README_https.txt

步驟 2  登入失敗次數限制
  - 同一帳戶 15 分鐘內錯 5 次 → 鎖定 15 分鐘（一般登入頁和系統管理登入頁都適用）。
  - 解鎖：等 15 分鐘，或在「系統管理 → 登入失敗紀錄」刪除該帳戶的紀錄。
  - 次數和時間可在 config/settings.py 修改：FB_LOGIN_MAX_FAILURES、FB_LOGIN_LOCK_MINUTES。

步驟 3  網站不用 root 執行
  - 網站容器以普通用戶 app 執行，並移除所有 Linux 特權（cap_drop: ALL、no-new-privileges）。
  - 在容器內安裝工具要加 --user，例如：
      docker compose exec web pip install --user bandit pip-audit
      docker compose exec web python -m bandit -r estimator history quotes config -x "*/tests.py,*/migrations/*"
      docker compose exec web python -m pip_audit

步驟 4  限制誰可以連入
  a. 防火牆（正式版電腦，系統管理員 PowerShell）：
       powershell -ExecutionPolicy Bypass -File C:\fireboard\firewall_fireboard.ps1
     只容許公司網絡（例如 192.168.0.0/24）連入 8000，VPN 網絡不可以。
  b. 測試版只給自己的電腦用：C:\fireboard\.env 改為
       WEB_PORT=127.0.0.1:8001
  c. 路由器：確認沒有把 8000（或任何埠號）轉發到這部電腦
     （路由器設定頁的「Port Forwarding / 虛擬伺服器 / NAT」不應有這部電腦的 IP）。
  d. 「/admin/ 只限你的電腦」做不到：同事經 Windows port proxy 連入，
     網站見到所有人的 IP 都一樣。改為：只給少數人系統管理權限，並用強密碼。

步驟 5  記錄同事的真正 IP（Windows 版 Caddy 取代 port proxy）
  為甚麼：port proxy 轉發時會換成 Windows 自己的 IP，網站見到所有人都一樣。
  Windows 版 Caddy 直接接收同事的連線，把真正的 IP 傳給網站。

    同事 --https--> Windows Caddy（埠 8000）--> WSL 網站（只開 127.0.0.1:8443）

  安裝（次序很重要）：
  a. Ubuntu：/opt/fireboard/.env 把 WEB_PORT 改為
       WEB_PORT=127.0.0.1:8443
     並加一行（容許 Windows Caddy 傳入真正 IP；未做步驟 5 不要加，否則 IP 可被偽造）：
       FB_TRUSTED_PROXIES=private_ranges
     然後：cd /opt/fireboard && sudo docker compose up -d
     （這時同事暫時連不到，直至做完 b）
  b. Windows（系統管理員 PowerShell，先關 VPN）：
       powershell -ExecutionPolicy Bypass -File C:\fireboard\windows_caddy_setup.ps1
     它會：下載 caddy.exe、建立 C:\fireboard_caddy、停用排程「Fireboard Port 8000」、
     刪除 port proxy、建立 Windows 服務「FireboardCaddy」（開機自動啟動、停了會自動重啟）。
  c. 根憑證：同事電腦要改裝 C:\fireboard_caddy\fireboard-root.crt
     （步驟 1 的 WSL 根憑證只剩 Windows Caddy 自己用，同事不再需要）。
  d. 檢查：系統管理 → 登入失敗紀錄 的 IP 欄、以及 C:\fireboard_caddy\logs\access.log。

  還原（回到 port proxy）：
       powershell -ExecutionPolicy Bypass -File C:\fireboard\windows_caddy_setup.ps1 -Remove
     然後 Ubuntu 的 .env 改回 WEB_PORT=8000，sudo docker compose up -d。

  注意：
  - 這部電腦的 IP 改變（例如 DHCP）就要再執行一次 b。建議請 IT 在路由器固定這個 IP。
  - 不要刪除 C:\fireboard_caddy\data（裏面是憑證；刪除後各電腦要重新安裝根憑證）。

步驟 6  安全事件紀錄（系統管理 → 安全事件紀錄）
  記錄被拒絕的可疑操作：時間、類別、帳戶、IP、網址、Origin、Referer、瀏覽器、原因。
    CSRF 驗證失敗      其他網頁送資料過來，或表格暗碼不符
    不容許的網址       用不在 DJANGO_ALLOWED_HOSTS 的地址打開網站（Bad Request 400）
    權限不足           已登入但打開沒有權限的頁面（403），例如沒有價錢權限的人打開價錢頁
    帳戶被鎖定         登入失敗太多次，開始鎖定
    鎖定期間嘗試登入   鎖定期間再嘗試
  - 同一來源 1 分鐘內重複的同一事件只記一次；保留 180 天。
  - 只可查看；只有超級用戶可以刪除。
  - IP：做了步驟 5 才是同事的真正 IP，否則都是同一個 Windows IP。

步驟 7  使用紀錄（系統管理 → 使用紀錄）
  每筆：時間、帳戶、IP、動作、方式、網址、結果（HTTP 狀態，例如 200 成功、403 沒有權限）、內容、瀏覽器。
  記錄的動作：
    登入、登出、登入失敗
    計算（選了甚麼系統、面積等）、匯出／下載（Excel、範本、匯入檔、報價）
    查看價錢、更新價錢、Excel 匯入、新增材料
    報價：儲存、發出、取消、修訂、修改／刪除／移動項目
    系統管理：新增、修改、刪除（包括改了哪些欄位）
    其他送出資料的操作
  - 一般瀏覽頁面不記錄；密碼、表格暗碼不記錄。
  - 保留 365 天（config/settings.py 的 FB_ACTIVITY_KEEP_DAYS）。
  - 只可查看；可選取後「匯出所選紀錄（CSV）」用 Excel 打開；只有超級用戶可以刪除。
  - IP：做了步驟 5 才是同事的真正 IP。

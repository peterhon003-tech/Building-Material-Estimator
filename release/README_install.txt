防火板計價系統 — 新電腦安裝說明（Windows + WSL Docker Engine）
=================================================================

安裝檔：fireboard-install-YYYY-MM-DD_HHMM.run
內容：網站程式（已打包）、PostgreSQL、全部數據（材料、價錢、配方、用戶帳戶、報價、紀錄）。
安裝後的帳戶和密碼與原本電腦相同。安裝檔內有全部數據，完成後請刪除。

一、準備（新電腦，只需做一次）
-------------------------------
1. 以系統管理員身分開 PowerShell，安裝 WSL 和 Ubuntu，完成後重新開機：
     wsl --install -d Ubuntu
   重新開機後打開 Ubuntu，設定 Linux 帳戶和密碼。

2. 開啟 systemd：在 Ubuntu 執行
     printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf
   然後在 PowerShell 執行：
     wsl --shutdown

3. 如果這部電腦有 Docker Desktop：
   關閉它，並在 Settings > General 取消「Start Docker Desktop when you sign in」，
   以免和本系統爭用 8000 端口。

二、安裝
--------
1. 把安裝檔複製到 C:\fireboard_release\

2. 打開 Ubuntu，執行（檔名換成實際名稱）：
     sudo sh /mnt/c/fireboard_release/fireboard-install-YYYY-MM-DD_HHMM.run
   - 未有 Docker 會自動安裝（需要互聯網）
   - 會問「只限這部電腦使用？」：
       輸入 y   = 只有這部電腦可以打開網站（http://localhost:8000），其他電腦連不到
       直接 Enter = 公司網絡內的電腦都可以打開，之後會再問網站地址，按 Enter 用建議值即可
   - 完成後本機可打開 http://localhost:8000

3. 以系統管理員身分開 PowerShell（用同一個 Windows 帳戶），執行：
     powershell -ExecutionPolicy Bypass -File C:\fireboard_ops\windows_setup.ps1
   會要求輸入 Windows 密碼（不是 PIN），用來設定開機自動啟動。

4. 測試：重新開機、不要登入，等 3 分鐘，用另一部電腦打開 http://這部電腦的IP:8000

三、安裝後
----------
- 程式及設定：Ubuntu 內的 /opt/fireboard（只有 root 可修改）
- 備份：每小時自動備份到 C:\fireboard_backup\daily，結果見 backup.log
- 端口轉駁紀錄：C:\fireboard_ops\wsl_portproxy.log
- 常用指令（Ubuntu）：
    cd /opt/fireboard
    sudo docker compose ps              查看狀態
    sudo docker compose logs -f web     查看網站紀錄
    sudo docker compose restart web     重啟網站
- 原本的電腦：確認新電腦正常後，停止原本的系統，避免兩邊數據不一致。

四、常見問題
------------
- 「WSL 未開啟 systemd」：做「一、2」，再重新執行安裝檔。
- 「已有防火板系統的數據」：這部電腦已安裝過，安裝檔不會覆蓋。要重新安裝請先聯絡系統管理員。
- 「Docker 安裝失敗」：在 Ubuntu 執行 sudo apt-get update，看有沒有 E: 開頭的錯誤。
- 其他電腦打不開：看 C:\fireboard_ops\wsl_portproxy.log 最後一行是否 [OK]；
  確認這部電腦 IP 在 .env 的 DJANGO_ALLOWED_HOSTS 內（sudo nano /opt/fireboard/.env，
  改完執行 cd /opt/fireboard && sudo docker compose up -d）。

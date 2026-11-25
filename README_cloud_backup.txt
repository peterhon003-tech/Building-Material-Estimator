防火板計價系統 - 加密備份到 Google Drive（rclone）
================================================

運作方式
--------
  每小時 :05  backup_fireboard.sh      備份資料庫到 C:\fireboard_backup\daily（及 monthly）
  每小時 :15  cloud_backup_fireboard.sh 把新備份「加密」後上載到 Google Drive
  - Google Drive 上的檔名和內容都是亂碼，沒有你的加密密碼打不開。
  - Google Drive 保留：每日備份 30 天、每月備份 400 天（腳本開頭可改）。
  - 本機備份不受影響；上載失敗只寫入 backup.log，不會影響網站或本機備份。

一次性設定（正式版 Ubuntu，約 15 分鐘）
---------------------------------------
1. 安裝 rclone
     sudo -v ; curl https://rclone.org/install.sh | sudo bash
     rclone version

2. 連接 Google Drive（遠端名稱一定要叫 gdrive）
     sudo rclone config
   依次回答：
     n                       （New remote）
     name>  gdrive
     Storage>  drive         （Google Drive）
     client_id> 直接 Enter    client_secret> 直接 Enter
     scope>  drive.file      （只可存取 rclone 自己建立的檔案，最安全）
     service_account_file> 直接 Enter
     Edit advanced config?  n
     Use web browser to automatically authenticate?  y
       → 畫面會顯示 http://127.0.0.1:53682/auth?state=... ，
         把整條網址複製到 Windows 的瀏覽器打開，登入「公司」的 Google 帳戶，按「允許」。
         瀏覽器顯示 Success 後回到 Ubuntu。
     Configure this as a Shared Drive?  n
     Keep this "gdrive" remote?  y

3. 建立加密層（遠端名稱一定要叫 gdrive-crypt）
     n
     name>  gdrive-crypt
     Storage>  crypt
     remote>  gdrive:fireboard_backup_encrypted
     filename_encryption>  standard
     directory_name_encryption>  true
     Password or pass phrase for encryption>  y  → 輸入你自己的加密密碼兩次
     Password or pass phrase for salt>        y  → 輸入另一個不同的密碼兩次
     Edit advanced config?  n
     Keep this "gdrive-crypt" remote?  y
     q                       （Quit）

   *** 立即把兩個密碼寫在紙上，放在安全的地方（例如公司保險箱），另存一份在密碼管理工具。***
   *** 密碼遺失 = Google Drive 上的備份永遠打不開。不要只存在這部伺服器上。         ***

4. 保護設定檔（裏面有連接 Google 的資料）
     sudo chmod 600 /root/.config/rclone/rclone.conf
     sudo chmod 700 /opt/fireboard/cloud_backup_fireboard.sh

5. 第一次上載和測試
     sudo /opt/fireboard/cloud_backup_fireboard.sh          上載（第一次會上載最近 7 天）
     sudo /opt/fireboard/cloud_backup_fireboard.sh list     列出 Google Drive 上的備份（已解密的檔名）
     sudo /opt/fireboard/cloud_backup_fireboard.sh test     下載最新一個並檢查可以還原
   在 Google Drive 網頁會見到資料夾 fireboard_backup_encrypted，裏面的名稱都是亂碼 = 正確。

6. 每小時自動執行
     (sudo crontab -l; echo "15 * * * * /opt/fireboard/cloud_backup_fireboard.sh") | sudo crontab -
     sudo crontab -l          應該見到 :05 的 backup_fireboard.sh 和 :15 的 cloud_backup_fireboard.sh

日常檢查
--------
  C:\fireboard_backup\backup.log 最後幾行應有：
    [cloud] [OK] Uploaded. Google Drive now has N daily backup(s).
  出現 [cloud] [FAILED]：多數是沒有網絡，或 Google 登入過期
  （例如改了 Google 密碼）。重新登入：
    sudo rclone config reconnect gdrive:
  建議每月執行一次：sudo /opt/fireboard/cloud_backup_fireboard.sh test

還原（從 Google Drive 取回備份）
------------------------------
A. 伺服器仍然正常（Ubuntu）
   1. 看有哪些備份：
        sudo /opt/fireboard/cloud_backup_fireboard.sh list
   2. 下載並自動解密（換成你要的檔名）：
        sudo rclone copy gdrive-crypt:fireboard/daily/fireboard-2026-11-24_1005.dump /tmp/restore/
   3. 還原到資料庫（會覆蓋現有資料！先備份目前的資料庫；最好先在測試版試）：
        cd /opt/fireboard
        sudo /opt/fireboard/backup_fireboard.sh
        sudo docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < /tmp/restore/fireboard-2026-11-24_1005.dump
        sudo docker compose restart web

B. 伺服器壞了（在任何一部電腦）
   1. 安裝 rclone（Windows：https://rclone.org/downloads/ 下載 rclone.exe）。
   2. rclone config：照上面第 2、3 步，用「同一個」Google 帳戶，
      gdrive-crypt 用「同一個」remote（gdrive:fireboard_backup_encrypted）和「同樣的兩個密碼」。
   3. rclone copy gdrive-crypt:fireboard/daily/<檔名> <本機資料夾>  → 下載後已經解密。
   4. 新伺服器裝好系統後，按 A 的第 3 步還原。

注意
----
- 用「公司」的 Google 帳戶，不要用私人帳戶。
- rclone.conf 裏的密碼只是「混淆」不是加密；能以 root 登入伺服器的人可以讀到。
  所以要保護好伺服器的 Windows 帳戶，並 chmod 600 這個檔案。
- 伺服器要能上網才可以上載。

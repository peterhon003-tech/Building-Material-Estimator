# 防火板計價系統（第一版）

輸入 **品牌 → 系統 → 耐火時間**，計出每 m² 材料用量和每項價錢。

- 系統類型：**Enclosure for Ceiling**、**Enclosure for Gas Pipe**、**Partition**（Partition 未有數據）
- 數據：Promat · Enclosure for Ceiling / Gas Pipe · 1 / 2 / 4 小時。板、岩棉和鐵料規格根據 Easy Smart Promat Enclosure System 圖則 01-03-2024 及供應商報價單；槽鐵和角鐵按每 m² 固定支數（另加 10% 損耗）：

  | 每 m² 支數（未計損耗） | Ceiling | Gas Pipe |
  |---|---|---|
  | 槽鐵 | 1.0815 | 0.67 |
  | 連牆角鐵 | 0.8605 | 0.05 |
  | 連板角鐵 | 待定 | 1.36 |

  更新到這個版本時，migration 0004 會把現有 Enclosure 改名為 Enclosure for Ceiling 並更新槽鐵和連牆角鐵（管理員已手動改過的不會覆蓋）；Gas Pipe 系統由 seed_data 在啟動時自動建立。
- 技術：Django 5.2 + PostgreSQL 16，用 Docker Compose 部署
- Partition 和 Durasteel 之後在「系統管理」加入數據即可，不用改程式

---

## 1. 項目結構

```
fireboard/
├── docker-compose.yml        # 兩個容器：db (PostgreSQL) + web (Django)
├── Dockerfile                # web 容器
├── entrypoint.sh             # 啟動時：更新數據庫 → 收集靜態檔 → 載入初始數據 → 啟動網站
├── requirements.txt
├── .env.example              # 設定範本，複製成 .env
├── manage.py
├── config/                   # Django 設定
│   ├── settings.py
│   └── urls.py
├── estimator/                # 主程式
│   ├── calc.py               # 計算公式（純 Python）
│   ├── models.py             # 數據表：材料、價錢、系統、組件
│   ├── services.py           # 計價流程：找配方 → 計用量 → 配價錢
│   ├── views.py              # 頁面：計價、原料價錢、價錢紀錄、更新價錢
│   ├── admin.py              # 系統管理（設定配方）
│   ├── price_import.py       # Excel 範本產生及讀取（價錢、新增 / 修改 / 停用材料）
│   ├── export.py             # 計價結果匯出 Excel
│   ├── seed.py               # 初始材料、價錢、配方數據
│   ├── management/commands/seed_data.py
│   ├── migrations/0001_initial.py
│   └── tests.py
├── history/                  # 自動計價紀錄（附加功能，見第 14 節）
├── quotes/                   # 報價（附加功能，見第 15 節）
└── templates/                # 網頁（中文介面）
```

### 數據表

| 表 | 內容 | 誰可以改 |
|---|---|---|
| Material 材料 | 名稱、規格、計價單位、每單位涵蓋量（板 2.9768 m²、鐵 2.44 m、岩棉 0.72 m²） | 系統管理員 |
| MaterialPrice 價錢 | 單價、供應商、生效日期、修改人（只新增，不覆蓋） | 價錢管理員 |
| FireSystem 系統 | 品牌、系統、耐火時間、F.R.R.、測試報告、總厚度 | 系統管理員 |
| SystemComponent 組件 | 每個系統的材料、計算方式、層數、間距、損耗 % | 系統管理員 |

### 計算方式

| 計算方式 | 用於 | 每 m² 用量 |
|---|---|---|
| 按面積 | 板、岩棉 | 層數 × (1 + 損耗%) ÷ 每單位面積 |
| 按間距 | 槽鐵 @ c/c | (1 ÷ 間距) × (1 + 損耗%) ÷ 每支長度 |
| 固定數量 | 角鐵、螺絲、螺栓、人工 | 設定數量 × (1 + 損耗%) |

每 m² 價錢 = 每 m² 用量 × 單價（四捨五入至 2 位小數）。用量或價錢未設定的項目顯示「待定」，不計入合計。

---

## 2. 部署前準備

需要一部安裝了 **Docker** 和 **Docker Compose** 的機器。

> **關於 Windows Server：** Docker Desktop 不支援 Windows Server，而這個系統用的是 Linux 容器。建議做法：
> 1. **（建議）** 在 Windows Server 用 Hyper-V 開一部 Ubuntu Server 虛擬機，在虛擬機安裝 Docker Engine。
> 2. 試用或開發時，可以在 Windows 10/11 電腦安裝 Docker Desktop。
>
> 請和公司 IT 確認用哪個方法。

在 Ubuntu 安裝 Docker：
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER    # 之後重新登入
docker compose version           # 確認可用
```

---

## 3. 第一次部署

```bash
# 1. 把整個 fireboard 資料夾複製到伺服器，然後進入資料夾
cd fireboard

# 2. 建立設定檔
cp .env.example .env
#    用文字編輯器打開 .env，修改：
#    - DJANGO_SECRET_KEY：一串長而隨機的字
#    - POSTGRES_PASSWORD：數據庫密碼
#    - DJANGO_ALLOWED_HOSTS 和 DJANGO_CSRF_TRUSTED_ORIGINS：伺服器的 IP 或名稱

# 3. 建立並啟動
docker compose up -d --build

# 4. 查看啟動紀錄，見到「seed_data 完成」和 gunicorn 啟動即成功
docker compose logs -f web      # Ctrl+C 離開

# 5. 建立系統管理員帳戶（只需做一次）
docker compose exec web python manage.py createsuperuser
```

打開瀏覽器：`http://伺服器IP:8000`，用剛建立的帳戶登入。

---

## 4. 設定用戶

進入 **系統管理** → 用戶 → 新增用戶：

| 角色 | 設定 | 可以做 |
|---|---|---|
| 材料查看員 | 普通用戶，**不加群組** | 計價頁只顯示材料和每 m² 用量；**看不到任何價錢**，沒有「原料價錢」選單；匯出 Excel 也沒有價錢欄 |
| 估價員 | 加入群組「估價員」 | 以上 + 看到單價、每 m² 價錢、合計；可查看原料價錢頁（不能修改） |
| 價錢管理員 | 加入群組「價錢管理員」 | 以上 + 更新原料價錢、Excel 批量更新、新增 / 修改 / 停用材料 |
| 系統管理員 | 勾選「職員狀態」和「超級用戶」 | 所有功能 + 設定系統配方 |

價錢權限由「查看材料價錢」（`view_materialprice`）決定。沒有這個權限的用戶，伺服器根本不會讀取價錢，所以網頁原始碼和 Excel 裡都不會有價錢資料。

---

## 5. 第一次使用前要補充的數據

圖則沒有以下資料，初始數據標示為「待定」。請工程同事確認後輸入：

1. **每 m² 固定數量**（系統管理 → 系統 → 打開系統 → 組件）
   - ③ 連牆角鐵、④ 連板角鐵、⑥ M4 螺絲、⑦ M8 膨脹螺栓
2. **價錢**（原料價錢頁 → 更新，或用 Excel 批量更新）
   - M4 自攻螺絲、M8 膨脹螺栓、Enclosure 安裝人工
3. **損耗 %**：暫定板、槽鐵、角鐵、岩棉 10%，其他 0%。在組件表修改。
4. **4 小時槽鐵規格**：圖則寫 100×50×100×1.0，報價單寫 1.0×50×100×50（$33），請確認。
5. **岩棉價錢**：Warwick 報價是 2022 年，建議更新。

---

## 6. 日常使用

- **計價：** 首頁選品牌、系統、耐火時間 → 計算。
- **匯出 Excel：** 計價結果右上角按「匯出 Excel」，下載每 m² 材料及價錢明細（包括系統資料、測試報告、待定項目）。
- **總面積（可選）：** 計價時輸入總面積（m²），會多計「總用量」、「訂購數量」（張、支、件、粒向上進位至整數）及「總價」，Excel 匯出同樣包括。留空就只計每 m²。
- **包括價錢 / 只看材料：** 有價錢權限的用戶（估價員、價錢管理員、管理員）在計價頁可以選「只看材料」，畫面和匯出的 Excel 都不會有價錢，方便把材料清單交給地盤或分判商。沒有價錢權限的用戶不會見到這個選項，一律只有材料。
- **更新價錢（逐項）：** 原料價錢 → 找到材料 → 更新 → 輸入新單價和生效日期 → 儲存。
- **Excel 批量更新：** 原料價錢 → Excel 批量更新 → 下載範本 → 修改 → 上載 → 檢查預覽 → 確認儲存。
  - **更新價錢**：黃色欄填「新單價」（生效日期留空 = 上載頁的預設日期）。「現時單價」「現時生效日期」只供參考。
  - **修改材料資料**：直接改藍色欄（中文名稱、規格、英文名稱、類別、計價單位、每單位涵蓋量）。改涵蓋量會影響所有用到這材料的系統，預覽會提示。
  - **新增材料**：在最後的空白行，「動作」選「新增」，填編號、中文名稱、類別、計價單位、每單位涵蓋量，可同時填新單價。編號不存在又沒有選「新增」會當作錯誤，避免打錯編號變成新材料。
  - **停用材料**：「動作」選「停用」。不會刪除，紀錄保留，可在系統管理重新啟用；仍在使用中的系統配方用到的材料不可以停用。
  - **計價單位有中文和英文兩欄**：中文介面顯示中文單位，英文介面顯示英文單位；英文留空就按系統翻譯顯示。後台和「新增材料」頁也可以填英文計價單位。
  - 舊範本仍可上載，但只會更新價錢。
  - 新單價留空的行不處理；供應商、生效日期留空就用上載頁的預設值。
  - 有錯誤的行（編號不存在、單價不是數字等）會列出，不會儲存；其他行仍可確認儲存。
- **新增材料：** 原料價錢 → 新增材料 → 填寫編號、名稱、規格、類別、單位、每單位涵蓋量，可同時輸入第一個價錢。
  - 新材料要用於計價，需由系統管理員在「系統管理」加入系統配方。
- 舊價錢永遠保留，按「紀錄」查看。生效日期是未來的價錢，到該日才會用於計價。
- **系統管理（後台）的價錢紀錄是唯讀的**：不能新增、修改或刪除，確保每個價錢都有修改人和時間。

---

## 7. 備份和還原

**備份**（建議每日用排程執行，並把檔案複製到 NAS）：
```bash
mkdir -p backups
docker compose exec db pg_dump -U fireboard -Fc -f /tmp/fireboard.dump fireboard
docker compose cp db:/tmp/fireboard.dump ./backups/fireboard-$(date +%F).dump
```

**還原：**
```bash
docker compose cp ./backups/fireboard-2026-11-03.dump db:/tmp/restore.dump
docker compose exec db pg_restore -U fireboard -d fireboard --clean --if-exists /tmp/restore.dump
```

> 數據存放在 Docker volume `pgdata`。**不要執行 `docker compose down -v`**，`-v` 會刪除所有數據。

---

## 8. 常用指令

| 用途 | 指令 |
|---|---|
| 啟動 | `docker compose up -d` |
| 停止 | `docker compose down` |
| 查看紀錄 | `docker compose logs -f web` |
| 更新程式後重建 | `docker compose up -d --build` |
| 執行測試 | `docker compose exec web python manage.py test estimator` |
| 進入 Django shell | `docker compose exec web python manage.py shell` |

---

## 9. 本機開發（不用 Docker）

沒有設定 `POSTGRES_DB` 時會自動用 SQLite，方便在自己電腦試：

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows；Mac/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
set DJANGO_DEBUG=1              # Mac/Linux 用 export DJANGO_DEBUG=1
python manage.py migrate
python manage.py seed_data
python manage.py createsuperuser
python manage.py test estimator
python manage.py runserver
```
打開 `http://127.0.0.1:8000`。

---

## 10. 之後加入 Partition 和 Durasteel

1. 系統管理 → 材料：加入新材料（例如 Durasteel 6.3mm、9.0mm 板），填計價單位和每單位涵蓋量。
2. 原料價錢頁：輸入新材料價錢。
3. 系統管理 → 系統 → 新增：選品牌、系統、耐火時間，填測試報告編號，再加入組件。
4. 儲存後，計價頁的選項會自動出現。

如果 Durasteel 的計法不適用現有三種計算方式，需要在 `estimator/calc.py` 新增一種，並在 `models.py` 的 `METHOD_CHOICES` 加入。

---

## 11. 介面語言（繁體 / 简体 / English）

- **每次登入都用帳戶的「預設語言」**：管理員在「系統管理 → 用戶 → 打開用戶 → 用戶設定 → 預設語言」設定。未設定的帳戶和登入頁用**英文**（`settings.py` 的 `FB_DEFAULT_LANGUAGE`）。
- 每頁右上角的語言選擇**只維持到登出**，不會改變帳戶的預設語言。
- **簡體中文**：所有文字和數據庫內容由繁體**自動轉換**（OpenCC），不用另外輸入。
- **英文**：
  - 介面文字在 `estimator/translations_en.py`（繁體 → 英文對照表）。新增網頁文字時要在這裡加上英文，沒有對照的會顯示繁體。
  - 材料和組件在「系統管理」有英文欄：材料的「英文名稱」「英文規格」，組件的「英文項目」「英文備註」。留空就顯示中文。初始數據已預先填好英文。
- **Excel 匯出**跟隨用戶當時的語言。**Excel 批量更新範本**用任何語言下載都可以上載，系統會辨認三種語言的欄名。
- 測試：`docker compose exec web python manage.py test estimator`

---

## 12. 關閉瀏覽器即登出

`config/settings.py` 設定了 `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`：關閉瀏覽器後再打開，要重新登入。

- 要關閉**所有**瀏覽器視窗才算關閉；只關一個分頁不會登出。
- Chrome / Edge 如果開啟了「繼續瀏覽上次的網頁」（Continue where you left off），瀏覽器會還原 cookie，可能仍然保持登入。需要時請關閉這個設定，或按「登出」。

---

## 13. 臨時調整計價結果

計價結果上方按「**調整**」：
- 可以改項目名稱、材料 / 規格、單位、每 m² 用量、單價（有價錢權限才可以改單價）
- **換產品**：每行的材料可用下拉選單換成**同類別**的其他產品（例如槽鐵 0.8mm → 1.0mm），用量和單價自動更新。選了非原配方的產品會顯示紅色警告「不在測試報告配方內，請確認是否符合耐火要求」，Excel 備註亦會註明。選回「原配方」即還原該行
- 可以「＋ 新增項目」（例如運輸費）或按 ✕ 刪除項目；新增的行可從**所有材料**中選擇，自動填入名稱、單位和單價；「還原」回到系統計算結果
- 價錢、總用量、訂購數量和合計即時重算；改過的格子以黃色標示，新增的行以藍色標示
- 「匯出 Excel」會匯出調整後的內容，並註明「已手動調整（未儲存到系統）」
- **調整不會儲存到系統**：原料價錢、配方和其他人的結果都不受影響；重新整理或離開頁面時調整會消失（有未匯出的調整時會先提示）
- 價錢權限由伺服器控制：沒有價錢權限或選了「只看材料」，送出的價錢會被忽略

---

## 14. 自動計價紀錄（保留 180 日）

- 每次在計價頁算出結果都會**自動記錄**（當時的輸入、每項明細、合計的快照）。同一用戶 10 分鐘內用相同條件重複計算，只更新同一筆。
- 頂部選單「**計價紀錄**」：每人只看自己的；系統管理員（職員狀態）可以看所有人，並按用戶篩選。沒有價錢權限的人看不到價錢。
- 「查看」顯示當時的快照，之後加價也不會改變；「重新計算」用現時價錢再計一次。
- **超過 180 日自動刪除**（每次有新紀錄時順便清理）。也可以手動執行：`docker compose exec web python manage.py purge_history`
- 設定（`config/settings.py`）：
  - `FB_CALC_HISTORY_ENABLED = True`：改為 `False` 即停用（不再記錄、隱藏選單，數據保留）
  - `FB_CALC_HISTORY_DAYS = 180`：保留日數
- 測試：`docker compose exec web python manage.py test estimator history`

### 完全移除這個功能
這個功能放在獨立的 `history` 資料夾，`estimator` 只透過 `estimator/hooks.py` 的通知點連接，所以移除時不用改計價程式。**次序很重要：先刪數據表，再刪程式。**
1. 備份數據庫：`docker compose exec db pg_dump -U fireboard -Fc -f /tmp/before-remove.dump fireboard`
2. 刪除數據表（程式碼仍要存在）：`docker compose exec web python manage.py migrate history zero`
3. 修改 `config/settings.py`：在 `INSTALLED_APPS` 刪除 `"history"`，在 `context_processors` 刪除 `"history.context_processors.history_nav"`，刪除 `FB_CALC_HISTORY_*` 兩行
4. 修改 `config/urls.py`：刪除 `path("history/", ...)` 一行
5. 刪除 `history` 資料夾
6. `docker compose up -d --build`，再執行 `docker compose exec web python manage.py test estimator`

---

## 15. 報價（另存為報價）

**建立**
- 計價頁算出結果後按「**另存為報價**」（有沒有臨時調整都可以），選「建立新報價」或「加入現有報價（草稿）」，可填「位置 / 說明」（例如 1/F 走廊）。
- 一張報價可以有**多個項目**（例如 Enclosure for Ceiling 2hr 120 m² + Enclosure for Gas Pipe 1hr 80 m²），每個項目有自己的總面積。
- 在報價頁按「＋ 從計價加入項目」→ 計算 → 「另存為報價」，會預先選好這張報價。
- 在「計價紀錄」的查看頁按「**轉為報價**」，會直接複製當時的快照數字。

**快照**：報價複製當時的名稱、規格、用量和價錢，之後原料價錢或配方改動**不會**影響已存的報價。保留材料編號方便追查。

**編號和版本**：`Q-2026-0001 Rev A`（每年由 0001 開始）。
- **草稿**：可以修改客戶資料（客戶名稱、聯絡人及電話、工程名稱及地址、備註）、修改項目（用量、單價、總面積、加減行）、調整次序、刪除項目
- **發出（鎖定）**：之後不可以修改
- **建立新版本**：複製成 Rev B（草稿），Rev A 保持不變。只可以由最新版本建立
- **取消報價**：不刪除，保留紀錄
- 報價列表預設只顯示每張報價的最新版本，勾選「顯示所有版本」可看全部

**權限**
- 所有登入用戶都可以查看所有報價
- 只有**建立人**可以修改自己的草稿；**系統管理員（職員狀態）**可以修改所有人的
- 沒有價錢權限的用戶：建立的報價只有材料；查看別人的報價和匯出 Excel 都**不會**看到任何價錢（由伺服器控制）；不可以修改包括價錢的項目

**匯出 Excel**：報價頁的「匯出 Excel（包括價錢）/（只有材料）」，內容包括客戶資料、項目總表、每個項目的明細，並跟隨介面語言。

**開關**：`config/settings.py` 的 `FB_QUOTES_ENABLED = True`。改為 `False` 後執行 `docker compose up -d --build`：選單、「另存為報價」和「轉為報價」按鈕隱藏，報價網址顯示 404；**數據保留**，改回 `True` 即恢復。停用期間後台仍可查看報價。

**後台**：「系統管理 → 報價」只供查看和刪除（修改請在網站的報價頁進行，以保留鎖定和版本紀錄）。

**測試**：`docker compose exec web python manage.py test estimator history quotes`

### 完全移除這個功能
報價放在獨立的 `quotes` 資料夾；計價頁和計價紀錄頁只在 `fb_quote_save_url` 存在時才顯示按鈕。**次序很重要：先刪數據表，再刪程式。**
1. 備份數據庫：`docker compose exec db pg_dump -U fireboard -Fc -f /tmp/before-remove-quotes.dump fireboard`
2. 刪除數據表（程式碼仍要存在）：`docker compose exec web python manage.py migrate quotes zero`
3. 修改 `config/settings.py`：在 `INSTALLED_APPS` 刪除 `"quotes"`，在 `context_processors` 刪除 `"quotes.context_processors.quotes_nav"`，刪除 `FB_QUOTES_ENABLED` 一行
4. 修改 `config/urls.py`：刪除 `path("quotes/", ...)` 一行
5. 刪除 `quotes` 資料夾
6. `docker compose up -d --build`，再執行 `docker compose exec web python manage.py test estimator history`

---

## 16. 自動備份（backup_fireboard.bat）

- 雙擊 `backup_fireboard.bat` 即可備份一次；備份放在 `C:\fireboard_backup\daily`，每月 1 號另存到 `monthly`，結果寫在 `backup.log`
- 每日備份保留 14 日，每月備份保留約 13 個月（檔案開頭的 `DAILY_KEEP`、`MONTHLY_KEEP` 可改）
- 填上 `COPY_TO`（例如 `\\NAS\backup\fireboard`）可另外複製到 NAS
- 用「工作排程器」每晚執行；電腦要開著並已登入，Docker Desktop 要在運行
- 還原：見「7. 備份和還原」

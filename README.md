# 防火板計價系統（第一版）

輸入 **品牌 → 系統 → 耐火時間**，計出每 m² 材料用量和每項價錢。

- 第一版數據：Promat · Enclosure · 1 / 2 / 4 小時（根據 Easy Smart Promat Enclosure System 圖則 01-03-2024 及供應商報價單）
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
│   ├── price_import.py       # Excel 範本產生及讀取（批量更新價錢）
│   ├── export.py             # 計價結果匯出 Excel
│   ├── seed.py               # 初始材料、價錢、配方數據
│   ├── management/commands/seed_data.py
│   ├── migrations/0001_initial.py
│   └── tests.py
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
| 價錢管理員 | 加入群組「價錢管理員」 | 以上 + 更新原料價錢、Excel 批量更新、新增材料 |
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
- **Excel 批量更新：** 原料價錢 → Excel 批量更新 → 下載範本 → 在黃色欄填「新單價」→ 上載 → 檢查預覽 → 確認儲存。
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

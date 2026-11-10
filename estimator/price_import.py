"""Excel 批量更新：價錢、新增材料、修改材料資料、停用材料（不依賴 Django，方便測試）。

範本欄位：
  動作 | 編號 | 中文名稱 | 中文規格 | 英文名稱 | 英文規格 | 類別 | 中文計價單位 | 英文計價單位 | 每單位涵蓋量 |
  現時單價 | 現時生效日期 | 新單價 | 供應商 | 生效日期 | 備註

- 動作留空或「更新」：更新價錢（「新單價」有填時）及修改材料資料（和現時資料不同時）
- 動作「新增」：新增材料（編號不可已存在），可同時填第一個價錢
- 動作「停用」：停用材料（不刪除，紀錄保留）；仍在使用中的系統配方用到的不可以停用
- 「現時單價」「現時生效日期」只供參考，上載時不會讀取
- 舊範本（只有 編號 | 名稱 | 規格 | 單位 | 現時單價 | 新單價 …）仍可上載，但只會更新價錢
"""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

HEADERS = ["動作", "編號", "中文名稱", "中文規格", "英文名稱", "英文規格", "類別", "中文計價單位", "英文計價單位", "每單位涵蓋量",
           "現時單價", "現時生效日期", "新單價", "供應商", "生效日期", "備註"]
COL = {h: i + 1 for i, h in enumerate(HEADERS)}           # 欄號（1 起）
ACTION_ADD, ACTION_DEACTIVATE, ACTION_UPDATE = "新增", "停用", "更新"   # 「更新」= 留空
DETAIL_FIELDS = [("中文名稱", "name"), ("中文規格", "spec"), ("英文名稱", "name_en"), ("英文規格", "spec_en"),
                 ("類別", "category"), ("中文計價單位", "unit"), ("英文計價單位", "unit_en"), ("每單位涵蓋量", "coverage")]
OLD_HEADER_ALIASES = {"中文計價單位": {"計價單位"}}   # 舊範本的欄名
REQUIRED_DETAILS = {"name", "category", "unit", "coverage"}
TEXT_LIMITS = {"name": 100, "spec": 100, "name_en": 100, "spec_en": 100, "unit": 20, "unit_en": 20}
MAX_ROWS = 2000
MAX_COVERAGE = Decimal("999999")


def _no_translate(text, **kwargs):
    return text.format(**kwargs) if kwargs else text


@dataclass
class MaterialInfo:
    """上載時比對用的現有材料資料。"""
    name: str
    spec: str = ""
    name_en: str = ""
    spec_en: str = ""
    category: str = ""
    unit: str = ""
    unit_en: str = ""
    coverage: Decimal = Decimal("1")
    price: Decimal | None = None
    price_date: date | None = None
    active: bool = True
    used_in: list = field(default_factory=list)      # 使用中的系統（停用時檢查）
    unit_names: set = field(default_factory=set)     # 計價單位在各語言的寫法（小寫），例如 {"張", "sheet"}

    @property
    def label(self):
        return f"{self.name} {self.spec}".strip()


@dataclass
class ImportRow:
    """一行價錢更新。"""
    row: int
    code: str
    name: str
    old_price: Decimal | None
    new_price: Decimal
    supplier: str
    effective_date: date
    note: str
    warning: str = ""          # 預覽時提示（例如生效日期不比現時價錢晚），不影響儲存

    def to_session(self):
        return {
            "row": self.row, "code": self.code, "name": self.name,
            "old_price": str(self.old_price) if self.old_price is not None else None,
            "new_price": str(self.new_price), "supplier": self.supplier,
            "effective_date": self.effective_date.isoformat(), "note": self.note,
        }


@dataclass
class NewMaterial:
    row: int
    code: str
    fields: dict                # name, spec, name_en, spec_en, category, unit, unit_en, coverage
    category_label: str = ""    # 預覽顯示用

    @property
    def label(self):
        return f"{self.fields['name']} {self.fields['spec']}".strip()

    def to_session(self):
        return {"row": self.row, "code": self.code,
                "fields": {**self.fields, "coverage": str(self.fields["coverage"])}}


@dataclass
class MaterialChange:
    row: int
    code: str
    name: str
    changes: list               # [(欄名, 舊顯示, 新顯示)]
    values: dict                # 欄位 → 新值（儲存用）

    @property
    def coverage_changed(self):
        return "coverage" in self.values

    def to_session(self):
        values = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.values.items()}
        return {"row": self.row, "code": self.code, "values": values}


@dataclass
class Deactivation:
    row: int
    code: str
    name: str

    def to_session(self):
        return asdict(self)


@dataclass
class ImportResult:
    valid: list = field(default_factory=list)       # ImportRow（價錢）
    errors: list = field(default_factory=list)      # (行號, 訊息)
    unchanged: list = field(default_factory=list)   # (行號, 編號)
    new: list = field(default_factory=list)         # NewMaterial
    changes: list = field(default_factory=list)     # MaterialChange
    deactivate: list = field(default_factory=list)  # Deactivation

    @property
    def warning_count(self):
        return sum(1 for r in self.valid if r.warning)

    @property
    def has_updates(self):
        return bool(self.valid or self.new or self.changes or self.deactivate)

    @property
    def update_count(self):
        return len(self.valid) + len(self.new) + len(self.changes) + len(self.deactivate)

    def to_session(self):
        return {"prices": [r.to_session() for r in self.valid],
                "new": [r.to_session() for r in self.new],
                "changes": [r.to_session() for r in self.changes],
                "deactivate": [r.to_session() for r in self.deactivate]}


# ---------- 範本 ----------

def build_template(materials, t=_no_translate, categories=None, actions=None):
    """materials：[dict(code, name, spec, name_en, spec_en, category_label, unit, unit_en, coverage,
                        price, price_date, supplier)]
    categories：類別顯示名稱（下拉選單用）；actions：動作顯示名稱（新增、停用）。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = t("材料及價錢")[:31]
    ws.append([t(h) for h in HEADERS])
    for m in materials:
        ws.append([
            None, m["code"], m["name"], m.get("spec", ""), m.get("name_en", ""), m.get("spec_en", ""),
            m.get("category_label", ""), m.get("unit", ""), m.get("unit_en", ""),
            float(m["coverage"]) if m.get("coverage") is not None else None,
            float(m["price"]) if m.get("price") is not None else None, m.get("price_date"),
            None, m.get("supplier") or "", None, "",
        ])

    bold = Font(bold=True)
    grey = PatternFill("solid", fgColor="EEEEEE")
    yellow = PatternFill("solid", fgColor="FFF2CC")
    blue = PatternFill("solid", fgColor="DDEBF7")
    ref_font = Font(color="666666")
    for c in ws[1]:
        c.font = bold
        c.fill = grey
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for h in ("動作", "中文名稱", "中文規格", "英文名稱", "英文規格", "類別", "中文計價單位", "英文計價單位",
              "每單位涵蓋量"):
        ws.cell(1, COL[h]).fill = blue                # 材料資料（可改）
    for h in ("新單價", "供應商", "生效日期", "備註"):
        ws.cell(1, COL[h]).fill = yellow              # 價錢（可填）
    widths = {"動作": 9, "編號": 20, "中文名稱": 18, "中文規格": 24, "英文名稱": 18, "英文規格": 24,
              "類別": 12, "中文計價單位": 10, "英文計價單位": 10, "每單位涵蓋量": 12, "現時單價": 11, "現時生效日期": 13,
              "新單價": 11, "供應商": 24, "生效日期": 13, "備註": 28}
    for h, w in widths.items():
        ws.column_dimensions[ws.cell(1, COL[h]).column_letter].width = w
    ws.row_dimensions[1].height = 32

    last = max(ws.max_row, 2) + 200                    # 預留空白行給新增材料
    for r in range(2, last + 1):
        ws.cell(r, COL["每單位涵蓋量"]).number_format = "0.####"
        ws.cell(r, COL["現時單價"]).number_format = "#,##0.00"
        ws.cell(r, COL["現時生效日期"]).number_format = "yyyy-mm-dd"
        ws.cell(r, COL["現時單價"]).font = ref_font
        ws.cell(r, COL["現時生效日期"]).font = ref_font
        ws.cell(r, COL["新單價"]).number_format = "#,##0.00"
        ws.cell(r, COL["生效日期"]).number_format = "yyyy-mm-dd"

    def letter(h):
        return ws.cell(1, COL[h]).column_letter

    def add_dv(dv, h):
        ws.add_data_validation(dv)
        dv.add(f"{letter(h)}2:{letter(h)}{last}")

    add_dv(DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0",
                          showErrorMessage=True, error=t("請輸入 0 或以上的數字")), "新單價")
    add_dv(DataValidation(type="decimal", operator="greaterThan", formula1="0", showErrorMessage=True,
                          error=t("每單位涵蓋量必須大於 0。")), "每單位涵蓋量")
    example = date.today().isoformat()
    add_dv(DataValidation(type="date", operator="greaterThan", formula1="DATE(2000,1,1)",
                          allow_blank=True, showErrorMessage=True, showInputMessage=True,
                          promptTitle=t("生效日期")[:32],
                          prompt=t("格式：YYYY-MM-DD，例如 {d}", d=example)[:255],
                          error=t("生效日期格式不正確，請用 YYYY-MM-DD，例如 {d}", d=example)[:255]), "生效日期")

    def list_dv(values, h, prompt):
        joined = ",".join(v.replace(",", " ") for v in values)
        if values and len(joined) <= 250:             # Excel 下拉清單上限 255 字元
            add_dv(DataValidation(type="list", formula1=f'"{joined}"', allow_blank=True,
                                  showErrorMessage=True, showInputMessage=True, prompt=prompt[:255],
                                  error=t("請從清單選擇")), h)

    list_dv(actions or [], "動作", t("「更新」或留空 = 更新價錢 / 資料；「新增」= 新材料；「停用」= 停用材料"))
    list_dv(categories or [], "類別", t("請從清單選擇"))
    ws.freeze_panes = ws.cell(2, COL["中文名稱"])

    info = wb.create_sheet(t("說明"))
    for line in [
        "使用方法",
        "1. 只需在黃色欄填寫：新單價（必填）、供應商、生效日期（YYYY-MM-DD）、備註。",
        "2. 新單價留空的行不會更新價錢。",
        "「現時單價」和「現時生效日期」只供參考，修改了也不會儲存。",
        "3. 供應商、生效日期留空，會使用上載頁面填寫的預設值。",
        "4. 不要修改「編號」欄，系統用它配對材料。",
        "5. 上載後會先顯示預覽，確認後才會儲存。舊價錢會保留在紀錄中。",
        "6. 修改材料資料：直接修改藍色欄（中文名稱、規格、英文名稱、類別、中文 / 英文計價單位、每單位涵蓋量）。修改「每單位涵蓋量」會影響所有用到這材料的系統計算。",
        "7. 新增材料：在最後的空白行，「動作」填「新增」，再填編號、中文名稱、類別、中文計價單位、每單位涵蓋量（英文計價單位建議一併填寫）；可同時填新單價。",
        "8. 停用材料：「動作」填「停用」。停用不會刪除紀錄，可在系統管理重新啟用；仍在系統配方中使用的材料不可以停用。",
        "9. 中文計價單位填中文（例如 張、支、件、粒），英文計價單位填英文（例如 sheet、pc、nos）。中文介面顯示中文單位，英文介面顯示英文單位；英文計價單位留空會按系統翻譯顯示。",
        "10. 現有材料的中文名稱、類別、中文計價單位、每單位涵蓋量留空 = 不改動；新增材料時這幾欄必須填寫。",
    ]:
        info.append([t(line)])
    info["A1"].font = bold
    info.column_dimensions["A"].width = 110

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- 讀取 ----------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _price(v, t=_no_translate):
    if v is None or _text(v) == "":
        return None
    try:
        d = Decimal(_text(v).replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise ValueError(t("新單價「{v}」不是數字", v=_text(v))) from None
    if not d.is_finite():
        raise ValueError(t("新單價「{v}」不是數字", v=_text(v)))
    if d < 0:
        raise ValueError(t("新單價不可以是負數"))
    if d.as_tuple().exponent < -2:
        d = d.quantize(Decimal("0.01"))
    return d


def _coverage(v, t=_no_translate):
    try:
        d = Decimal(_text(v).replace(",", ""))
    except InvalidOperation:
        raise ValueError(t("每單位涵蓋量「{v}」不是數字", v=_text(v))) from None
    if not d.is_finite() or d <= 0 or d > MAX_COVERAGE:
        raise ValueError(t("每單位涵蓋量必須大於 0。"))
    return d.quantize(Decimal("0.0001"))


def _date(v, t=_no_translate):
    if v is None or _text(v) == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v).replace("/", "-")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ValueError(t("生效日期「{v}」格式不正確，請用 YYYY-MM-DD", v=_text(v))) from None


def _fmt(key, value, category_names):
    if key == "category":
        return category_names.get(value, value)
    if key == "coverage":
        return f"{Decimal(value).normalize():f}"      # :f 避免 1E+1 這類寫法
    return value or "—"


def parse_workbook(file, materials, default_supplier, default_date, t=_no_translate,
                   header_aliases=None, category_aliases=None, unit_aliases=None, action_aliases=None,
                   can_add=False, can_change=False, category_names=None):
    """materials：{code: MaterialInfo}，包括已停用的材料（新增時檢查重複）。

    *_aliases：{顯示文字（小寫）: 儲存值}，用來辨認任何語言寫的類別和動作。
    unit_aliases：已不使用（計價單位照填寫的文字儲存），保留參數只為相容。
    can_add / can_change：用戶是否有新增 / 修改（含停用）材料的權限。
    """
    result = ImportResult()
    category_aliases = category_aliases or {}
    action_aliases = {**{ACTION_ADD: ACTION_ADD, ACTION_DEACTIVATE: ACTION_DEACTIVATE, ACTION_UPDATE: ""},
                      **(action_aliases or {})}
    category_names = category_names or {}
    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except Exception:
        result.errors.append((0, t("無法讀取檔案，請上載 .xlsx 格式的 Excel 檔")))
        return result

    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    # 範本可能是任何一種介面語言下載的：把欄名換回繁體中文的標準名稱
    alias_to_key = {}
    for key in HEADERS:
        for name in (header_aliases or {}).get(key, {key}) | {key}:
            alias_to_key[name.strip().lower()] = key
    header = [alias_to_key.get(_text(h).lower(), _text(h)) for h in next(rows, [])]
    missing = [h for h in ("編號", "新單價") if h not in header]
    if missing:
        result.errors.append((1, t("找不到欄位：{cols}。請使用系統下載的範本",
                                   cols="、".join(t(m) for m in missing))))
        return result
    idx = {h: header.index(h) for h in HEADERS if h in header}
    detail_cols = [(h, key) for h, key in DETAIL_FIELDS if h in idx]   # 舊範本沒有這些欄

    def cell(values, name):
        i = idx.get(name)
        return values[i] if i is not None and i < len(values) else None

    def lookup(aliases, raw):
        text = _text(raw)
        return aliases.get(text.lower(), aliases.get(text, None))

    def read_details(values, info):
        """讀取材料資料欄，傳回 {欄位: 新值}（只包括有欄的）。資料不正確時 raise ValueError。

        現有材料（info 不是 None）：必填欄（中文名稱、類別、計價單位、涵蓋量）留空 = 不改動。
        新材料（info 是 None）：必填欄不可以留空。
        """
        out = {}
        for h, key in detail_cols:
            raw = cell(values, h)
            text = _text(raw)
            if key in REQUIRED_DETAILS and text == "":
                if info is not None:
                    continue                          # 現有材料：留空 = 不改動
                raise ValueError(t("「{col}」不可以留空", col=t(h)))
            if key == "category":
                value = lookup(category_aliases, raw)
                if value is None:
                    raise ValueError(t("類別「{v}」不正確，請從清單選擇", v=text))
            elif key == "unit":
                names = (info.unit_names | {info.unit.lower()}) if info is not None else set()
                # 和現時單位相同（任何語言的寫法，例如英文介面的 sheet = 張）→ 不改動；
                # 否則照填寫的文字儲存（例如 pc、no.、m²）
                value = info.unit if text.lower() in names else text
            elif key == "coverage":
                value = _coverage(raw, t)
            else:
                value = text
            if key in TEXT_LIMITS and len(value) > TEXT_LIMITS[key]:
                raise ValueError(t("「{col}」太長（上限 {n} 字）", col=t(h), n=TEXT_LIMITS[key]))
            out[key] = value
        return out

    # 編號不分大小寫配對（現有編號例如 AG-50x50x1.0 有小寫 x）；新增的編號一律轉為大寫
    canonical = {c.upper(): c for c in materials}
    seen = {}
    for n, values in enumerate(rows, start=2):
        if n > MAX_ROWS + 1:
            result.errors.append((n, t("超過 {n} 行，其餘未處理", n=MAX_ROWS)))
            break
        typed = _text(cell(values, "編號"))
        code = canonical.get(typed.upper(), typed.upper())
        raw_action = cell(values, "動作")
        raw_price = cell(values, "新單價")
        action = ""
        if _text(raw_action):
            action = lookup(action_aliases, raw_action)
            if action is None:
                result.errors.append((n, t("「動作」只可以留空，或選「更新」、「新增」、「停用」")))
                continue
        if not code:
            if action or _text(raw_price):
                result.errors.append((n, t("未填編號")))
            continue
        if code in seen:
            result.errors.append((n, t("編號「{code}」重複（第 {row} 行已有），此行未處理",
                                       code=code, row=seen[code])))
            continue
        info = materials.get(code)

        try:
            # ---- 新增材料 ----
            if action == ACTION_ADD:
                if not can_add:
                    raise ValueError(t("你沒有新增材料的權限"))
                if info is not None:
                    raise ValueError(t("編號「{code}」已存在（已停用，可在系統管理重新啟用）", code=code)
                                     if not info.active else t("編號「{code}」已存在，不可以新增", code=code))
                if len(code) > 40:
                    raise ValueError(t("編號太長（上限 40 字）"))
                if len(detail_cols) < len(DETAIL_FIELDS):
                    raise ValueError(t("舊範本不可以新增材料，請重新下載範本"))
                fields = read_details(values, None)       # 新材料：沒有現時資料可比對
                price = _price(raw_price, t)
                seen[code] = n
                result.new.append(NewMaterial(row=n, code=code, fields=fields,
                                              category_label=category_names.get(fields["category"], fields["category"])))
                if price is not None:
                    result.valid.append(ImportRow(
                        row=n, code=code, name=f"{fields['name']} {fields['spec']}".strip(), old_price=None,
                        new_price=price, supplier=_text(cell(values, "供應商")) or default_supplier,
                        effective_date=_date(cell(values, "生效日期"), t) or default_date,
                        note=_text(cell(values, "備註"))))
                continue

            if info is None or not info.active:
                if info is not None:
                    raise ValueError(t("材料「{code}」已停用，請先在系統管理重新啟用", code=code))
                raise ValueError(t("找不到材料編號「{code}」（如要新增，請在「動作」欄填「新增」）", code=code))

            # ---- 停用材料 ----
            if action == ACTION_DEACTIVATE:
                if not can_change:
                    raise ValueError(t("你沒有停用材料的權限"))
                if _text(raw_price):
                    raise ValueError(t("停用的材料不可以同時填新單價"))
                if info.used_in:
                    raise ValueError(t("「{code}」仍在以下系統使用，不可以停用：{systems}",
                                       code=code, systems="、".join(info.used_in)))
                seen[code] = n
                result.deactivate.append(Deactivation(row=n, code=code, name=info.label))
                continue

            # ---- 修改資料及 / 或更新價錢 ----
            details = read_details(values, info) if detail_cols else {}
            changed = {}
            for key, new_value in details.items():
                old_value = getattr(info, key)
                same = (Decimal(old_value) == new_value) if key == "coverage" else (old_value or "") == new_value
                if not same:
                    changed[key] = new_value
            if changed and not can_change:
                raise ValueError(t("你沒有修改材料資料的權限（只可以更新價錢）"))
            price = _price(raw_price, t)
            eff = (_date(cell(values, "生效日期"), t) or default_date) if price is not None else None
        except ValueError as e:
            result.errors.append((n, str(e)))
            continue

        if not changed and price is None:
            continue
        seen[code] = n
        if changed:
            labels = dict((key, h) for h, key in DETAIL_FIELDS)
            result.changes.append(MaterialChange(
                row=n, code=code, name=info.label, values=changed,
                changes=[(t(labels[k]), _fmt(k, getattr(info, k), category_names), _fmt(k, v, category_names))
                         for k, v in changed.items()]))
        if price is None:
            continue
        if info.price is not None and price == info.price and info.price_date == eff:
            result.unchanged.append((n, code))
            continue
        warning = ""
        if info.price_date is not None and eff == info.price_date:
            warning = t("生效日期和現時價錢相同（{d}），請確認。價錢紀錄會顯示新價錢由 {d} 起生效。",
                        d=info.price_date.isoformat())
        elif info.price_date is not None and eff < info.price_date:
            warning = t("生效日期 {e} 早於現時價錢的生效日期（{d}），請確認。儲存後現時價錢不會改變，新價錢只會成為舊紀錄。",
                        d=info.price_date.isoformat(), e=eff.isoformat())
        result.valid.append(ImportRow(
            row=n, code=code, name=info.label, old_price=info.price, new_price=price,
            supplier=_text(cell(values, "供應商")) or default_supplier,
            effective_date=eff, note=_text(cell(values, "備註")), warning=warning,
        ))
    wb.close()
    return result

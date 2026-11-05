"""Excel 批量更新價錢：產生範本、讀取上載檔案（不依賴 Django，方便測試）。

範本欄位：
  編號 | 名稱 | 規格 | 單位 | 現時單價 | 新單價 | 供應商 | 生效日期 | 備註
只有「新單價」有填的行才會處理；「供應商」「生效日期」留空就用上載時填的預設值。
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

HEADERS = ["編號", "名稱", "規格", "單位", "現時單價", "新單價", "供應商", "生效日期", "備註"]
COL = {h: i for i, h in enumerate(HEADERS)}
MAX_ROWS = 2000


@dataclass
class ImportRow:
    row: int
    code: str
    name: str
    old_price: Decimal | None
    new_price: Decimal
    supplier: str
    effective_date: date
    note: str

    def to_session(self):
        return {
            "row": self.row, "code": self.code, "name": self.name,
            "old_price": str(self.old_price) if self.old_price is not None else None,
            "new_price": str(self.new_price), "supplier": self.supplier,
            "effective_date": self.effective_date.isoformat(), "note": self.note,
        }


@dataclass
class ImportResult:
    valid: list = field(default_factory=list)      # ImportRow
    errors: list = field(default_factory=list)     # (行號, 訊息)
    unchanged: list = field(default_factory=list)  # (行號, 編號)


def build_template(materials):
    """materials：[(code, name, spec, unit, current_price or None, current_supplier)]"""
    wb = Workbook()
    ws = wb.active
    ws.title = "價錢"
    ws.append(HEADERS)
    for code, name, spec, unit, price, supplier in materials:
        ws.append([code, name, spec, unit, float(price) if price is not None else None,
                   None, supplier or "", None, ""])

    bold = Font(bold=True)
    grey = PatternFill("solid", fgColor="EEEEEE")
    fill = PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.font = bold
        c.fill = grey
        c.alignment = Alignment(horizontal="center")
    for col in ("F", "G", "H", "I"):           # 用戶要填的欄
        ws[f"{col}1"].fill = fill
    widths = {"A": 20, "B": 20, "C": 26, "D": 8, "E": 12, "F": 12, "G": 26, "H": 14, "I": 30}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    last = max(ws.max_row, 2)
    for row in ws.iter_rows(min_row=2, max_row=last, min_col=5, max_col=6):
        for c in row:
            c.number_format = "#,##0.00"
    for row in ws.iter_rows(min_row=2, max_row=last, min_col=8, max_col=8):
        for c in row:
            c.number_format = "yyyy-mm-dd"
    dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0",
                        showErrorMessage=True, error="請輸入 0 或以上的數字")
    ws.add_data_validation(dv)
    dv.add(f"F2:F{last}")
    ws.freeze_panes = "A2"

    info = wb.create_sheet("說明")
    for line in [
        "使用方法",
        "1. 只需在黃色欄填寫：新單價（必填）、供應商、生效日期（YYYY-MM-DD）、備註。",
        "2. 新單價留空的行不會處理。",
        "3. 供應商、生效日期留空，會使用上載頁面填寫的預設值。",
        "4. 不要修改「編號」欄，系統用它配對材料。",
        "5. 上載後會先顯示預覽，確認後才會儲存。舊價錢會保留在紀錄中。",
    ]:
        info.append([line])
    info["A1"].font = bold
    info.column_dimensions["A"].width = 80

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _price(v):
    if v is None or _text(v) == "":
        return None
    try:
        d = Decimal(_text(v).replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise ValueError(f"新單價「{_text(v)}」不是數字")
    if d < 0:
        raise ValueError("新單價不可以是負數")
    if d.as_tuple().exponent < -2:
        d = d.quantize(Decimal("0.01"))
    return d


def _date(v):
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
        raise ValueError(f"生效日期「{_text(v)}」格式不正確，請用 YYYY-MM-DD")


def parse_workbook(file, materials, default_supplier, default_date):
    """materials：{code: (name, current_price or None, current_date or None)}"""
    result = ImportResult()
    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except Exception:
        result.errors.append((0, "無法讀取檔案，請上載 .xlsx 格式的 Excel 檔"))
        return result

    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_text(h) for h in next(rows, [])]
    missing = [h for h in ("編號", "新單價") if h not in header]
    if missing:
        result.errors.append((1, f"找不到欄位：{'、'.join(missing)}。請使用系統下載的範本"))
        return result
    idx = {h: header.index(h) for h in HEADERS if h in header}

    def cell(values, name):
        i = idx.get(name)
        return values[i] if i is not None and i < len(values) else None

    seen = {}
    for n, values in enumerate(rows, start=2):
        if n > MAX_ROWS + 1:
            result.errors.append((n, f"超過 {MAX_ROWS} 行，其餘未處理"))
            break
        code = _text(cell(values, "編號"))
        raw_price = cell(values, "新單價")
        if not code and _text(raw_price) == "":
            continue
        if _text(raw_price) == "":
            continue
        if code not in materials:
            result.errors.append((n, f"找不到材料編號「{code}」"))
            continue
        try:
            price = _price(raw_price)
            eff = _date(cell(values, "生效日期")) or default_date
        except ValueError as e:
            result.errors.append((n, str(e)))
            continue
        if code in seen:
            result.errors.append((n, f"編號「{code}」重複（第 {seen[code]} 行已有），此行未處理"))
            continue
        seen[code] = n

        name, old_price, old_date = materials[code]
        if old_price is not None and price == old_price and old_date == eff:
            result.unchanged.append((n, code))
            continue
        result.valid.append(ImportRow(
            row=n, code=code, name=name, old_price=old_price, new_price=price,
            supplier=_text(cell(values, "供應商")) or default_supplier,
            effective_date=eff, note=_text(cell(values, "備註")),
        ))
    wb.close()
    return result

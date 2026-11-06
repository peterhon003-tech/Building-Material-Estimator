"""把計價結果匯出為 Excel。"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# (欄名, 闊度, 是否價錢欄)
COLUMNS = [
    ("#", 5, False), ("項目", 16, False), ("材料 / 規格", 30, False), ("計算方式", 10, False),
    ("計算依據", 36, False), ("每 m² 用量", 12, False), ("單位", 7, False),
    ("單價 (HK$)", 12, True), ("供應商", 24, True), ("價錢日期", 12, True),
    ("每 m² 價錢 (HK$)", 16, True), ("備註", 34, False),
]


def build_calc_xlsx(result, user="", show_prices=True):
    """show_prices=False：不包括任何價錢欄和合計（給沒有價錢權限的用戶）。"""
    cols = [c for c in COLUMNS if show_prices or not c[2]]
    names = [c[0] for c in cols]
    s = result.system
    wb = Workbook()
    ws = wb.active
    ws.title = "每 m² 材料及價錢"

    bold = Font(bold=True)
    title = Font(bold=True, size=14)
    head_fill = PatternFill("solid", fgColor="EEEEEE")
    pending_font = Font(color="9A6700")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(bottom=thin)

    ws.append([f"防火板計價：{s}"])
    ws["A1"].font = title
    info = [
        ("F.R.R.", s.frr_label),
        ("測試報告", s.report_no),
        ("系統總厚度", f"{s.overall_thickness_mm} mm" if s.overall_thickness_mm else ""),
        ("圖則", s.drawing_ref),
        *([("價錢日期", result.on_date.isoformat())] if show_prices else []),
        ("匯出人", user),
    ]
    for k, v in info:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = bold
    ws.append([])

    ws.append(names)
    head_row = ws.max_row
    for c in ws[head_row]:
        c.font = bold
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for l in result.lines:
        values = {
            "#": l.item_no, "項目": l.description, "材料 / 規格": l.material,
            "計算方式": l.method, "計算依據": l.basis,
            "每 m² 用量": float(l.qty) if l.qty is not None else "待定", "單位": l.unit,
            "單價 (HK$)": float(l.unit_price) if l.unit_price is not None else "待提供",
            "供應商": l.supplier, "價錢日期": l.price_date.isoformat() if l.price_date else "",
            "每 m² 價錢 (HK$)": float(l.cost) if l.cost is not None else None, "備註": l.note,
        }
        ws.append([values[n] for n in names])
        r = ws.max_row
        formats = {"每 m² 用量": "0.0000", "單價 (HK$)": "#,##0.00", "每 m² 價錢 (HK$)": "#,##0.00"}
        for n, fmt in formats.items():
            if n in names:
                ws.cell(r, names.index(n) + 1).number_format = fmt
        is_pending = l.pending if show_prices else l.qty_pending
        for c in ws[r]:
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=True)
            if is_pending:
                c.font = pending_font

    first, last = head_row + 1, ws.max_row
    if show_prices:
        cost_col = names.index("每 m² 價錢 (HK$)") + 1
        letter = ws.cell(head_row, cost_col).column_letter
        ws.append([])
        total = [""] * len(names)
        total[1] = "每 m² 合計（已計項目）"
        total[cost_col - 1] = f"=SUM({letter}{first}:{letter}{last})"
        ws.append(total)
        total_row = ws.max_row
        ws.cell(total_row, 2).font = bold
        ws.cell(total_row, cost_col).font = bold
        ws.cell(total_row, cost_col).number_format = "#,##0.00"

    pending = result.pending_lines
    if pending:
        label = "未計入合計（用量或價錢待定）：" if show_prices else "用量待定："
        ws.append([])
        ws.append(["", label + "、".join(f"{l.item_no}. {l.description}" for l in pending)])
        ws.cell(ws.max_row, 2).font = pending_font

    for i, w in enumerate([c[1] for c in cols], start=1):
        ws.column_dimensions[ws.cell(head_row, i).column_letter].width = w
    ws.freeze_panes = ws.cell(head_row + 1, 1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

"""把計價結果匯出為 Excel。"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HEADERS = ["#", "項目", "材料 / 規格", "計算方式", "計算依據", "每 m² 用量", "單位",
           "單價 (HK$)", "供應商", "價錢日期", "每 m² 價錢 (HK$)", "備註"]
WIDTHS = [5, 16, 30, 10, 36, 12, 7, 12, 24, 12, 16, 34]


def build_calc_xlsx(result, user=""):
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
        ("價錢日期", result.on_date.isoformat()),
        ("匯出人", user),
    ]
    for k, v in info:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = bold
    ws.append([])

    ws.append(HEADERS)
    head_row = ws.max_row
    for c in ws[head_row]:
        c.font = bold
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for l in result.lines:
        ws.append([
            l.item_no, l.description, l.material, l.method, l.basis,
            float(l.qty) if l.qty is not None else "待定", l.unit,
            float(l.unit_price) if l.unit_price is not None else "待提供",
            l.supplier, l.price_date.isoformat() if l.price_date else "",
            float(l.cost) if l.cost is not None else None, l.note,
        ])
        r = ws.max_row
        ws.cell(r, 6).number_format = "0.0000"
        ws.cell(r, 8).number_format = "#,##0.00"
        ws.cell(r, 11).number_format = "#,##0.00"
        for c in ws[r]:
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=True)
            if l.pending:
                c.font = pending_font

    first, last = head_row + 1, ws.max_row
    ws.append([])
    ws.append(["", "每 m² 合計（已計項目）"] + [""] * 8 + [f"=SUM(K{first}:K{last})"])
    total_row = ws.max_row
    ws.cell(total_row, 2).font = bold
    ws.cell(total_row, 11).font = bold
    ws.cell(total_row, 11).number_format = "#,##0.00"

    pending = result.pending_lines
    if pending:
        ws.append([])
        ws.append(["", "未計入合計（用量或價錢待定）：" +
                   "、".join(f"{l.item_no}. {l.description}" for l in pending)])
        ws.cell(ws.max_row, 2).font = pending_font

    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[ws.cell(head_row, i).column_letter].width = w
    ws.freeze_panes = ws.cell(head_row + 1, 1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

"""把報價匯出為 Excel：先是客戶資料和項目總表，然後每個項目的明細。"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# (欄名, 闊度, 是否價錢欄, 是否只在有總面積時顯示)
LINE_COLUMNS = [
    ("#", 5, False, False), ("項目", 18, False, False), ("材料 / 規格", 32, False, False),
    ("每 m² 用量", 12, False, False), ("單位", 7, False, False),
    ("總用量", 11, False, True), ("訂購數量", 10, False, True),
    ("單價 (HK$)", 12, True, False), ("每 m² 價錢 (HK$)", 15, True, False), ("總價 (HK$)", 16, True, True),
    ("備註", 36, False, False),
]
WIDTHS = [6, 22, 34, 13, 9, 12, 12, 13, 16, 16, 36]


def _no_translate(text, **kwargs):
    return text.format(**kwargs) if kwargs else text


def _f(value):
    return None if value is None else float(value)


def build_quote_xlsx(quote, user="", show_prices=True, t=_no_translate):
    """show_prices=False：不包括任何價錢（給沒有價錢權限的用戶，或選了「只看材料」）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = t("報價")[:31]
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="EEEEEE")
    item_fill = PatternFill("solid", fgColor="DDEBF7")
    pending_font = Font(color="9A6700")
    border = Border(bottom=Side(style="thin", color="CCCCCC"))
    wrap_top = Alignment(vertical="top", wrap_text=True)

    def header(values):
        ws.append(values)
        for c in ws[ws.max_row]:
            c.font = bold
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.append([t("報價 {q}", q=quote.label)])
    ws["A1"].font = Font(bold=True, size=14)
    info = [
        (t("客戶名稱"), quote.customer_name), (t("聯絡人及電話"), quote.contact),
        (t("工程名稱及地址"), quote.project), (t("備註"), quote.remarks),
        (t("狀態"), str(quote.get_status_display())),
        (t("建立人"), quote.created_by.get_username() if quote.created_by else ""),
        (t("最後修改"), f"{quote.updated_at:%Y-%m-%d %H:%M}" if quote.updated_at else ""),
        *([(t("發出時間"), f"{quote.issued_at:%Y-%m-%d %H:%M}")] if quote.issued_at else []),
        (t("匯出人"), user),
    ]
    for k, v in info:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = bold
        ws.cell(ws.max_row, 2).alignment = wrap_top
    ws.append([])

    items = list(quote.items.prefetch_related("lines"))

    # ---- 項目總表 ----
    ws.append([t("項目總表")])
    ws.cell(ws.max_row, 1).font = bold
    summary_cols = ["#", t("位置 / 說明"), t("系統"), "F.R.R.", t("測試報告"), t("總面積 (m²)")]
    if show_prices:
        summary_cols += [t("每 m² 合計 (HK$)"), t("合計 (HK$)")]
    header(summary_cols)
    first = ws.max_row + 1
    for it in items:
        row = [it.position, it.title, it.system_label, it.frr_label, it.report_no, _f(it.area)]
        if show_prices:
            priced = it.include_prices
            row += [_f(it.total_per_sqm) if priced else t("只有材料"),
                    _f(it.grand_total) if priced else None]
        ws.append(row)
        for c in ws[ws.max_row]:
            c.alignment = wrap_top
            c.border = border
        ws.cell(ws.max_row, 6).number_format = "#,##0.00"
        if show_prices:
            ws.cell(ws.max_row, 7).number_format = "#,##0.00"
            ws.cell(ws.max_row, 8).number_format = "#,##0.00"
    last = ws.max_row
    if show_prices and items:
        ws.append([""] * 6 + [t("報價合計"), f"=SUM(H{first}:H{last})"])
        ws.cell(ws.max_row, 7).font = bold
        ws.cell(ws.max_row, 8).font = bold
        ws.cell(ws.max_row, 8).number_format = "#,##0.00"
        if any(not it.include_prices or it.grand_total is None for it in items):
            ws.append(["", t("合計只包括有價錢和總面積的項目。")])
            ws.cell(ws.max_row, 2).font = pending_font

    # ---- 每個項目的明細 ----
    for it in items:
        with_prices = show_prices and it.include_prices
        has_area = it.area is not None
        cols = [c for c in LINE_COLUMNS if (with_prices or not c[2]) and (has_area or not c[3])]
        names = [c[0] for c in cols]
        ws.append([])
        title = f"{t('項目')} {it.position}：{it.title + ' · ' if it.title else ''}{it.system_label}"
        ws.append([title])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        for c in range(1, len(WIDTHS) + 1):
            ws.cell(ws.max_row, c).fill = item_fill
        meta = [f"F.R.R. {it.frr_label}" if it.frr_label else "", f"{t('測試報告')} {it.report_no}" if it.report_no else "",
                f"{t('總面積')} {it.area} m²" if has_area else "",
                f"{t('價錢日期')} {it.price_date:%Y-%m-%d}" if (with_prices and it.price_date) else "",
                t("已手動調整") if it.adjusted else ""]
        ws.append(["", " · ".join(m for m in meta if m)])
        header([t(n) for n in names])
        lf = ws.max_row + 1
        for l in it.lines.all():
            values = {
                "#": l.item_no, "項目": l.description, "材料 / 規格": l.material,
                "每 m² 用量": _f(l.qty) if l.qty is not None else t("待定"), "單位": l.unit,
                "總用量": _f(l.total_qty) if l.total_qty is not None else t("待定"),
                "訂購數量": _f(l.order_qty),
                "單價 (HK$)": _f(l.unit_price) if l.unit_price is not None else t("待提供"),
                "每 m² 價錢 (HK$)": _f(l.cost), "總價 (HK$)": _f(l.total_cost),
                "備註": "；".join(x for x in (l.note, str(l.get_state_display()) if l.state != l.ORIGINAL else "") if x),
            }
            ws.append([values[n] for n in names])
            r = ws.max_row
            fmts = {"每 m² 用量": "0.0000", "總用量": "0.00", "訂購數量": "0.##", "單價 (HK$)": "#,##0.00",
                    "每 m² 價錢 (HK$)": "#,##0.00", "總價 (HK$)": "#,##0.00"}
            for n, fmt in fmts.items():
                if n in names:
                    ws.cell(r, names.index(n) + 1).number_format = fmt
            pending = l.qty is None or (with_prices and l.cost is None)
            for c in ws[r]:
                c.border = border
                c.alignment = wrap_top
                if pending:
                    c.font = pending_font
        ll = ws.max_row
        if with_prices:
            total = [""] * len(names)
            total[1] = t("合計（已計項目）")
            for n in ("每 m² 價錢 (HK$)", "總價 (HK$)"):
                if n in names:
                    col = names.index(n) + 1
                    letter = ws.cell(1, col).column_letter
                    total[col - 1] = f"=SUM({letter}{lf}:{letter}{ll})"
            ws.append(total)
            for c in ws[ws.max_row]:
                c.font = bold
                c.number_format = "#,##0.00"

    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

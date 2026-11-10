"""臨時調整：讀取網頁送來的調整後明細，重新計算，供匯出 Excel 用。

調整只存在用戶的瀏覽器，不會寫入數據庫。這裡只負責檢查和計算（不依賴 Django，方便測試）。
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from . import calc

MAX_ROWS = 100
MAX_TEXT = 200
MAX_QTY = Decimal("1000000")
MAX_PRICE = Decimal("1000000000")


def _no_translate(text, **kwargs):
    return text.format(**kwargs) if kwargs else text


def _text(value):
    return str(value or "").strip()[:MAX_TEXT]


def parse_number(value, limit, label, t=_no_translate):
    """讀取數字欄：空白 = None；不是數字、負數或太大 → ValueError（訊息已翻譯）。"""
    return _number(value, limit, label, t)


def line_numbers(qty, price, area, round_up=True):
    """由每 m² 用量（未四捨五入）、單價和總面積計出一行的數字。"""
    total = calc.total_qty(qty, area)
    if total is None:
        order = None
    elif round_up:
        order = calc.order_qty(total, "")          # 張、支、件、粒：向上進位
    else:
        order = calc.round_qty(total)
    return {
        "qty": calc.round_qty(qty),
        "cost": calc.line_cost(qty, price),
        "total_qty": calc.round_qty(total),
        "order_qty": order,
        "total_cost": calc.total_cost(qty, area, price),
    }


def _number(value, limit, label, t):
    raw = _text(value).replace(",", "")
    if raw == "":
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValueError(t("{label}「{v}」不是數字", label=t(label), v=raw))
    if not d.is_finite() or d < 0:
        raise ValueError(t("{label}不可以是負數", label=t(label)))
    if d > limit:
        raise ValueError(t("{label}太大", label=t(label)))
    return d


def _date(value):
    try:
        return date.fromisoformat(_text(value)) if _text(value) else None
    except ValueError:
        return None


def compute_rows(rows, area, include_prices, t=_no_translate):
    """rows：網頁送來的明細（list of dict）。傳回可建立 services.Line 的 dict 清單。

    include_prices=False 時，忽略所有價錢資料（材料查看員或「只看材料」）。
    """
    if not isinstance(rows, list):
        raise ValueError(t("資料格式不正確"))
    if len(rows) > MAX_ROWS:
        raise ValueError(t("項目太多（上限 {n} 項）", n=MAX_ROWS))

    out = []
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            raise ValueError(t("資料格式不正確"))
        state = r.get("state") if r.get("state") in ("original", "edited", "added") else "added"
        qty = _number(r.get("qty"), MAX_QTY, "每 m² 用量", t)
        price = _number(r.get("unit_price"), MAX_PRICE, "單價", t) if include_prices else None
        round_up = bool(r.get("round_up", True))
        try:
            item_no = int(_text(r.get("item_no")) or i)
        except ValueError:
            item_no = i

        nums = line_numbers(qty, price, area, round_up)

        note = _text(r.get("note"))
        replaced_from = _text(r.get("replaced_from"))
        if replaced_from:
            note = "；".join(x for x in (note, t("已替換：{a} → {b}", a=replaced_from,
                                                      b=_text(r.get("material")))) if x)
        if r.get("off_spec"):
            note = "；".join(x for x in (note, t("不在測試報告配方內，請確認是否符合耐火要求")) if x)
        if state == "edited":
            note = "；".join(x for x in (note, t("手動調整")) if x)
        elif state == "added":
            note = "；".join(x for x in (note, t("手動新增")) if x)

        out.append({
            "item_no": item_no,
            "description": _text(r.get("description")),
            "material": _text(r.get("material")),
            "category": "",
            "unit": _text(r.get("unit")),
            "method": _text(r.get("method")) or (t("手動新增") if state == "added" else ""),
            "basis": _text(r.get("basis")),
            "qty": nums["qty"],
            "unit_price": price,
            "supplier": _text(r.get("supplier")) if include_prices else "",
            "price_date": _date(r.get("price_date")) if include_prices else None,
            "cost": nums["cost"],
            "note": note,
            "total_qty": nums["total_qty"],
            "order_qty": nums["order_qty"],
            "total_cost": nums["total_cost"],
            "qty_exact": qty,
            "round_up": round_up,
            "code": _text(r.get("code"))[:40],
        })
    return out

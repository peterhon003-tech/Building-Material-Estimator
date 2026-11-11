"""純計算邏輯（不依賴 Django），方便單獨測試。

三種計算方式，對應 Enclosure 圖則圖例的寫法：
- AREA    按面積：板、岩棉        每 m² 用量 = 層數 × (1 + 損耗%) ÷ 每單位面積
- SPACING 按間距：槽鐵 @ c/c       每 m² 用量 = (1 ÷ 間距) × (1 + 損耗%) ÷ 每單位長度
- FIXED   固定數量：角鐵、螺絲等   每 m² 用量 = 設定數量 × (1 + 損耗%)
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

AREA = "AREA"
SPACING = "SPACING"
FIXED = "FIXED"

CENT = Decimal("0.01")
QTY_PLACES = Decimal("0.0001")


def _d(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def qty_per_sqm(method, coverage, layers=1, spacing_m=None, fixed_qty=None, wastage_pct=0):
    """傳回每 m² 所需數量（以材料計價單位計）。資料不足時傳回 None。"""
    coverage = _d(coverage)
    factor = Decimal("1") + _d(wastage_pct or 0) / Decimal("100")

    if method == AREA:
        if not coverage:
            return None
        return Decimal(layers or 1) * factor / coverage
    if method == SPACING:
        spacing = _d(spacing_m)
        if not spacing or not coverage:
            return None
        return (Decimal("1") / spacing) * factor / coverage
    if method == FIXED:
        fixed = _d(fixed_qty)
        if fixed is None:
            return None
        return fixed * factor
    raise ValueError(f"Unknown method: {method}")


def money(value):
    return _d(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_qty(value):
    return None if value is None else _d(value).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)


def line_cost(qty, unit_price):
    """每 m² 價錢 = 每 m² 用量 × 單價（用未四捨五入的用量計算）。"""
    if qty is None or unit_price is None:
        return None
    return money(_d(qty) * _d(unit_price))


# 這些單位可以按實際數量計，不用進位成整數（例如人工按 m²）
# 這些單位的訂購數量不進位（面積、長度、重量）；其他單位（張、支、件、粒）向上進位至整數
NO_ROUND_UNITS = {"m²", "m2", "sqm", "平方米", "m", "米", "kg", "公斤"}


def total_qty(qty_per_sqm, area):
    """總用量 = 每 m² 用量 × 總面積。"""
    if qty_per_sqm is None or area is None:
        return None
    return _d(qty_per_sqm) * _d(area)


def order_qty(total, unit):
    """建議訂購數量：張、支、件、粒等要買整數，向上進位；m² 等保留小數。"""
    if total is None:
        return None
    if unit in NO_ROUND_UNITS:
        return round_qty(total)
    return _d(total).quantize(Decimal("1"), rounding=ROUND_CEILING)


def total_cost(qty_per_sqm, area, unit_price):
    """總價 = 每 m² 用量 × 總面積 × 單價（用未四捨五入的用量計算）。"""
    if qty_per_sqm is None or area is None or unit_price is None:
        return None
    return money(_d(qty_per_sqm) * _d(area) * _d(unit_price))

"""純計算邏輯（不依賴 Django），方便單獨測試。

三種計算方式，對應 Enclosure 圖則圖例的寫法：
- AREA    按面積：板、岩棉        每 m² 用量 = 層數 × (1 + 損耗%) ÷ 每單位面積
- SPACING 按間距：槽鐵 @ c/c       每 m² 用量 = (1 ÷ 間距) × (1 + 損耗%) ÷ 每單位長度
- FIXED   固定數量：角鐵、螺絲等   每 m² 用量 = 設定數量 × (1 + 損耗%)
"""
from decimal import Decimal, ROUND_HALF_UP

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

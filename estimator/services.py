from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import calc
from .i18n import tr
from .models import FireSystem


@dataclass
class Line:
    item_no: int
    description: str
    material: str
    category: str
    unit: str
    method: str
    basis: str
    qty: Decimal | None
    unit_price: Decimal | None
    supplier: str
    price_date: date | None
    cost: Decimal | None
    note: str = ""
    total_qty: Decimal | None = None     # 有輸入總面積才有
    order_qty: Decimal | None = None
    total_cost: Decimal | None = None

    @property
    def pending(self):
        return self.cost is None

    @property
    def qty_pending(self):
        return self.qty is None


@dataclass
class Result:
    system: FireSystem
    on_date: date
    lines: list = field(default_factory=list)

    @property
    def total(self):
        return calc.money(sum((l.cost for l in self.lines if l.cost is not None), Decimal("0")))

    include_prices: bool = True
    area: Decimal | None = None          # 總面積 (m²)，可選

    @property
    def grand_total(self):
        """總面積的合計價錢（已計項目）。"""
        return calc.money(sum((l.total_cost for l in self.lines if l.total_cost is not None), Decimal("0")))

    @property
    def pending_lines(self):
        if not self.include_prices:
            return self.qty_pending_lines
        return [l for l in self.lines if l.pending]

    @property
    def qty_pending_lines(self):
        return [l for l in self.lines if l.qty_pending]


def _basis(c, coverage, unit):
    """計算依據的文字，按目前語言顯示。unit 已是翻譯後的單位。"""
    w = f"(1 + {c.wastage_pct.normalize():f}%)"
    cov = f"{coverage.normalize():f}"
    if c.method == calc.AREA:
        return tr("{layers} 層 × {w} ÷ {cov} m²/{unit}", layers=c.layers, w=w, cov=cov, unit=unit)
    if c.method == calc.SPACING:
        s = f"{c.spacing_m.normalize():f}" if c.spacing_m else "?"
        return tr("1 ÷ {s} m × {w} ÷ {cov} m/{unit}", s=s, w=w, cov=cov, unit=unit)
    if c.fixed_qty_per_sqm is None:
        return tr("每 m² 數量待定")
    return tr("{q} {unit}/m² × {w}", q=f"{c.fixed_qty_per_sqm.normalize():f}", unit=unit, w=w)


def find_system(brand, system_type, hours):
    return (
        FireSystem.objects.filter(
            brand=brand, system_type=system_type, fire_rating_hours=hours, active=True
        )
        .prefetch_related("components__material")
        .first()
    )


def calculate(system, on_date=None, include_prices=True, area=None):
    """計算一個系統每 m² 的材料用量和價錢；有 area（總面積 m²）時再計總用量和總價。

    include_prices=False：只計用量，完全不讀取價錢（給沒有價錢權限的用戶），
    所以價錢資料不會傳到網頁或 Excel。
    """
    on_date = on_date or date.today()
    result = Result(system=system, on_date=on_date, include_prices=include_prices, area=area)

    for c in system.components.select_related("material").all():
        m = c.material
        qty = calc.qty_per_sqm(
            c.method, m.coverage, layers=c.layers, spacing_m=c.spacing_m,
            fixed_qty=c.fixed_qty_per_sqm, wastage_pct=c.wastage_pct,
        )
        price = m.current_price(on_date) if include_prices else None
        unit_price = price.unit_price if price else None
        unit = m.display_unit()
        result.lines.append(Line(
            item_no=c.item_no,
            description=c.display_description(),
            material=m.display_name(),
            category=str(m.get_category_display()),
            unit=unit,
            method=str(c.get_method_display()),
            basis=_basis(c, m.coverage, unit),
            qty=calc.round_qty(qty),
            unit_price=unit_price,
            supplier=price.supplier if price else "",
            price_date=price.effective_date if price else None,
            cost=calc.line_cost(qty, unit_price),
            note=c.display_note(),
            total_qty=calc.round_qty(calc.total_qty(qty, area)),
            order_qty=calc.order_qty(calc.total_qty(qty, area), m.unit),
            total_cost=calc.total_cost(qty, area, unit_price),
        ))
    return result


def availability():
    """{brand: {system_type: [hours, ...]}}，供計價頁的下拉選單使用。"""
    data = {}
    for s in FireSystem.objects.filter(active=True):
        data.setdefault(s.brand, {}).setdefault(str(s.system_type), []).append(s.fire_rating_hours)
    return data

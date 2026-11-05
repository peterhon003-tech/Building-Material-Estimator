from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import calc
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

    @property
    def pending(self):
        return self.cost is None


@dataclass
class Result:
    system: FireSystem
    on_date: date
    lines: list = field(default_factory=list)

    @property
    def total(self):
        return calc.money(sum((l.cost for l in self.lines if l.cost is not None), Decimal("0")))

    @property
    def pending_lines(self):
        return [l for l in self.lines if l.pending]


def _basis(c, coverage, unit):
    w = f"(1 + {c.wastage_pct.normalize():f}%)"
    if c.method == calc.AREA:
        return f"{c.layers} 層 × {w} ÷ {coverage.normalize():f} m²/{unit}"
    if c.method == calc.SPACING:
        s = c.spacing_m.normalize() if c.spacing_m else "?"
        return f"1 ÷ {s} m × {w} ÷ {coverage.normalize():f} m/{unit}"
    if c.fixed_qty_per_sqm is None:
        return "每 m² 數量待定"
    return f"{c.fixed_qty_per_sqm.normalize():f} {unit}/m² × {w}"


def find_system(brand, system_type, hours):
    return (
        FireSystem.objects.filter(
            brand=brand, system_type=system_type, fire_rating_hours=hours, active=True
        )
        .prefetch_related("components__material")
        .first()
    )


def calculate(system, on_date=None):
    """計算一個系統每 m² 的材料用量和價錢。"""
    on_date = on_date or date.today()
    result = Result(system=system, on_date=on_date)

    for c in system.components.select_related("material").all():
        m = c.material
        qty = calc.qty_per_sqm(
            c.method, m.coverage, layers=c.layers, spacing_m=c.spacing_m,
            fixed_qty=c.fixed_qty_per_sqm, wastage_pct=c.wastage_pct,
        )
        price = m.current_price(on_date)
        unit_price = price.unit_price if price else None
        result.lines.append(Line(
            item_no=c.item_no,
            description=c.description,
            material=str(m),
            category=m.get_category_display(),
            unit=m.unit,
            method=c.get_method_display(),
            basis=_basis(c, m.coverage, m.unit),
            qty=calc.round_qty(qty),
            unit_price=unit_price,
            supplier=price.supplier if price else "",
            price_date=price.effective_date if price else None,
            cost=calc.line_cost(qty, unit_price),
            note=c.note,
        ))
    return result


def availability():
    """{brand: {system_type: [hours, ...]}}，供計價頁的下拉選單使用。"""
    data = {}
    for s in FireSystem.objects.filter(active=True):
        data.setdefault(s.brand, {}).setdefault(str(s.system_type), []).append(s.fire_rating_hours)
    return data

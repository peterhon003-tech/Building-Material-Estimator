from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import calc
from .i18n import tr
from .models import FireSystem, Material


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
    qty_exact: Decimal | None = None     # 未四捨五入的每 m² 用量（臨時調整時重算用）
    round_up: bool = True                # 訂購數量是否向上進位至整數
    code: str = ""                       # 材料編號
    options: list = field(default_factory=list)   # 臨時調整：同類別可替換的產品

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
    adjusted: bool = False               # 是否由用戶臨時調整（未儲存）

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


def _price_lookup(on_date, include_prices):
    """每種材料只查一次價錢。"""
    cache = {}

    def get(m):
        if not include_prices:
            return None
        if m.pk not in cache:
            cache[m.pk] = m.current_price(on_date)
        return cache[m.pk]
    return get


def calculate(system, on_date=None, include_prices=True, area=None, with_options=False):
    """計算一個系統每 m² 的材料用量和價錢；有 area（總面積 m²）時再計總用量和總價。

    include_prices=False：只計用量，完全不讀取價錢（給沒有價錢權限的用戶），
    所以價錢資料不會傳到網頁或 Excel。
    """
    on_date = on_date or date.today()
    result = Result(system=system, on_date=on_date, include_prices=include_prices, area=area)
    price_of = _price_lookup(on_date, include_prices)
    by_category = {}
    if with_options:
        for m in Material.objects.filter(active=True).order_by("code"):
            by_category.setdefault(m.category, []).append(m)

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
            qty_exact=qty,
            round_up=m.unit not in calc.NO_ROUND_UNITS,
            code=m.code,
            options=_component_options(c, m, by_category, price_of) if with_options else [],
        ))
    return result


def _component_options(c, original, by_category, price_of):
    """同類別的材料都可以選。用量按這個組件的計算方式（層數、間距、損耗）由伺服器計好。"""
    candidates = [original] + [m for m in by_category.get(original.category, []) if m.pk != original.pk]
    options = []
    for m in candidates:
        qty = calc.qty_per_sqm(
            c.method, m.coverage, layers=c.layers, spacing_m=c.spacing_m,
            fixed_qty=c.fixed_qty_per_sqm, wastage_pct=c.wastage_pct,
        )
        opt = {
            "code": m.code, "label": m.display_name(), "unit": m.display_unit(),
            "qty": None if qty is None else str(qty),
            "basis": _basis(c, m.coverage, m.display_unit()),
            "round_up": m.unit not in calc.NO_ROUND_UNITS,
            "original": m.pk == original.pk,
        }
        _add_price(opt, price_of(m))
        options.append(opt)
    return options


def _add_price(opt, price):
    """只有可以看價錢時 price_of 才會傳回價錢；否則選項完全沒有價錢資料。"""
    if price is not None:
        opt.update({"unit_price": str(price.unit_price), "supplier": price.supplier,
                    "price_date": price.effective_date.isoformat()})


def material_catalogue(include_prices, on_date=None):
    """「新增項目」可選的所有材料（按類別排列）。沒有價錢權限時不包括價錢。"""
    price_of = _price_lookup(on_date or date.today(), include_prices)
    items = []
    for m in Material.objects.filter(active=True).order_by("category", "code"):
        opt = {"code": m.code, "label": m.display_name(), "unit": m.display_unit(),
               "category": str(m.get_category_display()),
               "round_up": m.unit not in calc.NO_ROUND_UNITS}
        _add_price(opt, price_of(m))
        items.append(opt)
    return items


def availability():
    """{brand: {system_type: [hours, ...]}}，供計價頁的下拉選單使用。"""
    data = {}
    for s in FireSystem.objects.filter(active=True):
        data.setdefault(s.brand, {}).setdefault(str(s.system_type), []).append(s.fire_rating_hours)
    return data


def _s(value):
    return None if value is None else str(value)


def adjust_payload(result, brand, system_type, hours, view):
    """把計價結果轉成網頁「臨時調整」用的資料。沒有價錢權限時不包括任何價錢。"""
    show = result.include_prices
    lines = []
    for l in result.lines:
        row = {
            "item_no": l.item_no, "description": l.description, "material": l.material,
            "unit": l.unit, "method": l.method, "basis": l.basis, "note": l.note,
            "qty": _s(l.qty_exact), "qty_display": _s(l.qty), "round_up": l.round_up,
            "total_qty": _s(l.total_qty), "order_qty": _s(l.order_qty), "state": "original",
            "code": l.code, "options": l.options,
        }
        if show:
            row.update({
                "unit_price": _s(l.unit_price), "supplier": l.supplier,
                "price_date": l.price_date.isoformat() if l.price_date else "",
                "cost": _s(l.cost), "total_cost": _s(l.total_cost),
            })
        lines.append(row)
    return {
        "brand": brand, "system_type": system_type, "hours": hours, "view": view,
        "area": _s(result.area), "show_prices": show, "lines": lines,
        "catalogue": material_catalogue(show, result.on_date),
    }


def adjusted_result(system, area, rows, include_prices, t=None):
    """用網頁送來的調整後明細建立 Result（不讀取、不寫入數據庫的價錢和配方）。"""
    from .adjust import compute_rows
    kwargs = {"t": t} if t else {}
    result = Result(system=system, on_date=date.today(), include_prices=include_prices,
                    area=area, adjusted=True)
    for d in compute_rows(rows, area, include_prices, **kwargs):
        result.lines.append(Line(**d))
    return result

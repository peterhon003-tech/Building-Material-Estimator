from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import calc, formula, partition
from .i18n import tr
from .models import FireSystem, Material


@dataclass
class PartitionInput:
    """Partition 的牆高和 stud 屈服強度。"""
    height_mm: int
    stress: int

    @property
    def height_m(self):
        return Decimal(self.height_mm) / Decimal(1000)

    def label(self):
        return tr("牆高 {h} m · {s} N/mm²", h=f"{self.height_m.normalize():f}", s=self.stress)


def parse_partition(system, height, stress):
    """讀取並檢查牆高和屈服強度（來自網址或網頁送來的資料）。

    傳回 (PartitionInput 或 None, 錯誤訊息)。不是 Partition 系統 → (None, "")。
    """
    if system is None or not system.is_partition:
        return None, ""
    try:
        stress = int(stress or partition.DEFAULT_STRESS)
    except (TypeError, ValueError):
        stress = partition.DEFAULT_STRESS
    if stress not in dict(partition.STRESS_CHOICES):
        stress = partition.DEFAULT_STRESS
    try:
        height = int(height)
    except (TypeError, ValueError):
        return None, tr("請選擇牆高。")
    if height not in system.height_options(stress):
        return None, tr("牆高不在這個系統的選項內，請重新選擇。")
    return PartitionInput(height, stress), ""


def system_label(system, part=None):
    """系統名稱；Partition 加上牆高和屈服強度（用於計價紀錄、報價、Excel）。"""
    return f"{system} · {part.label()}" if part else str(system)


def partition_choices():
    """{brand: {system_type: {hours: {stress: [牆高 mm, ...]}}}}，供計價頁的牆高選單使用。"""
    data = {}
    for s in FireSystem.objects.filter(active=True, system_type__in=FireSystem.PARTITION_TYPES) \
            .prefetch_related("stud_rules"):
        data.setdefault(s.brand, {}).setdefault(str(s.system_type), {})[str(s.fire_rating_hours)] = {
            str(v): s.height_options(v) for v, _ in partition.STRESS_CHOICES}
    return data


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
    wastage_pct: Decimal | None = None   # 損耗 %（臨時調整可修改）
    qty_w0: Decimal | None = None        # 損耗 0% 時的每 m² 用量
    qty_slope: Decimal | None = None     # 損耗每加 1% 增加的用量（用量 = qty_w0 + qty_slope × 損耗）

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
    partition: "PartitionInput | None" = None   # Partition 的牆高和屈服強度
    stud: str = ""                       # Partition：揀選的 stud（顯示用）

    @property
    def label(self):
        return system_label(self.system, self.partition)

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


def _num(d):
    return f"{Decimal(d).normalize():f}"


def _basis(c, coverage, unit, ctx=None):
    """計算依據的文字，按目前語言顯示。unit 已是翻譯後的單位。ctx：Partition 的計算資料。"""
    w = f"(1 + {c.wastage_pct.normalize():f}%)"
    cov = f"{coverage.normalize():f}"
    if c.formula.strip():
        return _custom_basis(c, coverage, ctx)
    if c.method in calc.HEIGHT_METHODS:
        return _height_basis(c, coverage, unit, ctx, w, cov)
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


@dataclass
class _HeightCtx:
    """Partition 計算時共用的資料。"""
    part: "PartitionInput | None"
    choice: object = None               # partition.StudChoice；找不到合用 stud 時 None
    needed: list = field(default_factory=list)   # 報告容許的規格（找不到時提示）


def _height_ctx(system, part):
    if not system.is_partition:
        return None
    ctx = _HeightCtx(part=part)
    if part is None:
        return ctx
    rules = system.stud_table()
    channels = Material.objects.filter(active=True, category="CHANNEL").order_by("code")
    ctx.choice = partition.pick_stud(rules, part.stress, part.height_mm, channels)
    if ctx.choice is None:
        ctx.needed = partition.minimum_needed(rules, part.stress, part.height_mm)
    return ctx


def _stud_spacing(c):
    return c.spacing_m or Decimal("0.610")


def _formula_values(c, m, ctx, w=None):
    """公式變數的數值（中文名稱）。沒有的變數為 None（用到就變成待定）。w：代替組件的損耗 %。"""
    height = ctx.part.height_m if ctx is not None and ctx.part is not None else None
    spacing = _stud_spacing(c) if c.method == calc.STUD else c.spacing_m
    return {"層數": c.layers or 1, "涵蓋量": m.coverage or None, "間距": spacing,
            "每平方米數量": c.fixed_qty_per_sqm, "損耗": (c.wastage_pct or 0) if w is None else w, "牆高": height}


def _qty(c, m, ctx, w=None):
    """一個組件用材料 m 時的每 m² 用量（未四捨五入）。資料不足時 None。w：代替組件的損耗 %。"""
    w = c.wastage_pct if w is None else w
    if c.formula.strip():                       # 管理員填了自訂公式
        try:
            return formula.evaluate(c.formula, _formula_values(c, m, ctx, w))
        except formula.FormulaError:
            return None
    if c.method not in calc.HEIGHT_METHODS:
        return calc.qty_per_sqm(c.method, m.coverage, layers=c.layers, spacing_m=c.spacing_m,
                                fixed_qty=c.fixed_qty_per_sqm, wastage_pct=w)
    if ctx is None or ctx.part is None:
        return None
    if c.method == calc.STUD:
        return calc.qty_per_sqm(calc.SPACING, m.coverage, spacing_m=_stud_spacing(c), wastage_pct=w)
    if c.method == calc.TRACK:
        return partition.track_qty(ctx.part.height_m, m.coverage, w)
    return partition.anchor_qty(ctx.part.height_m, c.spacing_m, w)


def formula_preview(c, ctx_cache=None):
    """系統管理用：一個組件的公式變數數值和試算的每 m² 用量。

    Partition 用第一個牆高選項（350 N/mm²）試算；傳回 dict(material, values, used, qty, part)。
    ctx_cache：同一系統的組件共用揀 stud 的結果（dict，鍵為系統 id）。
    """
    system = c.system
    part = None
    if system.is_partition:
        heights = system.height_options(partition.DEFAULT_STRESS)
        if heights:
            part = PartitionInput(heights[0], partition.DEFAULT_STRESS)
    if ctx_cache is not None and system.pk in ctx_cache:
        ctx = ctx_cache[system.pk]
    else:
        ctx = _height_ctx(system, part)
        if ctx_cache is not None:
            ctx_cache[system.pk] = ctx
    m = _material_for(c, ctx)
    try:
        used = formula.variables_used(c.active_formula())
    except formula.FormulaError:
        used = []
    qty = _qty(c, m, ctx)
    if c.method in (calc.STUD, calc.TRACK) and ctx is not None and ctx.choice is None:
        qty = None
    return {"material": m, "values": _formula_values(c, m, ctx), "used": used, "qty": qty, "part": part}


def _wastage_line(c, m, ctx):
    """損耗 0% 和 100% 的用量 → (損耗 0% 用量, 每 1% 增加量)，供網頁調整損耗時重算。資料不足時 (None, None)。"""
    q0, q100 = _qty(c, m, ctx, Decimal("0")), _qty(c, m, ctx, Decimal("100"))
    if q0 is None or q100 is None:
        return None, None
    return q0, (q100 - q0) / Decimal("100")


def _custom_basis(c, coverage, ctx):
    """自訂公式的計算依據：公式 +（用到的變數 = 數值）。"""
    from types import SimpleNamespace
    text = c.formula.strip()
    try:
        used = formula.variables_used(text)
    except formula.FormulaError:
        return tr("自訂公式有錯誤：{f}", f=text)
    values = _formula_values(c, SimpleNamespace(coverage=coverage), ctx)
    shown = text
    for name in formula.VARIABLES:              # 英文介面時，變數名稱也翻譯
        shown = shown.replace(name, tr(name))
    parts = [f"{tr(k)} = {_num(values[k]) if values[k] is not None else '?'}" for k in used]
    return tr("自訂公式：{f}", f=shown) + (f"（{'，'.join(parts)}）" if parts else "")


def _height_basis(c, coverage, unit, ctx, w, cov):
    h = _num(ctx.part.height_m) if ctx and ctx.part else "?"
    if c.method == calc.STUD:
        return tr("1 ÷ {s} m × {w} ÷ {cov} m/{unit}", s=_num(_stud_spacing(c)), w=w, cov=cov, unit=unit)
    if c.method == calc.TRACK:
        return tr("2 ÷ 牆高 {h} m × {w} ÷ {cov} m/{unit}", h=h, w=w, cov=cov, unit=unit)
    s = _num(c.spacing_m) if c.spacing_m else "?"
    return tr("2 ÷ {s} m ÷ 牆高 {h} m × {w}", s=s, h=h, w=w)


def _material_for(c, ctx):
    """Stud 和頂底槽用揀選的槽鐵；其他用配方設定的材料。"""
    if c.method in (calc.STUD, calc.TRACK) and ctx is not None and ctx.choice is not None:
        return ctx.choice.material
    return c.material


def _height_note(c, ctx):
    """Partition 行的額外備註：揀選依據，或找不到合用 stud 的原因。"""
    if c.method not in (calc.STUD, calc.TRACK) or ctx is None or ctx.part is None:
        return ""
    if ctx.choice is not None:
        r = ctx.choice.rule
        if c.method == calc.STUD:
            return tr("報告 stud 表：{spec} 最高 {h} mm（{s} N/mm²）",
                      spec=r.label(), h=r.max_height_mm, s=r.stress)
        return tr("和 stud 相同的槽鐵")
    if ctx.needed:
        return tr("材料表沒有合用的槽鐵，報告最少要：{specs}",
                  specs="、".join(r.label() for r in ctx.needed[:3]))
    return tr("報告沒有這個牆高的 stud 規格")


def calculate(system, on_date=None, include_prices=True, area=None, with_options=False, part=None):
    """計算一個系統每 m² 的材料用量和價錢；有 area（總面積 m²）時再計總用量和總價。

    include_prices=False：只計用量，完全不讀取價錢（給沒有價錢權限的用戶），
    所以價錢資料不會傳到網頁或 Excel。
    part：Partition 的牆高和屈服強度（PartitionInput）；stud、頂底槽和螺栓按它計。
    """
    on_date = on_date or date.today()
    result = Result(system=system, on_date=on_date, include_prices=include_prices, area=area, partition=part)
    price_of = _price_lookup(on_date, include_prices)
    ctx = _height_ctx(system, part)
    if ctx is not None and ctx.choice is not None:
        result.stud = ctx.choice.material.display_name()
    by_category = {}
    if with_options:
        for m in Material.objects.filter(active=True).order_by("code"):
            by_category.setdefault(m.category, []).append(m)

    for c in system.components.select_related("material").all():
        m = _material_for(c, ctx)
        qty = _qty(c, m, ctx)
        no_stud = c.method in (calc.STUD, calc.TRACK) and ctx is not None and ctx.choice is None
        if no_stud:
            qty = None                      # 沒有合用 stud：不可以用配方的預設槽鐵計
        w0, slope = (None, None) if no_stud else _wastage_line(c, m, ctx)
        price = None if no_stud else price_of(m)
        unit_price = price.unit_price if price else None
        unit = m.display_unit()
        note = "；".join(x for x in (c.display_note(), _height_note(c, ctx)) if x)
        result.lines.append(Line(
            item_no=c.item_no,
            description=c.display_description(),
            material=tr("未有合用的槽鐵") if no_stud else m.display_name(),
            category=str(m.get_category_display()),
            unit=unit,
            method=str(c.get_method_display()) + (tr("（自訂公式）") if c.formula.strip() else ""),
            basis=_basis(c, m.coverage, unit, ctx),
            qty=calc.round_qty(qty),
            unit_price=unit_price,
            supplier=price.supplier if price else "",
            price_date=price.effective_date if price else None,
            cost=calc.line_cost(qty, unit_price),
            note=note,
            total_qty=calc.round_qty(calc.total_qty(qty, area)),
            order_qty=calc.order_qty(calc.total_qty(qty, area), m.unit),
            total_cost=calc.total_cost(qty, area, unit_price),
            qty_exact=qty,
            round_up=m.unit not in calc.NO_ROUND_UNITS,
            code="" if no_stud else m.code,
            options=_component_options(c, m, by_category, price_of, ctx) if with_options else [],
            wastage_pct=c.wastage_pct,
            qty_w0=w0,
            qty_slope=slope,
        ))
    return result


def _component_options(c, original, by_category, price_of, ctx=None):
    """同類別的材料都可以選。用量按這個組件的計算方式（層數、間距、損耗、牆高）由伺服器計好。"""
    candidates = [original] + [m for m in by_category.get(original.category, []) if m.pk != original.pk]
    options = []
    for m in candidates:
        qty = _qty(c, m, ctx)
        q0, slope = _wastage_line(c, m, ctx)
        opt = {
            "code": m.code, "label": m.display_name(), "unit": m.display_unit(),
            "qty": None if qty is None else str(qty),
            "qty0": None if q0 is None else str(q0), "slope": None if slope is None else str(slope),
            "basis": _basis(c, m.coverage, m.display_unit(), ctx),
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
            "wastage": None if l.wastage_pct is None else f"{l.wastage_pct.normalize():f}",
            "qty0": _s(l.qty_w0), "slope": _s(l.qty_slope),
        }
        if show:
            row.update({
                "unit_price": _s(l.unit_price), "supplier": l.supplier,
                "price_date": l.price_date.isoformat() if l.price_date else "",
                "cost": _s(l.cost), "total_cost": _s(l.total_cost),
            })
        lines.append(row)
    part = result.partition
    return {
        "brand": brand, "system_type": system_type, "hours": hours, "view": view,
        "height": part.height_mm if part else None, "stress": part.stress if part else None,
        "area": _s(result.area), "show_prices": show, "lines": lines,
        "catalogue": material_catalogue(show, result.on_date),
    }


def adjusted_result(system, area, rows, include_prices, t=None, part=None):
    """用網頁送來的調整後明細建立 Result（不讀取、不寫入數據庫的價錢和配方）。"""
    from .adjust import compute_rows
    kwargs = {"t": t} if t else {}
    result = Result(system=system, on_date=date.today(), include_prices=include_prices,
                    area=area, adjusted=True, partition=part)
    for d in compute_rows(rows, area, include_prices, **kwargs):
        result.lines.append(Line(**d))
    return result

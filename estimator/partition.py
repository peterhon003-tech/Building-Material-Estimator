"""Partition（間隔牆）：按牆高和 stud 屈服強度揀 stud，計頂底槽和膨脹螺栓（不依賴 Django，方便測試）。

Stud 表來自測試報告（每種 stud 可做的最高高度）：
  StudRule(屈服強度 N/mm², web mm, flange mm, 厚度 mm, 最高高度 mm)

揀選方法（用戶確認：「最輕而合用」）：
  1. 找出所有「最高高度 ≥ 牆高」的 stud 規格；
  2. 每個規格在材料表找 web、flange、厚度都 ≥ 規格的槽鐵（找不到相同的就用較大的）；
  3. 在所有合用的槽鐵中，揀用鋼最少的：(web + 2 × flange) × 厚度；
     一樣時揀每支長度 ≥ 牆高的（免駁接），再按編號。

槽鐵的尺寸由材料「規格」讀取，格式「邊 × 底 × 邊 × 厚度mm」，例如 30×50×30×0.6mm
（即報價單 0.6×30×50×30：flange 30、web 50）。
"""
import re
from dataclasses import dataclass
from decimal import Decimal

STRESS_CHOICES = [(350, "350 N/mm²"), (200, "200 N/mm²")]
DEFAULT_STRESS = 350

_NUM = r"(\d+(?:\.\d+)?)"
_SEP = r"\s*[×xX*]\s*"
CHANNEL_SPEC = re.compile(_NUM + _SEP + _NUM + _SEP + _NUM + _SEP + _NUM + r"\s*mm")


@dataclass(frozen=True)
class ChannelSize:
    flange: Decimal
    web: Decimal
    thickness: Decimal

    @property
    def steel(self):
        """用鋼量指標（截面積 mm²）。"""
        return (self.web + 2 * self.flange) * self.thickness


def parse_channel(spec):
    """由規格文字讀出槽鐵尺寸；兩邊 flange 不同或讀不到就傳回 None。"""
    m = CHANNEL_SPEC.search(spec or "")
    if not m:
        return None
    f1, web, f2, t = (Decimal(x) for x in m.groups())
    if f1 != f2 or min(f1, web, t) <= 0:
        return None
    return ChannelSize(flange=f1, web=web, thickness=t)


@dataclass(frozen=True)
class StudRule:
    stress: int
    web: Decimal
    flange: Decimal
    thickness: Decimal
    max_height_mm: int

    def label(self):
        return f"{_n(self.web)}×{_n(self.flange)}×{_n(self.thickness)}mm"


@dataclass
class StudChoice:
    material: object          # 材料（Django Material 或測試用物件，要有 code、spec、coverage）
    size: ChannelSize
    rule: StudRule            # 令這款槽鐵合用的報告規格


def _n(d):
    return f"{Decimal(d).normalize():f}"


def allowed_rules(rules, stress, height_mm):
    return [r for r in rules if r.stress == stress and r.max_height_mm >= height_mm]


def pick_stud(rules, stress, height_mm, materials):
    """materials：可選的槽鐵（已啟用）。傳回 StudChoice；沒有合用的傳回 None。"""
    candidates = []
    for m in materials:
        size = parse_channel(m.spec)
        if size is None:
            continue
        fits = [r for r in allowed_rules(rules, stress, height_mm)
                if size.web >= r.web and size.flange >= r.flange and size.thickness >= r.thickness]
        if not fits:
            continue
        # 同一款槽鐵合用多個規格時，記錄最接近的那個（用鋼最少的規格）
        rule = min(fits, key=lambda r: ((r.web + 2 * r.flange) * r.thickness, r.web))
        long_enough = Decimal(m.coverage or 0) * 1000 >= height_mm
        candidates.append((size.steel, not long_enough, m.code, StudChoice(m, size, rule)))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3])
    return candidates[0][3]


def minimum_needed(rules, stress, height_mm):
    """找不到合用槽鐵時提示用：報告容許的規格（按用鋼量排列）。"""
    ok = allowed_rules(rules, stress, height_mm)
    return sorted(ok, key=lambda r: ((r.web + 2 * r.flange) * r.thickness, r.web))


def max_height(rules, stress):
    heights = [r.max_height_mm for r in rules if r.stress == stress]
    return max(heights) if heights else None


# ---------- 每 m² 用量 ----------

def track_qty(height_m, coverage, wastage_pct=0):
    """頂槽 + 底槽：每 m² 牆 = 2 ÷ 牆高（m 長），再 ÷ 每支長度。"""
    if not height_m or not coverage:
        return None
    factor = Decimal("1") + Decimal(wastage_pct or 0) / Decimal("100")
    return Decimal("2") / Decimal(height_m) * factor / Decimal(coverage)


def anchor_qty(height_m, spacing_m, wastage_pct=0):
    """頂槽和底槽的膨脹螺栓：每 m² 牆 = 2 條 × (1 ÷ 間距) ÷ 牆高。"""
    if not height_m or not spacing_m:
        return None
    factor = Decimal("1") + Decimal(wastage_pct or 0) / Decimal("100")
    return Decimal("2") / Decimal(spacing_m) / Decimal(height_m) * factor

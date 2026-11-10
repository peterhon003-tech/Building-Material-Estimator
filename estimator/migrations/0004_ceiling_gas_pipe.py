"""系統類型改為 Enclosure for Ceiling / Enclosure for Gas Pipe / Partition。

- 舊的 1 = Enclosure 改名為 Enclosure for Ceiling（編號不變，計價紀錄和報價不受影響）
- 現有 Ceiling 系統的槽鐵和連牆角鐵改為每 m² 固定支數（1.0815、0.8605，另加 10% 損耗）。
  只改動仍是原本設定的組件（槽鐵仍按間距、連牆角鐵仍是待定），管理員已手動修改的不會覆蓋。
- Enclosure for Gas Pipe 系統由 seed_data 在啟動時自動建立。
"""
from decimal import Decimal

from django.db import migrations, models

# 數值寫在這裡（不從 seed.py 匯入），以後改 seed.py 也不會改變這個 migration 的效果
CEILING = 1
STEEL_QTY = {2: "1.0815", 3: "0.8605"}          # 圖例編號 → 每 m² 支數（未計損耗）
STEEL_WASTE = "10"
SPEC_NOTE = "報價單寫 1.0×50×100×50，請確認規格"
SPEC_NOTE_EN = "quotation shows 1.0×50×100×50, please confirm the size"


def steel_note(qty, extra=""):
    base = f"Ceiling：每 m² {qty} 支（未計損耗）"
    return f"{base}；{extra}" if extra else base


def steel_note_en(qty, extra_en=""):
    base = f"Ceiling: {qty} pcs per m² (before wastage)"
    return f"{base}; {extra_en}" if extra_en else base


def update_ceiling(apps, schema_editor):
    FireSystem = apps.get_model("estimator", "FireSystem")
    for system in FireSystem.objects.filter(system_type=CEILING):
        for c in system.components.select_related("material"):
            qty = STEEL_QTY.get(c.item_no)
            if qty is None:
                continue
            is_channel = c.item_no == 2 and c.method == "SPACING" and c.material.category == "CHANNEL"
            is_wall_angle = (c.item_no == 3 and c.method == "FIXED" and c.fixed_qty_per_sqm is None
                             and c.material.category == "ANGLE")
            if not (is_channel or is_wall_angle):
                continue
            extra = SPEC_NOTE if SPEC_NOTE in (c.note or "") else ""
            c.method = "FIXED"
            c.layers = 1
            c.spacing_m = None
            c.fixed_qty_per_sqm = Decimal(qty)
            c.wastage_pct = Decimal(STEEL_WASTE)
            c.note = steel_note(qty, extra)
            c.note_en = steel_note_en(qty, SPEC_NOTE_EN if extra else "")
            c.save()


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0003_default_language"),
    ]

    operations = [
        migrations.AlterField(
            model_name="firesystem",
            name="system_type",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "Enclosure for Ceiling"), (3, "Enclosure for Gas Pipe"), (2, "Partition")],
                verbose_name="系統"),
        ),
        migrations.RunPython(update_ceiling, migrations.RunPython.noop),
    ]

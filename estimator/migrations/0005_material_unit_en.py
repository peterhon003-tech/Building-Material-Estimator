"""材料加入「英文計價單位」，並按現有單位填上英文（只填空白的）。"""
from django.db import migrations, models

# 現有中文單位 → 英文（和翻譯表一致）
UNITS_EN = {"張": "sheet", "支": "pc", "件": "pc", "粒": "nos", "m²": "m²", "米": "m", "公斤": "kg"}


def fill_unit_en(apps, schema_editor):
    Material = apps.get_model("estimator", "Material")
    for m in Material.objects.filter(unit_en=""):
        if m.unit in UNITS_EN:
            m.unit_en = UNITS_EN[m.unit]
        elif m.unit.isascii():
            m.unit_en = m.unit                       # 已經是英文（例如 pc、no.），中文單位之後在 Excel 修改
        else:
            continue
        m.save(update_fields=["unit_en"])


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0004_ceiling_gas_pipe"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="unit_en",
            field=models.CharField(blank=True, help_text="英文介面使用，例如 sheet、pc、nos；留空就按系統翻譯顯示",
                                   max_length=20, verbose_name="英文計價單位"),
        ),
        migrations.RunPython(fill_unit_en, migrations.RunPython.noop),
    ]

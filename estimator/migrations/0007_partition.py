"""Partition 系統：Partition Promina（新編號 4）及 Partition Promat-H（舊編號 2 改名）。

- 系統加「牆高選項」，新增 Stud 表（每種 stud 可做的最高牆高）
- 組件新增計算方式：Stud（按牆高揀）、頂底槽、頂底槽螺栓
- 配方和 stud 表由 seed_data 在啟動時建立（材料要先匯入）
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0006_material_log"),
    ]

    operations = [
        migrations.AlterField(
            model_name="firesystem",
            name="system_type",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "Enclosure for Ceiling"), (3, "Enclosure for Gas Pipe"),
                         (4, "Partition Promina"), (2, "Partition Promat-H")],
                verbose_name="系統"),
        ),
        migrations.AddField(
            model_name="firesystem",
            name="partition_heights",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="牆高選項 (mm)",
                help_text='只用於 Partition：每個屈服強度的牆高選項，例如 {"350": [3300, 4000], "200": [3100, 4000]}；'
                          '留空就用 stud 表的高度'),
        ),
        migrations.AlterField(
            model_name="systemcomponent",
            name="method",
            field=models.CharField(
                choices=[("AREA", "按面積"), ("SPACING", "按間距"), ("FIXED", "固定數量"),
                         ("STUD", "Stud（按牆高揀）"), ("TRACK", "頂底槽（按牆高）"),
                         ("ANCHOR", "頂底槽螺栓（按牆高）")],
                max_length=10, verbose_name="計算方式"),
        ),
        migrations.CreateModel(
            name="StudRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("yield_stress", models.PositiveSmallIntegerField(
                    choices=[(350, "350 N/mm²"), (200, "200 N/mm²")], verbose_name="屈服強度 (N/mm²)")),
                ("web_mm", models.DecimalField(decimal_places=1, max_digits=6, verbose_name="Web (mm)")),
                ("flange_mm", models.DecimalField(decimal_places=1, max_digits=6, verbose_name="Flange (mm)")),
                ("thickness_mm", models.DecimalField(decimal_places=2, max_digits=4, verbose_name="厚度 (mm)")),
                ("max_height_mm", models.PositiveIntegerField(verbose_name="最高牆高 (mm)")),
                ("system", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="stud_rules", to="estimator.firesystem",
                                             verbose_name="系統")),
            ],
            options={
                "verbose_name": "Stud 表",
                "verbose_name_plural": "Stud 表",
                "ordering": ["system", "-yield_stress", "web_mm", "thickness_mm"],
            },
        ),
    ]

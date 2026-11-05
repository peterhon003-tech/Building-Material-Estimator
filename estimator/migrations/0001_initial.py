import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FireSystem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("brand", models.CharField(choices=[("PROMAT", "Promat"), ("DURASTEEL", "Durasteel")], max_length=20, verbose_name="品牌")),
                ("system_type", models.PositiveSmallIntegerField(choices=[(1, "Enclosure"), (2, "Partition")], verbose_name="系統")),
                ("fire_rating_hours", models.PositiveSmallIntegerField(choices=[(1, "1 小時"), (2, "2 小時"), (4, "4 小時")], verbose_name="耐火時間")),
                ("frr_label", models.CharField(blank=True, max_length=30, verbose_name="F.R.R.")),
                ("report_no", models.CharField(blank=True, max_length=50, verbose_name="測試報告編號")),
                ("drawing_ref", models.CharField(blank=True, max_length=200, verbose_name="圖則")),
                ("overall_thickness_mm", models.PositiveIntegerField(blank=True, null=True, verbose_name="系統總厚度 (mm)")),
                ("active", models.BooleanField(default=True, verbose_name="啟用")),
                ("notes", models.TextField(blank=True, verbose_name="備註")),
            ],
            options={
                "verbose_name": "系統",
                "verbose_name_plural": "系統",
                "ordering": ["brand", "system_type", "fire_rating_hours"],
                "constraints": [
                    models.UniqueConstraint(fields=("brand", "system_type", "fire_rating_hours"), name="unique_fire_system"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Material",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="編號")),
                ("name", models.CharField(max_length=100, verbose_name="名稱")),
                ("spec", models.CharField(blank=True, max_length=100, verbose_name="規格")),
                ("category", models.CharField(choices=[("BOARD", "板"), ("CHANNEL", "槽鐵"), ("ANGLE", "角鐵"), ("ROCKWOOL", "岩棉"), ("FIXING", "螺絲及螺栓"), ("SEALANT", "膠"), ("LABOUR", "人工")], max_length=20, verbose_name="類別")),
                ("unit", models.CharField(help_text="例如：張、支、件、粒、m²", max_length=20, verbose_name="計價單位")),
                ("coverage", models.DecimalField(decimal_places=4, default=1, help_text="板／岩棉填每單位面積 (m²)，鐵料填每支長度 (m)，其他填 1", max_digits=10, verbose_name="每單位涵蓋量")),
                ("active", models.BooleanField(default=True, verbose_name="使用中")),
            ],
            options={
                "verbose_name": "材料",
                "verbose_name_plural": "材料",
                "ordering": ["category", "code"],
            },
        ),
        migrations.CreateModel(
            name="MaterialPrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("supplier", models.CharField(blank=True, max_length=100, verbose_name="供應商")),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="單價 (HK$)")),
                ("effective_date", models.DateField(verbose_name="生效日期")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="備註")),
                ("updated_by", models.CharField(blank=True, max_length=150, verbose_name="修改人")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("material", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="prices", to="estimator.material", verbose_name="材料")),
            ],
            options={
                "verbose_name": "材料價錢",
                "verbose_name_plural": "材料價錢",
                "ordering": ["-effective_date", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SystemComponent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_no", models.PositiveSmallIntegerField(verbose_name="圖例編號")),
                ("description", models.CharField(max_length=100, verbose_name="項目")),
                ("method", models.CharField(choices=[("AREA", "按面積"), ("SPACING", "按間距"), ("FIXED", "固定數量")], max_length=10, verbose_name="計算方式")),
                ("layers", models.PositiveSmallIntegerField(default=1, verbose_name="層數")),
                ("spacing_m", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True, verbose_name="間距 c/c (m)")),
                ("fixed_qty_per_sqm", models.DecimalField(blank=True, decimal_places=4, help_text="留空 = 待定（不計入總價）", max_digits=10, null=True, verbose_name="每 m² 固定數量")),
                ("wastage_pct", models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name="損耗 %")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="備註")),
                ("material", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="estimator.material", verbose_name="材料")),
                ("system", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="components", to="estimator.firesystem", verbose_name="系統")),
            ],
            options={
                "verbose_name": "系統組件",
                "verbose_name_plural": "系統組件",
                "ordering": ["item_no", "id"],
            },
        ),
    ]

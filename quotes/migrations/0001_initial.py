import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Quotation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.CharField(max_length=20, verbose_name="報價編號")),
                ("revision", models.CharField(default="A", max_length=4, verbose_name="版本")),
                ("status", models.CharField(choices=[("draft", "草稿"), ("issued", "已發出"), ("cancelled", "已取消")], default="draft", max_length=10, verbose_name="狀態")),
                ("customer_name", models.CharField(blank=True, max_length=200, verbose_name="客戶名稱")),
                ("contact", models.CharField(blank=True, max_length=200, verbose_name="聯絡人及電話")),
                ("project", models.TextField(blank=True, verbose_name="工程名稱及地址")),
                ("remarks", models.TextField(blank=True, verbose_name="備註")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("updated_by", models.CharField(blank=True, max_length=150, verbose_name="最後修改人")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="最後修改時間")),
                ("issued_at", models.DateTimeField(blank=True, null=True, verbose_name="發出時間")),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="quotations", to=settings.AUTH_USER_MODEL, verbose_name="建立人")),
                ("revised_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="quotes.quotation", verbose_name="由此版本修改")),
            ],
            options={
                "verbose_name": "報價",
                "verbose_name_plural": "報價",
                "ordering": ["-updated_at"],
                "constraints": [models.UniqueConstraint(fields=("number", "revision"), name="quote_number_revision")],
            },
        ),
        migrations.CreateModel(
            name="QuotationItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=1, verbose_name="次序")),
                ("title", models.CharField(blank=True, max_length=200, verbose_name="位置 / 說明")),
                ("brand", models.CharField(max_length=20, verbose_name="品牌")),
                ("system_type", models.PositiveSmallIntegerField(verbose_name="系統")),
                ("fire_rating_hours", models.PositiveSmallIntegerField(verbose_name="耐火時間")),
                ("system_label", models.CharField(max_length=200, verbose_name="系統")),
                ("frr_label", models.CharField(blank=True, max_length=50, verbose_name="F.R.R.")),
                ("report_no", models.CharField(blank=True, max_length=50, verbose_name="測試報告")),
                ("area", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="總面積")),
                ("include_prices", models.BooleanField(default=False, verbose_name="包括價錢")),
                ("price_date", models.DateField(blank=True, null=True, verbose_name="價錢日期")),
                ("adjusted", models.BooleanField(default=False, verbose_name="已手動調整")),
                ("total_per_sqm", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True, verbose_name="每 m² 合計")),
                ("grand_total", models.DecimalField(blank=True, decimal_places=2, max_digits=24, null=True, verbose_name="合計")),
                ("quotation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="quotes.quotation", verbose_name="報價")),
            ],
            options={
                "verbose_name": "報價項目",
                "verbose_name_plural": "報價項目",
                "ordering": ["position", "id"],
            },
        ),
        migrations.CreateModel(
            name="QuotationLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=1, verbose_name="次序")),
                ("item_no", models.PositiveIntegerField(default=1, verbose_name="#")),
                ("description", models.CharField(blank=True, max_length=200, verbose_name="項目")),
                ("material", models.CharField(blank=True, max_length=200, verbose_name="材料 / 規格")),
                ("code", models.CharField(blank=True, max_length=40, verbose_name="編號")),
                ("unit", models.CharField(blank=True, max_length=20, verbose_name="單位")),
                ("method", models.CharField(blank=True, max_length=50, verbose_name="計算方式")),
                ("basis", models.CharField(blank=True, max_length=200, verbose_name="計算依據")),
                ("qty_exact", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True, verbose_name="每 m² 用量（未進位）")),
                ("qty", models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True, verbose_name="每 m² 用量")),
                ("round_up", models.BooleanField(default=True, verbose_name="訂購數量進位至整數")),
                ("total_qty", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True, verbose_name="總用量")),
                ("order_qty", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True, verbose_name="訂購數量")),
                ("unit_price", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="單價")),
                ("supplier", models.CharField(blank=True, max_length=200, verbose_name="供應商")),
                ("price_date", models.DateField(blank=True, null=True, verbose_name="價錢日期")),
                ("cost", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True, verbose_name="每 m² 價錢")),
                ("total_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=24, null=True, verbose_name="總價")),
                ("note", models.CharField(blank=True, max_length=500, verbose_name="備註")),
                ("state", models.CharField(choices=[("original", "原配方"), ("edited", "手動調整"), ("added", "手動新增")], default="original", max_length=10, verbose_name="來源")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="quotes.quotationitem", verbose_name="報價項目")),
            ],
            options={
                "verbose_name": "報價明細",
                "verbose_name_plural": "報價明細",
                "ordering": ["position", "id"],
            },
        ),
    ]

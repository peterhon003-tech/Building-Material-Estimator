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
            name="CalcRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(db_index=True, verbose_name="時間")),
                ("brand", models.CharField(max_length=20, verbose_name="品牌")),
                ("system_type", models.PositiveSmallIntegerField(verbose_name="系統")),
                ("fire_rating_hours", models.PositiveSmallIntegerField(verbose_name="耐火時間")),
                ("system_label", models.CharField(max_length=200, verbose_name="系統")),
                ("report_no", models.CharField(blank=True, max_length=50, verbose_name="測試報告")),
                ("area", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="總面積")),
                ("view_mode", models.CharField(default="price", max_length=10, verbose_name="顯示")),
                ("include_prices", models.BooleanField(default=False, verbose_name="包括價錢")),
                ("total_per_sqm", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="每 m² 合計")),
                ("grand_total", models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True, verbose_name="合計")),
                ("language", models.CharField(blank=True, max_length=10, verbose_name="語言")),
                ("lines", models.JSONField(default=list, verbose_name="明細")),
                ("user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calc_records", to=settings.AUTH_USER_MODEL, verbose_name="用戶")),
            ],
            options={
                "verbose_name": "計價紀錄",
                "verbose_name_plural": "計價紀錄",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["user", "-created_at"], name="history_user_time")],
            },
        ),
    ]

"""材料修改紀錄和 Excel 匯入紀錄；並為現有材料補記一筆「系統建立」。"""
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

TRACKED = ["code", "name", "spec", "name_en", "spec_en", "category", "unit", "unit_en", "coverage", "active"]


def _s(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return str(value)


def backfill(apps, schema_editor):
    """現有材料沒有建立紀錄：用最早一個價錢的輸入時間和輸入人補記（沒有價錢就用現在）。"""
    Material = apps.get_model("estimator", "Material")
    MaterialPrice = apps.get_model("estimator", "MaterialPrice")
    MaterialLog = apps.get_model("estimator", "MaterialLog")
    for m in Material.objects.all():
        if MaterialLog.objects.filter(material=m).exists():
            continue
        first = MaterialPrice.objects.filter(material=m).order_by("created_at", "id").first()
        changes = [{"field": f, "old": "", "new": _s(getattr(m, f))} for f in TRACKED
                   if _s(getattr(m, f)) not in ("", None)]
        log = MaterialLog.objects.create(
            material=m, code=m.code, username=first.updated_by if first else "", source="system",
            action="created", changes=changes, note="補記：升級前已存在的材料")
        MaterialLog.objects.filter(pk=log.pk).update(created_at=first.created_at if first else timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0005_material_unit_en"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="上載時間")),
                ("confirmed_at", models.DateTimeField(blank=True, null=True, verbose_name="確認時間")),
                ("username", models.CharField(blank=True, max_length=150, verbose_name="帳戶名稱")),
                ("status", models.CharField(choices=[("preview", "預覽"), ("confirmed", "已確認")], default="preview", max_length=10, verbose_name="狀態")),
                ("filename", models.CharField(blank=True, max_length=255, verbose_name="檔案名稱")),
                ("file_data", models.BinaryField(blank=True, null=True, verbose_name="原檔")),
                ("file_size", models.PositiveIntegerField(default=0, verbose_name="檔案大小")),
                ("default_supplier", models.CharField(blank=True, max_length=100, verbose_name="預設供應商")),
                ("default_date", models.DateField(blank=True, null=True, verbose_name="預設生效日期")),
                ("counts", models.JSONField(blank=True, default=dict, verbose_name="數量")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="帳戶")),
            ],
            options={
                "verbose_name": "Excel 匯入紀錄",
                "verbose_name_plural": "Excel 匯入紀錄",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MaterialLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="時間")),
                ("code", models.CharField(max_length=40, verbose_name="編號")),
                ("username", models.CharField(blank=True, max_length=150, verbose_name="帳戶名稱")),
                ("source", models.CharField(choices=[("excel", "Excel 匯入"), ("admin", "系統管理"), ("form", "新增材料頁"), ("price_form", "更新價錢頁"), ("system", "系統建立")], max_length=12, verbose_name="來源")),
                ("action", models.CharField(choices=[("created", "新增"), ("changed", "修改"), ("deactivated", "停用"), ("reactivated", "重新啟用"), ("price", "價錢"), ("deleted", "刪除")], max_length=12, verbose_name="動作")),
                ("changes", models.JSONField(blank=True, default=list, verbose_name="改動")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="備註")),
                ("batch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="logs", to="estimator.importbatch", verbose_name="Excel 匯入紀錄")),
                ("material", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="logs", to="estimator.material", verbose_name="材料")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="帳戶")),
            ],
            options={
                "verbose_name": "材料修改紀錄",
                "verbose_name_plural": "材料修改紀錄",
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["material", "-created_at"], name="materiallog_material_time")],
            },
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]

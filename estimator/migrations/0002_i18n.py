import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """三語介面：材料和組件加入英文欄位；新增用戶設定（介面語言）。"""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("estimator", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="name_en",
            field=models.CharField(blank=True, default="", help_text="英文介面使用；留空就顯示中文名稱", max_length=100, verbose_name="英文名稱"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="material",
            name="spec_en",
            field=models.CharField(blank=True, default="", help_text="英文介面使用；留空就顯示中文規格", max_length=100, verbose_name="英文規格"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="systemcomponent",
            name="description_en",
            field=models.CharField(blank=True, default="", max_length=100, verbose_name="英文項目"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="systemcomponent",
            name="note_en",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="英文備註"),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("language", models.CharField(choices=[("zh-hant", "繁體中文"), ("zh-hans", "简体中文"), ("en", "English")], default="zh-hant", max_length=10, verbose_name="介面語言")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL, verbose_name="用戶")),
            ],
            options={
                "verbose_name": "用戶設定",
                "verbose_name_plural": "用戶設定",
            },
        ),
    ]

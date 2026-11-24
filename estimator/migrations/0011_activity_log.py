from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0010_security_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(db_index=True, verbose_name="時間")),
                ("username", models.CharField(blank=True, db_index=True, max_length=150, verbose_name="帳戶名稱")),
                ("ip", models.CharField(blank=True, db_index=True, max_length=45, verbose_name="IP 位址")),
                ("action", models.CharField(choices=[
                    ("login", "登入"), ("logout", "登出"), ("login_failed", "登入失敗"), ("calc", "計算"),
                    ("export", "匯出／下載"), ("view_price", "查看價錢"), ("price", "更新價錢"),
                    ("import", "Excel 匯入"), ("material", "新增材料"), ("quote", "報價"),
                    ("admin_add", "系統管理：新增"), ("admin_change", "系統管理：修改"),
                    ("admin_delete", "系統管理：刪除"), ("other", "其他操作")],
                    db_index=True, max_length=14, verbose_name="動作")),
                ("method", models.CharField(blank=True, max_length=10, verbose_name="方式")),
                ("path", models.CharField(blank=True, max_length=500, verbose_name="網址")),
                ("status", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="結果")),
                ("detail", models.CharField(blank=True, max_length=1000, verbose_name="內容")),
                ("user_agent", models.CharField(blank=True, max_length=300, verbose_name="瀏覽器")),
            ],
            options={
                "verbose_name": "使用紀錄",
                "verbose_name_plural": "使用紀錄",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

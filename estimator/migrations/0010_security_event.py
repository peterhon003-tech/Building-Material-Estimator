from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0009_login_failure"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(db_index=True, verbose_name="時間")),
                ("kind", models.CharField(choices=[("csrf", "CSRF 驗證失敗"), ("host", "不容許的網址"),
                                                   ("denied", "權限不足"), ("locked", "帳戶被鎖定"),
                                                   ("locked_try", "鎖定期間嘗試登入")],
                                          db_index=True, max_length=12, verbose_name="類別")),
                ("username", models.CharField(blank=True, db_index=True, max_length=150, verbose_name="帳戶名稱")),
                ("ip", models.CharField(blank=True, max_length=45, verbose_name="IP 位址")),
                ("method", models.CharField(blank=True, max_length=10, verbose_name="方式")),
                ("path", models.CharField(blank=True, max_length=500, verbose_name="網址")),
                ("origin", models.CharField(blank=True, max_length=300, verbose_name="Origin")),
                ("referer", models.CharField(blank=True, max_length=500, verbose_name="Referer")),
                ("user_agent", models.CharField(blank=True, max_length=300, verbose_name="瀏覽器")),
                ("detail", models.CharField(blank=True, max_length=500, verbose_name="原因")),
            ],
            options={
                "verbose_name": "安全事件紀錄",
                "verbose_name_plural": "安全事件紀錄",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

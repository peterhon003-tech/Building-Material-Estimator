from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estimator", "0008_component_formula"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginFailure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(db_index=True, max_length=150, verbose_name="帳戶名稱")),
                ("ip", models.CharField(blank=True, max_length=45, verbose_name="IP 位址")),
                ("created_at", models.DateTimeField(db_index=True, verbose_name="時間")),
            ],
            options={
                "verbose_name": "登入失敗紀錄",
                "verbose_name_plural": "登入失敗紀錄",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]

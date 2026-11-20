from django.db import migrations, models


class Migration(migrations.Migration):
    """系統組件加「自訂公式」：留空就用按計算方式的預設公式。"""

    dependencies = [
        ("estimator", "0007_partition"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemcomponent",
            name="formula",
            field=models.CharField(
                blank=True, max_length=200, verbose_name="自訂公式",
                help_text="留空 = 用預設公式。計出每 m² 用量（材料單位）。可用變數：層數、涵蓋量、間距、每平方米數量、"
                          "損耗（%）、牆高（m，只限 Partition），也可用英文 layers、coverage、spacing、qty_per_m2、wastage、height；"
                          "可用 + - * / ^ % ( )（* 乘、/ 除、^ 次方、% 百分比，例如 3^2 = 9、10% = 0.1；空格可有可無）、"
                          "最大(a, b)、最小(a, b)（或 max、min）"),
        ),
    ]

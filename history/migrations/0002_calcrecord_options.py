from django.db import migrations, models



class Migration(migrations.Migration):

    dependencies = [
        ("history", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="calcrecord",
            name="options",
            field=models.JSONField(blank=True, default=dict, verbose_name="計算選項"),
        ),
    ]

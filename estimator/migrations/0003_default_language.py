from django.conf import settings
from django.db import migrations, models


def set_existing_users_to_english(apps, schema_editor):
    """現有帳戶的預設語言全部設為英文。"""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserProfile = apps.get_model("estimator", "UserProfile")
    for user in User.objects.all():
        UserProfile.objects.update_or_create(user=user, defaults={"language": "en"})


class Migration(migrations.Migration):
    """語言改為「每個帳戶的預設語言」：每次登入都用它開始；右上角切換只維持到登出。"""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("estimator", "0002_i18n"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="language",
            field=models.CharField(
                choices=[("zh-hant", "繁體中文"), ("zh-hans", "简体中文"), ("en", "English")],
                default="en",
                help_text="每次登入時使用的語言。登入後在右上角切換，只維持到登出。",
                max_length=10, verbose_name="預設語言",
            ),
        ),
        migrations.RunPython(set_existing_users_to_english, migrations.RunPython.noop),
    ]

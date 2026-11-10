from django.apps import AppConfig

from estimator.i18n import tl


class QuotesConfig(AppConfig):
    """報價（附加功能）：把計價結果另存為報價，可以有多個項目、鎖定和建立新版本。

    移除方法見 README「報價」一節。
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "quotes"
    verbose_name = tl("報價")

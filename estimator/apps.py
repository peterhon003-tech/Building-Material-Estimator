from django.apps import AppConfig

from .i18n import tl


class EstimatorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "estimator"
    verbose_name = tl("防火板計價")

    def ready(self):
        from . import activity_log, login_guard, signals  # noqa: F401  語言；登入失敗次數；使用紀錄

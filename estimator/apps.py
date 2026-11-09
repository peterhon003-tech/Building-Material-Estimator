from django.apps import AppConfig

from .i18n import tl


class EstimatorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "estimator"
    verbose_name = tl("防火板計價")

    def ready(self):
        from . import signals  # noqa: F401  登入時重設語言

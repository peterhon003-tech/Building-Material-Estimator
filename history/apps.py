from django.apps import AppConfig

from estimator.i18n import tl


class HistoryConfig(AppConfig):
    """自動計價紀錄（附加功能）。

    - 開關：settings.FB_CALC_HISTORY_ENABLED
    - 保留日數：settings.FB_CALC_HISTORY_DAYS（預設 180）
    - 移除方法見 README「計價紀錄」一節
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "history"
    verbose_name = tl("計價紀錄")

    def ready(self):
        from . import receivers  # noqa: F401  接收 estimator 的 calculation_done

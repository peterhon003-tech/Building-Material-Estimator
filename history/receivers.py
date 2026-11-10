"""接收 estimator 的 calculation_done，記錄計價。記錄失敗不會影響計價頁。"""
import logging

from django.dispatch import receiver

from estimator.hooks import calculation_done

from . import recorder

log = logging.getLogger(__name__)


@receiver(calculation_done)
def on_calculation_done(sender, request, result, params, **kwargs):
    try:
        recorder.record(request.user, result, params)
    except Exception:  # 紀錄是附加功能，出錯也不可以令計價失敗
        log.exception("計價紀錄寫入失敗")

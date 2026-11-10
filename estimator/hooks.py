"""其他模組可以「掛上」的通知點，令 estimator 不需要知道有哪些附加功能。

calculation_done：計價頁每次算出結果後發出。
    參數：request、result（services.Result）、params（品牌、系統、耐火時間、面積、顯示模式）
目前由 history（計價紀錄）接收。移除 history 時，這裡不用改。
"""
from django.dispatch import Signal

calculation_done = Signal()

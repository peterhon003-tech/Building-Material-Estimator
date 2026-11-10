"""報價功能的開關：settings.FB_QUOTES_ENABLED（預設 True）。

設為 False：隱藏選單和「另存為報價 / 轉為報價」按鈕，報價網址顯示 404；數據保留，改回 True 即恢復。
後台「系統管理 → 報價」仍然可以查看。
"""
from functools import wraps

from django.conf import settings
from django.http import Http404


def enabled():
    return getattr(settings, "FB_QUOTES_ENABLED", True)


def require_enabled(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not enabled():
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper

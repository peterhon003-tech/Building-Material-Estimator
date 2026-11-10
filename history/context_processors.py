"""在頂部選單顯示「計價紀錄」。base.html 只用 fb_history_url，移除這個 app 後選單自動消失。"""
from django.urls import NoReverseMatch, reverse

from . import recorder


def history_nav(request):
    if not recorder.enabled() or not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    try:
        return {"fb_history_url": reverse("history_list")}
    except NoReverseMatch:
        return {}

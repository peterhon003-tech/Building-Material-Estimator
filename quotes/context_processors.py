"""在頂部選單顯示「報價」，並告訴計價頁和計價紀錄頁「另存為報價」要送到哪裡。

其他頁面只用 fb_quotes_url / fb_quote_save_url；移除這個 app 後按鈕和選單自動消失。
"""
from django.urls import NoReverseMatch, reverse

from .switch import enabled


def quotes_nav(request):
    user = getattr(request, "user", None)
    if not enabled() or not user or not user.is_authenticated:
        return {}
    try:
        return {"fb_quotes_url": reverse("quote_list"), "fb_quote_save_url": reverse("quote_save")}
    except NoReverseMatch:
        return {}

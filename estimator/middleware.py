"""決定每個請求用哪種介面語言。

次序：
1. 這次登入期間，用戶在右上角選的語言（存在 session，登出後消失）
2. 帳戶的「預設語言」（系統管理 → 用戶 → 用戶設定）
3. 系統預設語言 settings.FB_DEFAULT_LANGUAGE（英文）

每次登入都由帳戶的預設語言開始：登入時會清除 session 裡的臨時選擇（見 signals.py）。
刻意不跟瀏覽器的語言設定，避免同一個帳戶在不同電腦顯示不同語言。
"""
from django.conf import settings
from django.utils import translation

from .i18n import LANGUAGE_CODES

SESSION_KEY = "fb_language"


def default_language():
    lang = getattr(settings, "FB_DEFAULT_LANGUAGE", "en")
    return lang if lang in LANGUAGE_CODES else "en"


def user_language(request):
    lang = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if lang in LANGUAGE_CODES:
        return lang
    if request.user.is_authenticated:
        from .models import UserProfile
        lang = (UserProfile.objects.filter(user_id=request.user.pk)
                .values_list("language", flat=True).first())
        if lang in LANGUAGE_CODES:
            return lang
    return default_language()


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = user_language(request)
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", lang)
        return response

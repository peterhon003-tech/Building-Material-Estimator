"""按用戶帳戶設定的語言顯示介面。

次序：已登入用戶的帳戶設定 → 瀏覽器 cookie（登入頁用）→ 系統預設（繁體中文）。
刻意不跟瀏覽器的語言設定，避免同一個帳戶在不同電腦顯示不同語言。
"""
from django.conf import settings
from django.utils import translation

from .i18n import LANGUAGE_CODES


def user_language(request):
    if request.user.is_authenticated:
        from .models import UserProfile
        lang = (UserProfile.objects.filter(user_id=request.user.pk)
                .values_list("language", flat=True).first())
        if lang in LANGUAGE_CODES:
            return lang
    lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    if lang in LANGUAGE_CODES:
        return lang
    return settings.LANGUAGE_CODE


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

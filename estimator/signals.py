"""登入時清除上次在右上角臨時選擇的語言，令每次登入都由帳戶的預設語言開始。"""
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .middleware import SESSION_KEY


@receiver(user_logged_in)
def reset_language_on_login(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session.pop(SESSION_KEY, None)

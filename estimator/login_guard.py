"""限制登入失敗次數。

同一個帳戶名稱在 FB_LOGIN_LOCK_MINUTES 分鐘內輸入錯誤密碼 FB_LOGIN_MAX_FAILURES 次，
就暫時鎖定 FB_LOGIN_LOCK_MINUTES 分鐘（由最後一次錯誤起計）。鎖定期間即使密碼正確也不能登入。
登入成功會清除該帳戶的失敗紀錄。管理員可在「系統管理 → 登入失敗紀錄」刪除紀錄，立即解鎖。

注意：同事經 Windows port proxy 連入，網站見到的 IP 都是同一個，所以按帳戶名稱計算，不按 IP。
"""
import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.utils import timezone

KEEP_DAYS = 30


def max_failures():
    return getattr(settings, "FB_LOGIN_MAX_FAILURES", 5)


def lock_minutes():
    return getattr(settings, "FB_LOGIN_LOCK_MINUTES", 15)


def _name(username):
    return (username or "").strip().lower()[:150]


def remaining_minutes(username):
    """帳戶被鎖定時，傳回還要等幾分鐘（至少 1）；沒有鎖定傳回 0。"""
    from .models import LoginFailure
    name = _name(username)
    if not name:
        return 0
    now = timezone.now()
    window = timedelta(minutes=lock_minutes())
    times = list(LoginFailure.objects.filter(username=name, created_at__gte=now - window)
                 .order_by("-created_at").values_list("created_at", flat=True)[:max_failures()])
    if len(times) < max_failures():
        return 0
    seconds = (times[0] + window - now).total_seconds()
    return max(1, math.ceil(seconds / 60)) if seconds > 0 else 0


def client_ip(request):
    if request is None:
        return ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")     # Caddy 填上的原本 IP
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    return ip[:45]


@receiver(user_login_failed)
def record_failure(sender, credentials, request=None, **kwargs):
    from .models import LoginFailure
    name = _name(credentials.get("username"))
    if not name or remaining_minutes(name):        # 已鎖定：不再記錄，鎖定時間不會一直延長
        return
    now = timezone.now()
    LoginFailure.objects.create(username=name, ip=client_ip(request), created_at=now)
    LoginFailure.objects.filter(created_at__lt=now - timedelta(days=KEEP_DAYS)).delete()
    if remaining_minutes(name):                    # 這一次令帳戶開始鎖定
        from .security_log import record
        record("locked", request, username=name,
               detail=f"{max_failures()} failed log-ins within {lock_minutes()} minutes")


@receiver(user_logged_in)
def clear_failures(sender, request, user, **kwargs):
    from .models import LoginFailure
    LoginFailure.objects.filter(username=_name(user.get_username())).delete()

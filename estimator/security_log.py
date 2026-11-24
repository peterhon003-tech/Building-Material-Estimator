"""安全事件紀錄：把被拒絕的可疑操作寫入「系統管理 → 安全事件紀錄」。

記錄的事件：
  CSRF 驗證失敗      其他網頁送資料過來（Origin / Referer 不符合，或缺少表格暗碼）
  不容許的網址       用不在 DJANGO_ALLOWED_HOSTS 的地址打開網站（Bad Request 400）
  權限不足           已登入但沒有權限的頁面（403）
  帳戶被鎖定         登入失敗太多次，帳戶開始鎖定（見 login_guard.py）
  鎖定期間嘗試登入   鎖定期間再嘗試登入

同一來源 1 分鐘內重複的同一事件只記一次，以免被大量嘗試塞滿；保留 180 天。
記錄出錯時不會影響網站本身（只會少記一筆）。
"""
import logging
from datetime import timedelta

from django.core.exceptions import DisallowedHost
from django.utils import timezone
from django.views import csrf as csrf_views
from django.views import defaults

from .login_guard import client_ip

logger = logging.getLogger(__name__)
KEEP_DAYS = 180
REPEAT_SECONDS = 60


def _meta(request, key, size):
    return (request.META.get(key, "") if request is not None else "")[:size]


def record(kind, request=None, detail="", username=None):
    """寫入一筆安全事件。永遠不會令網站出錯。"""
    from .models import SecurityEvent
    try:
        if username is None:
            user = getattr(request, "user", None)
            username = user.get_username() if user is not None and user.is_authenticated else ""
        row = {
            "kind": kind,
            "username": (username or "")[:150],
            "ip": client_ip(request),
            "method": (request.method or "")[:10] if request is not None else "",
            "path": request.get_full_path()[:500] if request is not None else "",
            "origin": _meta(request, "HTTP_ORIGIN", 300),
            "referer": _meta(request, "HTTP_REFERER", 500),
            "user_agent": _meta(request, "HTTP_USER_AGENT", 300),
            "detail": (detail or "")[:500],
        }
        now = timezone.now()
        same = {k: row[k] for k in ("kind", "username", "ip", "path", "origin")}
        if SecurityEvent.objects.filter(created_at__gte=now - timedelta(seconds=REPEAT_SECONDS), **same).exists():
            return None
        event = SecurityEvent.objects.create(created_at=now, **row)
        SecurityEvent.objects.filter(created_at__lt=now - timedelta(days=KEEP_DAYS)).delete()
        return event
    except Exception:                      # noqa: BLE001  記錄失敗不可以令網站出錯
        logger.exception("Could not record security event %s", kind)
        return None


def csrf_failure(request, reason=""):
    """settings.CSRF_FAILURE_VIEW：先記錄，再顯示 Django 原本的 403 頁面。"""
    record("csrf", request, detail=reason)
    return csrf_views.csrf_failure(request, reason=reason)


def permission_denied(request, exception=None):
    """config/urls.py 的 handler403：先記錄，再顯示原本的 403 頁面。"""
    record("denied", request, detail=str(exception or "")[:500])
    return defaults.permission_denied(request, exception)


class HostCheckMiddleware:
    """放在 MIDDLEWARE 最前面：網址不在 ALLOWED_HOSTS → 記錄，然後照原本一樣回覆 400。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request.get_host()
        except DisallowedHost:
            record("host", request, detail=f"Host: {_meta(request, 'HTTP_HOST', 300)}", username="")
            raise
        return self.get_response(request)

"""使用紀錄：誰（帳戶、IP）在甚麼時間做了甚麼重要操作。見「系統管理 → 使用紀錄」。

記錄：登入、登出、登入失敗、計算、匯出／下載、查看價錢、更新價錢、Excel 匯入、新增材料、
報價（儲存、發出、取消、修訂、修改項目）、系統管理的新增／修改／刪除，及其他送出資料的操作。
一般瀏覽頁面不記錄。密碼、表格暗碼等敏感資料一律不記錄。保留 FB_ACTIVITY_KEEP_DAYS 天（預設 365）。
記錄出錯時不會影響網站本身（只會少記一筆）。
"""
import contextvars
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .login_guard import client_ip

logger = logging.getLogger(__name__)
_current_request = contextvars.ContextVar("fb_current_request", default=None)

# 網址名稱 → (動作, 記錄哪種方式：GET / POST / 兩者)
ROUTES = {
    "calculator_export": ("export", "GET"),
    "calculator_export_adjusted": ("export", "POST"),
    "price_list": ("view_price", "GET"),
    "price_history": ("view_price", "GET"),
    "price_add": ("price", "POST"),
    "price_import": ("import", "POST"),
    "price_import_confirm": ("import", "POST"),
    "price_import_template": ("export", "GET"),
    "material_add": ("material", "POST"),
    "import_batch_file": ("export", "GET"),
    "quote_save": ("quote", "POST"),
    "quote_issue": ("quote", "POST"),
    "quote_cancel": ("quote", "POST"),
    "quote_revise": ("quote", "POST"),
    "quote_item_edit": ("quote", "POST"),
    "quote_item_delete": ("quote", "POST"),
    "quote_item_move": ("quote", "POST"),
    "quote_export": ("export", "GET"),
}
SKIP = {"login", "logout", "set_language", "password_change", "password_change_done"}
CALC_KEYS = ["brand", "system_type", "hours", "height", "stress", "area", "view"]
SECRET_WORDS = ("password", "csrf", "token", "secret")


def keep_days():
    return getattr(settings, "FB_ACTIVITY_KEEP_DAYS", 365)


def _form_summary(request):
    """送出的資料（去掉密碼和暗碼），例如 system=3; area=12.5; file=prices.xlsx。"""
    parts = []
    for key in request.POST:
        if any(w in key.lower() for w in SECRET_WORDS):
            continue
        value = " / ".join(v[:60] for v in request.POST.getlist(key))
        parts.append(f"{key}={value}")
    parts += [f"file={f.name}" for f in request.FILES.values()]
    return "; ".join(parts)


def record(action, request=None, detail="", username=None, status=None):
    """寫入一筆使用紀錄。永遠不會令網站出錯。"""
    from .models import ActivityLog
    try:
        if username is None:
            user = getattr(request, "user", None)
            username = user.get_username() if user is not None and user.is_authenticated else ""
        meta = request.META if request is not None else {}
        now = timezone.now()
        row = ActivityLog.objects.create(
            created_at=now,
            username=(username or "")[:150],
            ip=client_ip(request),
            action=action,
            method=(getattr(request, "method", "") or "")[:10],
            path=request.get_full_path()[:500] if request is not None and hasattr(request, "path") else "",
            status=status,
            detail=(detail or "")[:1000],
            user_agent=meta.get("HTTP_USER_AGENT", "")[:300],
        )
        if row.pk % 200 == 0:                       # 間中清除過期紀錄
            ActivityLog.objects.filter(created_at__lt=now - timedelta(days=keep_days())).delete()
        return row
    except Exception:                               # noqa: BLE001  記錄失敗不可以令網站出錯
        logger.exception("Could not record activity %s", action)
        return None


class ActivityLogMiddleware:
    """放在 AuthenticationMiddleware 之後：重要操作完成後寫入使用紀錄。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            response = self.get_response(request)
        finally:
            _current_request.reset(token)
        try:
            self._log(request, response)
        except Exception:                           # noqa: BLE001
            logger.exception("Activity log failed")
        return response

    def _log(self, request, response):
        match = getattr(request, "resolver_match", None)
        if match is None or match.url_name in SKIP:
            return                                  # 404、登入登出（由訊號記錄）
        name, status = match.url_name, response.status_code
        if "admin" in match.namespaces:
            # 系統管理：一般由 LogEntry 記錄（見下面）；「刪除所選」等大量操作 Django 不經 LogEntry 訊號，
            # 所以已成功（轉頁）但未記錄的送出，在這裡補記。
            if request.method == "POST" and status in (301, 302, 303) and not getattr(request, "_fb_logged", False):
                if request.POST.get("action") == "delete_selected":
                    record("admin_delete", request, detail=_form_summary(request), status=status)
                else:
                    record("other", request, detail=_form_summary(request), status=status)
            return
        if name == "calculator":
            if request.method == "GET" and any(request.GET.get(k) for k in ("area", "system_type", "brand")):
                detail = "; ".join(f"{k}={request.GET[k][:60]}" for k in CALC_KEYS if request.GET.get(k))
                record("calc", request, detail=detail, status=status)
            return
        route = ROUTES.get(name)
        if route and route[1] == request.method:
            detail = _form_summary(request) if request.method == "POST" else request.GET.urlencode()[:500]
            if match.kwargs:
                detail = ", ".join(f"{k}={v}" for k, v in match.kwargs.items()) + (f"; {detail}" if detail else "")
            record(route[0], request, detail=detail, status=status)
        elif request.method not in ("GET", "HEAD", "OPTIONS"):
            record("other", request, detail=_form_summary(request), status=status)


# ---------- 登入、登出、登入失敗 ----------

@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    record("login", request, username=user.get_username())


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    record("logout", request, username=user.get_username() if user is not None else "")


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    record("login_failed", request, username=(credentials.get("username") or "")[:150])


# ---------- 系統管理的新增／修改／刪除（Django 本身的 LogEntry） ----------

@receiver(post_save, sender=LogEntry)
def _on_admin_change(sender, instance, created, **kwargs):
    if not created:
        return
    action = {ADDITION: "admin_add", CHANGE: "admin_change", DELETION: "admin_delete"}.get(instance.action_flag)
    if not action:
        return
    model = instance.content_type.name if instance.content_type_id else ""
    detail = f"{model}: {instance.object_repr}"
    message = instance.get_change_message()
    if message:
        detail += f" — {message}"
    request = _current_request.get()
    if request is not None:
        request._fb_logged = True
    record(action, request, detail=detail,
           username=instance.user.get_username() if instance.user_id else None)

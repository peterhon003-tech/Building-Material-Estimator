"""登入：檢查帳戶有沒有因為錯誤太多次而被鎖定（見 login_guard.py）。"""
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied

from . import login_guard
from .i18n import tr


class LockoutModelBackend(ModelBackend):
    """和 Django 原本的登入方法一樣，但帳戶鎖定期間一律拒絕（任何登入途徑都適用）。"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if login_guard.remaining_minutes(username):
            raise PermissionDenied
        return super().authenticate(request, username=username, password=password, **kwargs)


class _LockoutMixin:
    fb_locked = 0          # 鎖定時 = 還要等的分鐘數（登入頁用來顯示訊息）

    def clean(self):
        minutes = login_guard.remaining_minutes(self.data.get("username"))
        if minutes:
            self.fb_locked = minutes
            from .security_log import record
            record("locked_try", self.request, username=(self.data.get("username") or "").strip().lower(),
                   detail=f"locked, {minutes} minute(s) left")
            raise forms.ValidationError(
                tr("登入失敗次數太多，帳戶暫時鎖定。請 {m} 分鐘後再試，或請管理員解鎖。", m=minutes),
                code="locked")
        return super().clean()


class LoginForm(_LockoutMixin, AuthenticationForm):
    pass


class AdminLoginForm(_LockoutMixin, AdminAuthenticationForm):
    pass

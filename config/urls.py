from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from estimator.auth import AdminLoginForm, LoginForm
from estimator.i18n import tl

admin.site.site_header = tl("防火板計價系統 · 管理")
admin.site.site_title = tl("防火板計價系統")
admin.site.index_title = tl("系統管理")
admin.site.login_form = AdminLoginForm         # 登入失敗太多次 → 暫時鎖定

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(form_class=LoginForm), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("history/", include("history.urls")),     # 自動計價紀錄（可移除）
    path("quotes/", include("quotes.urls")),       # 報價（可移除）
    path("", include("estimator.urls")),
]

# 權限不足（403）→ 先寫入安全事件紀錄，再顯示原本的頁面
handler403 = "estimator.security_log.permission_denied"

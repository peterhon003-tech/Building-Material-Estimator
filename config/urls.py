from django.contrib import admin
from django.urls import include, path

from estimator.i18n import tl

admin.site.site_header = tl("防火板計價系統 · 管理")
admin.site.site_title = tl("防火板計價系統")
admin.site.index_title = tl("系統管理")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("history/", include("history.urls")),     # 自動計價紀錄（可移除）
    path("quotes/", include("quotes.urls")),       # 報價（可移除）
    path("", include("estimator.urls")),
]

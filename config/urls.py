from django.contrib import admin
from django.urls import include, path

from estimator.i18n import tl

admin.site.site_header = tl("防火板計價系統 · 管理")
admin.site.site_title = tl("防火板計價系統")
admin.site.index_title = tl("系統管理")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("estimator.urls")),
]

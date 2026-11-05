from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "防火板計價系統 · 管理"
admin.site.site_title = "防火板計價系統"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("estimator.urls")),
]

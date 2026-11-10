from django.urls import path

from . import views

urlpatterns = [
    path("", views.record_list, name="history_list"),
    path("<int:pk>/", views.record_detail, name="history_detail"),
]

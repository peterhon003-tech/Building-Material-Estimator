from django.urls import path

from . import views

urlpatterns = [
    path("", views.calculator, name="calculator"),
    path("export/", views.calculator_export, name="calculator_export"),
    path("prices/", views.price_list, name="price_list"),
    path("prices/<int:pk>/", views.price_history, name="price_history"),
    path("prices/<int:pk>/update/", views.price_add, name="price_add"),
    path("prices/import/", views.price_import, name="price_import"),
    path("prices/import/template/", views.price_import_template, name="price_import_template"),
    path("prices/import/confirm/", views.price_import_confirm, name="price_import_confirm"),
    path("materials/add/", views.material_add, name="material_add"),
]

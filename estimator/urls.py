from django.urls import path

from . import views

urlpatterns = [
    path("", views.calculator, name="calculator"),
    path("export/", views.calculator_export, name="calculator_export"),
    path("export/adjusted/", views.calculator_export_adjusted, name="calculator_export_adjusted"),
    path("prices/", views.price_list, name="price_list"),
    path("prices/<int:pk>/", views.price_history, name="price_history"),
    path("prices/<int:pk>/update/", views.price_add, name="price_add"),
    path("prices/import/", views.price_import, name="price_import"),
    path("prices/import/template/", views.price_import_template, name="price_import_template"),
    path("prices/import/confirm/", views.price_import_confirm, name="price_import_confirm"),
    path("materials/add/", views.material_add, name="material_add"),
    path("materials/logs/", views.material_logs, name="material_logs"),
    path("prices/import/history/", views.import_batches, name="import_batches"),
    path("prices/import/history/<int:pk>/", views.import_batch_detail, name="import_batch_detail"),
    path("prices/import/history/<int:pk>/file/", views.import_batch_file, name="import_batch_file"),
    path("language/", views.set_language, name="set_language"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("", views.quote_list, name="quote_list"),
    path("save/", views.save_to_quote, name="quote_save"),
    path("<int:pk>/", views.quote_detail, name="quote_detail"),
    path("<int:pk>/export/", views.quote_export, name="quote_export"),
    path("<int:pk>/issue/", views.quote_issue, name="quote_issue"),
    path("<int:pk>/cancel/", views.quote_cancel, name="quote_cancel"),
    path("<int:pk>/revise/", views.quote_revise, name="quote_revise"),
    path("<int:pk>/items/<int:item_pk>/", views.item_edit, name="quote_item_edit"),
    path("<int:pk>/items/<int:item_pk>/delete/", views.item_delete, name="quote_item_delete"),
    path("<int:pk>/items/<int:item_pk>/move/<str:direction>/", views.item_move, name="quote_item_move"),
]

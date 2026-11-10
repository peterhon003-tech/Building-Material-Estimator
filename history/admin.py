from django.contrib import admin

from .models import CalcRecord


@admin.register(CalcRecord)
class CalcRecordAdmin(admin.ModelAdmin):
    """唯讀：只供查看和刪除，不可新增或修改。"""
    list_display = ["created_at", "user", "system_label", "area", "grand_total"]
    list_filter = ["brand", "fire_rating_hours", "user"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

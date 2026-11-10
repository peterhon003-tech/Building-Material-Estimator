from django.contrib import admin

from .models import Quotation, QuotationItem, QuotationLine


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class QuotationItemInline(ReadOnlyInline):
    model = QuotationItem
    fields = ["position", "title", "system_label", "area", "include_prices", "total_per_sqm", "grand_total"]
    readonly_fields = fields


class QuotationLineInline(ReadOnlyInline):
    model = QuotationLine
    show_change_link = False
    fields = ["item_no", "description", "material", "qty", "unit", "unit_price", "cost", "total_cost", "state"]
    readonly_fields = fields


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    """後台只供查看和刪除；報價的修改請在網站的「報價」頁進行（有鎖定和版本管理）。"""
    list_display = ["number", "revision", "status", "customer_name", "created_by", "updated_at"]
    list_filter = ["status"]
    search_fields = ["number", "customer_name", "project"]
    inlines = [QuotationItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(QuotationItem)
class QuotationItemAdmin(admin.ModelAdmin):
    list_display = ["quotation", "position", "title", "system_label", "area"]
    inlines = [QuotationLineInline]

    def has_module_permission(self, request):
        return False                              # 不在後台首頁列出，只由報價頁連結進入

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

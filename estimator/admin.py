"""Django admin：只給系統管理員（開發者 / IT）設定系統配方和材料。

價錢紀錄在後台是唯讀的：不能新增、修改或刪除。
新增價錢一律經網站的「原料價錢」頁（逐項更新或 Excel 匯入），
確保每個價錢都有修改人和時間，舊價錢永遠保留。
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from . import audit
from .models import FireSystem, ImportBatch, Material, MaterialLog, MaterialPrice, SystemComponent, UserProfile

PRICE_FIELDS = ["unit_price", "supplier", "effective_date", "note", "updated_by", "created_at"]


class MaterialPriceInline(admin.TabularInline):
    model = MaterialPrice
    extra = 0
    fields = PRICE_FIELDS
    readonly_fields = PRICE_FIELDS
    can_delete = False
    verbose_name_plural = "價錢紀錄（唯讀，請在「原料價錢」頁更新）"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "spec", "name_en", "category", "unit", "unit_en", "coverage", "active"]
    list_filter = ["category", "active"]
    search_fields = ["code", "name", "spec", "name_en"]
    inlines = [MaterialPriceInline]

    # 材料修改紀錄：記錄在系統管理的新增、修改、刪除（改之前 → 改之後）
    def save_model(self, request, obj, form, change):
        before = audit.snapshot(Material.objects.get(pk=obj.pk)) if change and obj.pk else None
        super().save_model(request, obj, form, change)
        if before is None:
            audit.log_created(obj, request.user, MaterialLog.ADMIN)
        else:
            audit.log_changed(obj, before, request.user, MaterialLog.ADMIN)

    def delete_model(self, request, obj):
        audit.log(obj, request.user, MaterialLog.ADMIN, MaterialLog.DELETED)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            audit.log(obj, request.user, MaterialLog.ADMIN, MaterialLog.DELETED)
        super().delete_queryset(request, queryset)


@admin.register(MaterialLog)
class MaterialLogAdmin(admin.ModelAdmin):
    """唯讀：材料修改紀錄。"""
    list_display = ["created_at", "code", "action", "source", "username", "batch"]
    list_filter = ["source", "action"]
    search_fields = ["code", "username"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "material", "code", "user", "username", "source", "action", "changes",
                       "batch", "note"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    """唯讀：Excel 匯入紀錄（原檔可在網站「原料價錢 → 匯入紀錄」下載）。"""
    list_display = ["created_at", "username", "filename", "status", "confirmed_at"]
    list_filter = ["status"]
    exclude = ["file_data"]
    readonly_fields = ["created_at", "confirmed_at", "user", "username", "status", "filename", "file_size",
                       "default_supplier", "default_date", "counts"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MaterialPrice)
class MaterialPriceAdmin(admin.ModelAdmin):
    """唯讀：只可查看和搜尋。"""
    list_display = ["material", "unit_price", "supplier", "effective_date", "updated_by", "created_at"]
    list_filter = ["material__category", "supplier"]
    search_fields = ["material__name", "material__code"]
    date_hierarchy = "effective_date"
    readonly_fields = ["material"] + PRICE_FIELDS

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SystemComponentInline(admin.TabularInline):
    model = SystemComponent
    extra = 0
    autocomplete_fields = ["material"]


@admin.register(FireSystem)
class FireSystemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "frr_label", "report_no", "overall_thickness_mm", "active"]
    list_filter = ["brand", "system_type", "fire_rating_hours", "active"]
    inlines = [SystemComponentInline]


class UserProfileInline(admin.StackedInline):
    """在用戶頁可設定介面語言。"""
    model = UserProfile
    can_delete = False
    extra = 1
    max_num = 1


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]

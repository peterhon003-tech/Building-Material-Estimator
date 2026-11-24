"""Django admin：只給系統管理員（開發者 / IT）設定系統配方和材料。

價錢紀錄在後台是唯讀的：不能新增、修改或刪除。
新增價錢一律經網站的「原料價錢」頁（逐項更新或 Excel 匯入），
確保每個價錢都有修改人和時間，舊價錢永遠保留。
"""
from decimal import Decimal

from django.contrib import admin
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from . import audit
from .i18n import tl, tr
from .models import (ActivityLog, FireSystem, ImportBatch, LoginFailure, Material, SecurityEvent, MaterialLog, MaterialPrice, StudRule, SystemComponent,
                     UserProfile)

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


@admin.register(LoginFailure)
class LoginFailureAdmin(admin.ModelAdmin):
    """登入失敗紀錄：只可查看和刪除。刪除某帳戶的紀錄 = 立即解除鎖定。"""
    list_display = ["created_at", "username", "ip"]
    list_filter = ["created_at"]
    search_fields = ["username"]
    readonly_fields = ["created_at", "username", "ip"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """使用紀錄：只可查看；可匯出 CSV；只有超級用戶可以刪除。"""
    list_display = ["created_at", "username", "ip", "action", "short_detail", "status"]
    list_filter = ["action", "created_at", "username"]
    search_fields = ["username", "ip", "path", "detail"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "username", "ip", "action", "method", "path", "status", "detail",
                       "user_agent"]
    actions = ["export_csv"]

    @admin.display(description=tl("內容"))
    def short_detail(self, obj):
        return obj.detail if len(obj.detail) <= 80 else obj.detail[:80] + "…"

    @admin.action(description=tl("匯出所選紀錄（CSV）"))
    def export_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="activity_log.csv"'
        response.write("\ufeff")                        # Excel 正確顯示中文
        writer = csv.writer(response)
        writer.writerow([tr("時間"), tr("帳戶名稱"), tr("IP 位址"), tr("動作"), tr("方式"), tr("網址"),
                         tr("結果"), tr("內容"), tr("瀏覽器")])
        for row in queryset.order_by("created_at"):
            writer.writerow([timezone.localtime(row.created_at).strftime("%Y-%m-%d %H:%M:%S"), row.username,
                             row.ip, row.get_action_display(), row.method, row.path, row.status or "",
                             row.detail, row.user_agent])
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """安全事件紀錄：只可查看；只有超級用戶可以刪除。"""
    list_display = ["created_at", "kind", "username", "ip", "method", "path", "origin"]
    list_filter = ["kind", "created_at"]
    search_fields = ["username", "ip", "path", "origin", "referer", "detail"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "kind", "username", "ip", "method", "path", "origin", "referer",
                       "user_agent", "detail"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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
    fields = ["item_no", "description", "description_en", "material", "material_data", "method", "layers",
              "spacing_m", "fixed_qty_per_sqm", "wastage_pct", "default_formula_display", "formula",
              "formula_values", "qty_preview", "note", "note_en"]
    readonly_fields = ["material_data", "default_formula_display", "formula_values", "qty_preview"]

    def get_formset(self, request, obj=None, **kwargs):
        self._preview_cache = {}            # 同一系統只揀一次 stud
        return super().get_formset(request, obj, **kwargs)

    def _preview(self, obj):
        from . import services
        cache = getattr(self, "_preview_cache", None)
        key = ("row", obj.pk)
        if cache is not None and key in cache:
            return cache[key]
        result = services.formula_preview(obj, cache)
        if cache is not None:
            cache[key] = result
        return result

    @staticmethod
    def _num(d):
        return "—" if d is None else f"{Decimal(str(d)).normalize():f}"

    @admin.display(description=tl("材料數據"))
    def material_data(self, obj):
        """所選材料的計價單位和每單位涵蓋量（公式的「涵蓋量」）。"""
        if obj is None or not obj.pk:
            return "—"
        m = obj.material
        per = "m²" if m.category in ("BOARD", "ROCKWOOL") else "m"
        return tr("每{unit} {cov} {per}", unit=m.display_unit(), cov=self._num(m.coverage), per=per)

    @admin.display(description=tl("公式用到的數值"))
    def formula_values(self, obj):
        """實際公式用到的變數 = 數值（Partition 以第一個牆高試算）。"""
        if obj is None or not obj.pk:
            return "—"
        from . import services
        p = self._preview(obj)
        if not p["used"]:
            return "—"
        units = {"涵蓋量": "", "間距": " m", "損耗": "%", "牆高": " m"}
        parts = [f"{services.variable_label(k)} = {self._num(p['values'][k])}{units.get(k, '') if p['values'][k] is not None else ''}"
                 for k in p["used"]]
        return "，".join(parts)

    @admin.display(description=tl("試算每 m² 用量"))
    def qty_preview(self, obj):
        """用現時資料試算的每 m² 用量；Partition 註明試算用的牆高和 stud。"""
        if obj is None or not obj.pk:
            return "—"
        p = self._preview(obj)
        unit = p["material"].display_unit()
        text = tr("待定") if p["qty"] is None else f"{p['qty'].quantize(Decimal('0.0001'))} {unit}"
        if p["part"] is not None:
            text += tr("（牆高 {h} m、{s} N/mm²）", h=self._num(p["part"].height_m), s=p["part"].stress)
            if obj.method in ("STUD", "TRACK"):
                text += f" · {p['material'].code}"
        return text

    @admin.display(description=tl("預設公式"))
    def default_formula_display(self, obj):
        """按計算方式的預設公式（填了自訂公式就不會用）。"""
        if obj is None or not obj.pk:
            return "—"
        from . import services
        text = services.show_formula(obj.default_formula())
        return f"{text}（{tr('不使用')}）" if obj.formula.strip() else text


class StudRuleInline(admin.TabularInline):
    """Partition：測試報告的 stud 表（每種 stud 可做的最高牆高）。"""
    model = StudRule
    extra = 0


@admin.register(FireSystem)
class FireSystemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "frr_label", "report_no", "overall_thickness_mm", "active"]
    list_filter = ["brand", "system_type", "fire_rating_hours", "active"]
    inlines = [SystemComponentInline, StudRuleInline]


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

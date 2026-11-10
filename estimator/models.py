from datetime import date

from django.conf import settings
from django.db import models

from . import calc
from .i18n import EN_CODE, LANGUAGES, current_language, localized, tl, tr


class Material(models.Model):
    # (代碼, 中文名稱)；中文名稱同時是翻譯的 key（Excel 匯入時辨認任何語言的類別）
    CATEGORIES = [
        ("BOARD", "板"),
        ("CHANNEL", "槽鐵"),
        ("ANGLE", "角鐵"),
        ("ROCKWOOL", "岩棉"),
        ("FIXING", "螺絲及螺栓"),
        ("SEALANT", "膠"),
        ("LABOUR", "人工"),
    ]
    CATEGORY_CHOICES = [(code, tl(zh)) for code, zh in CATEGORIES]

    code = models.CharField(tl("編號"), max_length=40, unique=True)
    name = models.CharField(tl("名稱"), max_length=100)
    spec = models.CharField(tl("規格"), max_length=100, blank=True)
    name_en = models.CharField(tl("英文名稱"), max_length=100, blank=True,
                               help_text=tl("英文介面使用；留空就顯示中文名稱"))
    spec_en = models.CharField(tl("英文規格"), max_length=100, blank=True,
                               help_text=tl("英文介面使用；留空就顯示中文規格"))
    category = models.CharField(tl("類別"), max_length=20, choices=CATEGORY_CHOICES)
    unit = models.CharField(tl("計價單位"), max_length=20, help_text=tl("例如：張、支、件、粒、m²"))
    unit_en = models.CharField(tl("英文計價單位"), max_length=20, blank=True,
                               help_text=tl("英文介面使用，例如 sheet、pc、nos；留空就按系統翻譯顯示"))
    coverage = models.DecimalField(
        tl("每單位涵蓋量"), max_digits=10, decimal_places=4, default=1,
        help_text=tl("板／岩棉填每單位面積 (m²)，鐵料填每支長度 (m)，其他填 1"),
    )
    active = models.BooleanField(tl("使用中"), default=True)

    class Meta:
        ordering = ["category", "code"]
        verbose_name = tl("材料")
        verbose_name_plural = tl("材料")

    def __str__(self):
        return self.display_name()

    def display_name(self, lang=None):
        """按語言顯示的「名稱 規格」：英文用英文欄（未填用中文），簡體自動轉換。"""
        name = localized(self.name, self.name_en, lang)
        spec = localized(self.spec, self.spec_en, lang)
        return f"{name} {spec}".strip()

    def display_unit(self, lang=None):
        """英文介面優先用英文計價單位；未填就按翻譯表（沒有翻譯就顯示中文）。"""
        lang = lang or current_language()
        if lang == EN_CODE and self.unit_en:
            return self.unit_en
        return tr(self.unit, lang)

    def local_name(self):
        return localized(self.name, self.name_en)

    def local_spec(self):
        return localized(self.spec, self.spec_en)

    def current_price(self, on=None):
        """在指定日期（預設今日）已生效的最新價錢。"""
        on = on or date.today()
        return (
            self.prices.filter(effective_date__lte=on)
            .order_by("-effective_date", "-created_at")
            .first()
        )


class MaterialPrice(models.Model):
    """價錢只會新增，不會覆蓋，保留完整價錢紀錄。"""

    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name="prices", verbose_name=tl("材料")
    )
    supplier = models.CharField(tl("供應商"), max_length=100, blank=True)
    unit_price = models.DecimalField(tl("單價 (HK$)"), max_digits=12, decimal_places=2)
    effective_date = models.DateField(tl("生效日期"))
    note = models.CharField(tl("備註"), max_length=200, blank=True)
    updated_by = models.CharField(tl("修改人"), max_length=150, blank=True)
    created_at = models.DateTimeField(tl("建立時間"), auto_now_add=True)

    class Meta:
        ordering = ["-effective_date", "-created_at"]
        verbose_name = tl("材料價錢")
        verbose_name_plural = tl("材料價錢")

    def __str__(self):
        return f"{self.material} ${self.unit_price} ({self.effective_date})"


class FireSystem(models.Model):
    BRAND_CHOICES = [("PROMAT", "Promat"), ("DURASTEEL", "Durasteel")]
    # 編號不變（舊的 1 = Enclosure 現在是 Enclosure for Ceiling），下拉選單按這個次序
    TYPE_CHOICES = [(1, "Enclosure for Ceiling"), (3, "Enclosure for Gas Pipe"), (2, "Partition")]
    HOURS_CHOICES = [(1, tl("1 小時")), (2, tl("2 小時")), (4, tl("4 小時"))]

    brand = models.CharField(tl("品牌"), max_length=20, choices=BRAND_CHOICES)
    system_type = models.PositiveSmallIntegerField(tl("系統"), choices=TYPE_CHOICES)
    fire_rating_hours = models.PositiveSmallIntegerField(tl("耐火時間"), choices=HOURS_CHOICES)
    frr_label = models.CharField("F.R.R.", max_length=30, blank=True)
    report_no = models.CharField(tl("測試報告編號"), max_length=50, blank=True)
    drawing_ref = models.CharField(tl("圖則"), max_length=200, blank=True)
    overall_thickness_mm = models.PositiveIntegerField(tl("系統總厚度 (mm)"), null=True, blank=True)
    active = models.BooleanField(tl("啟用"), default=True)
    notes = models.TextField(tl("備註"), blank=True)

    class Meta:
        ordering = ["brand", "system_type", "fire_rating_hours"]
        verbose_name = tl("系統")
        verbose_name_plural = tl("系統")
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "system_type", "fire_rating_hours"], name="unique_fire_system"
            )
        ]

    def __str__(self):
        return f"{self.get_brand_display()} · {self.get_system_type_display()} · {self.get_fire_rating_hours_display()}"


class SystemComponent(models.Model):
    METHOD_CHOICES = [
        (calc.AREA, tl("按面積")),
        (calc.SPACING, tl("按間距")),
        (calc.FIXED, tl("固定數量")),
    ]

    system = models.ForeignKey(
        FireSystem, on_delete=models.CASCADE, related_name="components", verbose_name=tl("系統")
    )
    item_no = models.PositiveSmallIntegerField(tl("圖例編號"))
    description = models.CharField(tl("項目"), max_length=100)
    description_en = models.CharField(tl("英文項目"), max_length=100, blank=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, verbose_name=tl("材料"))
    method = models.CharField(tl("計算方式"), max_length=10, choices=METHOD_CHOICES)
    layers = models.PositiveSmallIntegerField(tl("層數"), default=1)
    spacing_m = models.DecimalField(
        tl("間距 c/c (m)"), max_digits=6, decimal_places=3, null=True, blank=True
    )
    fixed_qty_per_sqm = models.DecimalField(
        tl("每 m² 固定數量"), max_digits=10, decimal_places=4, null=True, blank=True,
        help_text=tl("留空 = 待定（不計入總價）"),
    )
    wastage_pct = models.DecimalField(tl("損耗 %"), max_digits=5, decimal_places=2, default=0)
    note = models.CharField(tl("備註"), max_length=200, blank=True)
    note_en = models.CharField(tl("英文備註"), max_length=200, blank=True)

    class Meta:
        ordering = ["item_no", "id"]
        verbose_name = tl("系統組件")
        verbose_name_plural = tl("系統組件")

    def __str__(self):
        return f"{self.item_no}. {self.display_description()}"

    def display_description(self, lang=None):
        return localized(self.description, self.description_en, lang)

    def display_note(self, lang=None):
        return localized(self.note, self.note_en, lang)


class UserProfile(models.Model):
    """每個用戶的設定。預設語言 = 每次登入時使用的語言。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
        verbose_name=tl("用戶"),
    )
    language = models.CharField(
        tl("預設語言"), max_length=10, choices=LANGUAGES, default=EN_CODE,
        help_text=tl("每次登入時使用的語言。登入後在右上角切換，只維持到登出。"),
    )

    class Meta:
        verbose_name = tl("用戶設定")
        verbose_name_plural = tl("用戶設定")

    def __str__(self):
        return f"{self.user} · {self.get_language_display()}"

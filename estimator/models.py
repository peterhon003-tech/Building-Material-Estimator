from datetime import date

from django.db import models

from . import calc


class Material(models.Model):
    CATEGORY_CHOICES = [
        ("BOARD", "板"),
        ("CHANNEL", "槽鐵"),
        ("ANGLE", "角鐵"),
        ("ROCKWOOL", "岩棉"),
        ("FIXING", "螺絲及螺栓"),
        ("SEALANT", "膠"),
        ("LABOUR", "人工"),
    ]

    code = models.CharField("編號", max_length=40, unique=True)
    name = models.CharField("名稱", max_length=100)
    spec = models.CharField("規格", max_length=100, blank=True)
    category = models.CharField("類別", max_length=20, choices=CATEGORY_CHOICES)
    unit = models.CharField("計價單位", max_length=20, help_text="例如：張、支、件、粒、m²")
    coverage = models.DecimalField(
        "每單位涵蓋量", max_digits=10, decimal_places=4, default=1,
        help_text="板／岩棉填每單位面積 (m²)，鐵料填每支長度 (m)，其他填 1",
    )
    active = models.BooleanField("使用中", default=True)

    class Meta:
        ordering = ["category", "code"]
        verbose_name = "材料"
        verbose_name_plural = "材料"

    def __str__(self):
        return f"{self.name} {self.spec}".strip()

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
        Material, on_delete=models.PROTECT, related_name="prices", verbose_name="材料"
    )
    supplier = models.CharField("供應商", max_length=100, blank=True)
    unit_price = models.DecimalField("單價 (HK$)", max_digits=12, decimal_places=2)
    effective_date = models.DateField("生效日期")
    note = models.CharField("備註", max_length=200, blank=True)
    updated_by = models.CharField("修改人", max_length=150, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-effective_date", "-created_at"]
        verbose_name = "材料價錢"
        verbose_name_plural = "材料價錢"

    def __str__(self):
        return f"{self.material} ${self.unit_price} ({self.effective_date})"


class FireSystem(models.Model):
    BRAND_CHOICES = [("PROMAT", "Promat"), ("DURASTEEL", "Durasteel")]
    TYPE_CHOICES = [(1, "Enclosure"), (2, "Partition")]
    HOURS_CHOICES = [(1, "1 小時"), (2, "2 小時"), (4, "4 小時")]

    brand = models.CharField("品牌", max_length=20, choices=BRAND_CHOICES)
    system_type = models.PositiveSmallIntegerField("系統", choices=TYPE_CHOICES)
    fire_rating_hours = models.PositiveSmallIntegerField("耐火時間", choices=HOURS_CHOICES)
    frr_label = models.CharField("F.R.R.", max_length=30, blank=True)
    report_no = models.CharField("測試報告編號", max_length=50, blank=True)
    drawing_ref = models.CharField("圖則", max_length=200, blank=True)
    overall_thickness_mm = models.PositiveIntegerField("系統總厚度 (mm)", null=True, blank=True)
    active = models.BooleanField("啟用", default=True)
    notes = models.TextField("備註", blank=True)

    class Meta:
        ordering = ["brand", "system_type", "fire_rating_hours"]
        verbose_name = "系統"
        verbose_name_plural = "系統"
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "system_type", "fire_rating_hours"], name="unique_fire_system"
            )
        ]

    def __str__(self):
        return f"{self.get_brand_display()} · {self.get_system_type_display()} · {self.get_fire_rating_hours_display()}"


class SystemComponent(models.Model):
    METHOD_CHOICES = [
        (calc.AREA, "按面積"),
        (calc.SPACING, "按間距"),
        (calc.FIXED, "固定數量"),
    ]

    system = models.ForeignKey(
        FireSystem, on_delete=models.CASCADE, related_name="components", verbose_name="系統"
    )
    item_no = models.PositiveSmallIntegerField("圖例編號")
    description = models.CharField("項目", max_length=100)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, verbose_name="材料")
    method = models.CharField("計算方式", max_length=10, choices=METHOD_CHOICES)
    layers = models.PositiveSmallIntegerField("層數", default=1)
    spacing_m = models.DecimalField(
        "間距 c/c (m)", max_digits=6, decimal_places=3, null=True, blank=True
    )
    fixed_qty_per_sqm = models.DecimalField(
        "每 m² 固定數量", max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="留空 = 待定（不計入總價）",
    )
    wastage_pct = models.DecimalField("損耗 %", max_digits=5, decimal_places=2, default=0)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        ordering = ["item_no", "id"]
        verbose_name = "系統組件"
        verbose_name_plural = "系統組件"

    def __str__(self):
        return f"{self.item_no}. {self.description}"

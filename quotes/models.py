"""報價：計價結果的快照。

- 每張報價有編號（Q-2026-0001）和版本（A、B、C…）。
- 報價的每一行都是「複製」當時的名稱、規格、用量和價錢，之後材料價錢或配方改動不會影響已存的報價。
- 草稿可以修改；發出後鎖定，要修改就建立新版本（舊版本保留）。
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from estimator import calc
from estimator.i18n import tl


class Quotation(models.Model):
    DRAFT, ISSUED, CANCELLED = "draft", "issued", "cancelled"
    STATUS_CHOICES = [(DRAFT, tl("草稿")), (ISSUED, tl("已發出")), (CANCELLED, tl("已取消"))]

    number = models.CharField(tl("報價編號"), max_length=20)
    revision = models.CharField(tl("版本"), max_length=4, default="A")
    status = models.CharField(tl("狀態"), max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    customer_name = models.CharField(tl("客戶名稱"), max_length=200, blank=True)
    contact = models.CharField(tl("聯絡人及電話"), max_length=200, blank=True)
    project = models.TextField(tl("工程名稱及地址"), blank=True)
    remarks = models.TextField(tl("備註"), blank=True)
    revised_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name=tl("由此版本修改"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name="quotations", verbose_name=tl("建立人"))
    created_at = models.DateTimeField(tl("建立時間"), auto_now_add=True)
    updated_by = models.CharField(tl("最後修改人"), max_length=150, blank=True)
    updated_at = models.DateTimeField(tl("最後修改時間"), auto_now=True)
    issued_at = models.DateTimeField(tl("發出時間"), null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = tl("報價")
        verbose_name_plural = tl("報價")
        constraints = [models.UniqueConstraint(fields=["number", "revision"], name="quote_number_revision")]

    def __str__(self):
        return self.label

    @property
    def label(self):
        return f"{self.number} Rev {self.revision}"

    @property
    def is_draft(self):
        return self.status == self.DRAFT

    def can_edit(self, user):
        """只有草稿可以修改；建立人可以改自己的，系統管理員可以改所有人的。"""
        return self.is_draft and self.can_manage(user)

    def can_manage(self, user):
        """可以發出、取消、建立新版本的人：建立人或系統管理員。"""
        return user.is_authenticated and (user.is_staff or user.is_superuser
                                          or (self.created_by_id is not None and self.created_by_id == user.pk))

    def totals(self):
        """(合計, 是否有項目未計入)。只計有價錢和總面積的項目。"""
        total = Decimal("0")
        partial = False
        for item in self.items.all():
            if item.include_prices and item.grand_total is not None:
                total += item.grand_total
            else:
                partial = True
        return calc.money(total), partial


class QuotationItem(models.Model):
    """報價裡的一個項目：一個防火系統 + 總面積（例如「1/F 走廊 Enclosure 2hr 120 m²」）。"""

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items",
                                  verbose_name=tl("報價"))
    position = models.PositiveIntegerField(tl("次序"), default=1)
    title = models.CharField(tl("位置 / 說明"), max_length=200, blank=True)
    brand = models.CharField(tl("品牌"), max_length=20)
    system_type = models.PositiveSmallIntegerField(tl("系統"))
    fire_rating_hours = models.PositiveSmallIntegerField(tl("耐火時間"))
    system_label = models.CharField(tl("系統"), max_length=200)
    frr_label = models.CharField("F.R.R.", max_length=50, blank=True)
    report_no = models.CharField(tl("測試報告"), max_length=50, blank=True)
    area = models.DecimalField(tl("總面積"), max_digits=12, decimal_places=2, null=True, blank=True)
    include_prices = models.BooleanField(tl("包括價錢"), default=False)
    price_date = models.DateField(tl("價錢日期"), null=True, blank=True)
    adjusted = models.BooleanField(tl("已手動調整"), default=False)
    total_per_sqm = models.DecimalField(tl("每 m² 合計"), max_digits=20, decimal_places=2, null=True, blank=True)
    grand_total = models.DecimalField(tl("合計"), max_digits=24, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = tl("報價項目")
        verbose_name_plural = tl("報價項目")

    def __str__(self):
        return f"{self.position}. {self.title or self.system_label}"

    def recalc_totals(self):
        """按各行重新計合計（不讀取現時價錢）。"""
        if not self.include_prices:
            self.total_per_sqm = self.grand_total = None
            return
        lines = list(self.lines.all())
        self.total_per_sqm = calc.money(sum((l.cost for l in lines if l.cost is not None), Decimal("0")))
        self.grand_total = (calc.money(sum((l.total_cost for l in lines if l.total_cost is not None), Decimal("0")))
                            if self.area is not None else None)

    @property
    def pending_lines(self):
        return [l for l in self.lines.all() if l.qty is None or (self.include_prices and l.cost is None)]


class QuotationLine(models.Model):
    ORIGINAL, EDITED, ADDED = "original", "edited", "added"
    STATE_CHOICES = [(ORIGINAL, tl("原配方")), (EDITED, tl("手動調整")), (ADDED, tl("手動新增"))]

    item = models.ForeignKey(QuotationItem, on_delete=models.CASCADE, related_name="lines",
                             verbose_name=tl("報價項目"))
    position = models.PositiveIntegerField(tl("次序"), default=1)
    item_no = models.PositiveIntegerField("#", default=1)
    description = models.CharField(tl("項目"), max_length=200, blank=True)
    material = models.CharField(tl("材料 / 規格"), max_length=200, blank=True)
    code = models.CharField(tl("編號"), max_length=40, blank=True)
    unit = models.CharField(tl("單位"), max_length=20, blank=True)
    method = models.CharField(tl("計算方式"), max_length=50, blank=True)
    basis = models.CharField(tl("計算依據"), max_length=200, blank=True)
    qty_exact = models.DecimalField(tl("每 m² 用量（未進位）"), max_digits=24, decimal_places=12,
                                    null=True, blank=True)
    qty = models.DecimalField(tl("每 m² 用量"), max_digits=14, decimal_places=4, null=True, blank=True)
    round_up = models.BooleanField(tl("訂購數量進位至整數"), default=True)
    total_qty = models.DecimalField(tl("總用量"), max_digits=20, decimal_places=4, null=True, blank=True)
    order_qty = models.DecimalField(tl("訂購數量"), max_digits=20, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(tl("單價"), max_digits=14, decimal_places=2, null=True, blank=True)
    supplier = models.CharField(tl("供應商"), max_length=200, blank=True)
    price_date = models.DateField(tl("價錢日期"), null=True, blank=True)
    cost = models.DecimalField(tl("每 m² 價錢"), max_digits=20, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(tl("總價"), max_digits=24, decimal_places=2, null=True, blank=True)
    note = models.CharField(tl("備註"), max_length=500, blank=True)
    state = models.CharField(tl("來源"), max_length=10, choices=STATE_CHOICES, default=ORIGINAL)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = tl("報價明細")
        verbose_name_plural = tl("報價明細")

    def __str__(self):
        return f"{self.item_no}. {self.description}"

    @property
    def pending(self):
        return self.cost is None

    @property
    def qty_pending(self):
        return self.qty is None

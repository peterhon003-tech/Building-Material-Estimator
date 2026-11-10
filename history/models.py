from django.conf import settings
from django.db import models

from estimator.i18n import tl


class CalcRecord(models.Model):
    """一次計價的快照：當時的輸入、每項明細和合計。只供查看，超過保留日數自動刪除。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             related_name="calc_records", verbose_name=tl("用戶"))
    created_at = models.DateTimeField(tl("時間"), db_index=True)
    brand = models.CharField(tl("品牌"), max_length=20)
    system_type = models.PositiveSmallIntegerField(tl("系統"))
    fire_rating_hours = models.PositiveSmallIntegerField(tl("耐火時間"))
    system_label = models.CharField(tl("系統"), max_length=200)
    report_no = models.CharField(tl("測試報告"), max_length=50, blank=True)
    area = models.DecimalField(tl("總面積"), max_digits=12, decimal_places=2, null=True, blank=True)
    view_mode = models.CharField(tl("顯示"), max_length=10, default="price")
    include_prices = models.BooleanField(tl("包括價錢"), default=False)
    total_per_sqm = models.DecimalField(tl("每 m² 合計"), max_digits=14, decimal_places=2, null=True, blank=True)
    grand_total = models.DecimalField(tl("合計"), max_digits=16, decimal_places=2, null=True, blank=True)
    language = models.CharField(tl("語言"), max_length=10, blank=True)
    lines = models.JSONField(tl("明細"), default=list)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = tl("計價紀錄")
        verbose_name_plural = tl("計價紀錄")
        indexes = [models.Index(fields=["user", "-created_at"], name="history_user_time")]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} · {self.system_label}"

    def calculator_query(self):
        """重新計算用的網址參數。"""
        from urllib.parse import urlencode
        q = {"brand": self.brand, "system_type": self.system_type, "hours": self.fire_rating_hours}
        if self.area is not None:
            q["area"] = f"{self.area}"
        if self.view_mode == "material":
            q["view"] = "material"
        return urlencode(q)

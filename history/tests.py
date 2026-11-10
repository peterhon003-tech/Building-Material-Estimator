from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CalcRecord

PARAMS = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}


# 測試假設功能已開啟；settings.py 關閉了也照樣測試（停用時的行為另有測試）
@override_settings(FB_DEFAULT_LANGUAGE="zh-hant", FB_CALC_HISTORY_ENABLED=True)
class HistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.est = User.objects.create_user("h_est", password="pw-12345-x")
        cls.est.groups.add(Group.objects.get(name="估價員"))
        cls.plain = User.objects.create_user("h_plain", password="pw-12345-x")
        cls.staff = User.objects.create_user("h_staff", password="pw-12345-x", is_staff=True)
        cls.staff.groups.add(Group.objects.get(name="估價員"))

    def calc(self, user, **extra):
        self.client.force_login(user)
        return self.client.get(reverse("calculator"), {**PARAMS, **extra})

    # ---------- 自動記錄 ----------
    def test_calculation_is_recorded_with_snapshot(self):
        self.calc(self.est)
        rec = CalcRecord.objects.get(user=self.est)
        self.assertEqual(rec.fire_rating_hours, 2)
        self.assertEqual(rec.area, Decimal("100.00"))
        self.assertTrue(rec.include_prices)
        self.assertEqual(rec.total_per_sqm, Decimal("174.71"))
        self.assertEqual(rec.grand_total, Decimal("17471.97"))
        board = next(l for l in rec.lines if l["item_no"] == 1)
        self.assertEqual(board["unit_price"], "350.00")
        self.assertEqual(board["order_qty"], "37")

    def test_same_conditions_within_10_minutes_recorded_once(self):
        self.calc(self.est)
        self.calc(self.est)
        self.calc(self.est, hours="4")
        self.assertEqual(CalcRecord.objects.filter(user=self.est).count(), 2)

    def test_material_only_user_record_has_no_prices(self):
        self.calc(self.plain)
        rec = CalcRecord.objects.get(user=self.plain)
        self.assertFalse(rec.include_prices)
        self.assertIsNone(rec.total_per_sqm)
        for line in rec.lines:
            self.assertFalse({"unit_price", "cost", "total_cost"} & set(line))

    def test_no_record_without_result(self):
        self.client.force_login(self.est)
        self.client.get(reverse("calculator"))
        self.client.get(reverse("calculator"), {"brand": "DURASTEEL", "system_type": "1", "hours": "2"})
        self.assertFalse(CalcRecord.objects.exists())

    def test_snapshot_not_changed_by_later_price_update(self):
        from estimator.models import Material, MaterialPrice
        self.calc(self.est)
        m = Material.objects.get(code="PTH-09")
        MaterialPrice.objects.create(material=m, unit_price=Decimal("999"), effective_date=timezone.localdate())
        rec = CalcRecord.objects.get(user=self.est)
        self.assertEqual(next(l for l in rec.lines if l["item_no"] == 1)["unit_price"], "350.00")

    # ---------- 180 日清理 ----------
    def test_old_records_purged(self):
        self.calc(self.est)
        old = CalcRecord.objects.get()
        old.created_at = timezone.now() - timedelta(days=181)
        old.save()
        self.calc(self.est, hours="4")                     # 新紀錄會順便清理
        self.assertFalse(CalcRecord.objects.filter(pk=old.pk).exists())
        self.assertEqual(CalcRecord.objects.count(), 1)

    def test_purge_command_keeps_recent(self):
        self.calc(self.est)
        r = CalcRecord.objects.get()
        r.created_at = timezone.now() - timedelta(days=179)
        r.save()
        call_command("purge_history", verbosity=0)
        self.assertTrue(CalcRecord.objects.filter(pk=r.pk).exists())

    @override_settings(FB_CALC_HISTORY_DAYS=30)
    def test_keep_days_setting(self):
        self.calc(self.est)
        r = CalcRecord.objects.get()
        r.created_at = timezone.now() - timedelta(days=31)
        r.save()
        call_command("purge_history", verbosity=0)
        self.assertFalse(CalcRecord.objects.exists())

    # ---------- 查看權限 ----------
    def test_users_see_only_their_own(self):
        self.calc(self.est)
        self.calc(self.plain)
        other = CalcRecord.objects.get(user=self.plain)
        self.client.force_login(self.est)
        resp = self.client.get(reverse("history_list"))
        self.assertEqual(len(resp.context["page"]), 1)
        self.assertEqual(self.client.get(reverse("history_detail", args=[other.pk])).status_code, 404)

    def test_staff_sees_everyone(self):
        self.calc(self.est)
        self.calc(self.plain)
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("history_list"))
        self.assertEqual(len(resp.context["page"]), 2)
        resp = self.client.get(reverse("history_list"), {"user": self.plain.pk})
        self.assertEqual(len(resp.context["page"]), 1)

    def test_detail_hides_prices_without_permission(self):
        self.calc(self.plain)
        rec = CalcRecord.objects.get(user=self.plain)
        resp = self.client.get(reverse("history_detail", args=[rec.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["show_prices"])

    def test_detail_with_prices(self):
        self.calc(self.est)
        rec = CalcRecord.objects.get(user=self.est)
        resp = self.client.get(reverse("history_detail", args=[rec.pk]))
        self.assertTrue(resp.context["show_prices"])
        self.assertContains(resp, "17471.97")

    def test_list_requires_login(self):
        self.assertEqual(self.client.get(reverse("history_list")).status_code, 302)

    def test_nav_link(self):
        resp = self.calc(self.est)
        self.assertEqual(resp.context["fb_history_url"], reverse("history_list"))

    # ---------- 開關 ----------
    @override_settings(FB_CALC_HISTORY_ENABLED=False)
    def test_disabled(self):
        resp = self.calc(self.est)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("fb_history_url", resp.context)
        self.assertFalse(CalcRecord.objects.exists())
        self.assertEqual(self.client.get(reverse("history_list")).status_code, 404)

    def test_recording_error_does_not_break_calculator(self):
        with mock.patch("history.recorder.record", side_effect=RuntimeError("boom")):
            with self.assertLogs("history.receivers", level="ERROR"):
                resp = self.calc(self.est)
        self.assertEqual(resp.status_code, 200)

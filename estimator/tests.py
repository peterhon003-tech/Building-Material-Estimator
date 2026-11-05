from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import calc, services
from .models import FireSystem, Material, MaterialPrice


class CalcTests(TestCase):
    def test_area_board(self):
        # Promatect-H 9mm：1 層，損耗 10%，每張 2.9768 m²
        q = calc.qty_per_sqm(calc.AREA, "2.9768", layers=1, wastage_pct=10)
        self.assertEqual(calc.line_cost(q, "350"), Decimal("129.33"))

    def test_spacing_channel(self):
        # 槽鐵 @610，每支 2.44 m，$18
        q = calc.qty_per_sqm(calc.SPACING, "2.44", spacing_m="0.61", wastage_pct=10)
        self.assertEqual(calc.round_qty(q), Decimal("0.7390"))
        self.assertEqual(calc.line_cost(q, "18"), Decimal("13.30"))

    def test_fixed_pending(self):
        self.assertIsNone(calc.qty_per_sqm(calc.FIXED, "1", fixed_qty=None))
        self.assertIsNone(calc.line_cost(None, "10"))


class SeedAndViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.viewer = User.objects.create_user("viewer", password="pw-12345-x")
        cls.manager = User.objects.create_user("manager", password="pw-12345-x")
        cls.manager.groups.add(Group.objects.get(name="價錢管理員"))

    def test_seed_is_idempotent(self):
        call_command("seed_data", verbosity=0)
        self.assertEqual(FireSystem.objects.count(), 3)
        self.assertEqual(MaterialPrice.objects.filter(material__code="PTH-09").count(), 1)

    def test_two_hour_result(self):
        system = services.find_system("PROMAT", 1, 2)
        r = services.calculate(system)
        costs = {l.item_no: l.cost for l in r.lines}
        self.assertEqual(costs[1], Decimal("129.33"))   # 板
        self.assertEqual(costs[2], Decimal("13.30"))    # 槽鐵
        self.assertEqual(costs[5], Decimal("32.08"))    # 岩棉 1.1 ÷ 0.72 × 21
        self.assertEqual(r.total, Decimal("174.71"))
        self.assertEqual(len(r.pending_lines), 5)

    def test_four_hour_two_layers_rockwool(self):
        r = services.calculate(services.find_system("PROMAT", 1, 4))
        rw = next(l for l in r.lines if l.item_no == 5)
        self.assertEqual(rw.cost, Decimal("91.67"))     # 2 × 1.1 ÷ 0.72 × 30

    def test_calculator_page(self):
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("calculator"), {"brand": "PROMAT", "system_type": "1", "hours": "2"})
        self.assertContains(resp, "R23J17-1A")
        self.assertContains(resp, "174.71")

    def test_not_available(self):
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("calculator"), {"brand": "DURASTEEL", "system_type": "1", "hours": "2"})
        self.assertContains(resp, "此組合尚未提供")

    def test_login_required(self):
        resp = self.client.get(reverse("calculator"))
        self.assertEqual(resp.status_code, 302)

    def test_viewer_cannot_update_price(self):
        self.client.force_login(self.viewer)
        m = Material.objects.get(code="PTH-09")
        resp = self.client.get(reverse("price_add", args=[m.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_manager_updates_price_and_keeps_history(self):
        self.client.force_login(self.manager)
        m = Material.objects.get(code="PTH-09")
        resp = self.client.post(reverse("price_add", args=[m.pk]), {
            "unit_price": "400.00", "supplier": "WinTech Century",
            "effective_date": date.today().isoformat(), "note": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(m.prices.count(), 2)
        self.assertEqual(m.current_price().unit_price, Decimal("400.00"))
        self.assertEqual(m.current_price().updated_by, "manager")

    def test_future_price_not_used_yet(self):
        m = Material.objects.get(code="PTH-09")
        MaterialPrice.objects.create(material=m, unit_price=Decimal("999"),
                                     effective_date=date.today() + timedelta(days=30))
        self.assertEqual(m.current_price().unit_price, Decimal("350.00"))


class AdminAndImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.viewer = User.objects.create_user("viewer2", password="pw-12345-x")
        cls.manager = User.objects.create_user("manager2", password="pw-12345-x")
        cls.manager.groups.add(Group.objects.get(name="價錢管理員"))
        cls.admin = User.objects.create_superuser("boss", password="pw-12345-x")

    # --- 1. 後台價錢唯讀 ---
    def test_admin_price_is_read_only(self):
        from django.contrib import admin as dj_admin
        from django.test import RequestFactory
        ma = dj_admin.site._registry[MaterialPrice]
        req = RequestFactory().get("/")
        req.user = self.admin
        self.assertFalse(ma.has_add_permission(req))
        self.assertFalse(ma.has_change_permission(req))
        self.assertFalse(ma.has_delete_permission(req))
        self.assertTrue(ma.has_view_permission(req))

    def test_admin_price_delete_blocked(self):
        self.client.force_login(self.admin)
        p = MaterialPrice.objects.first()
        resp = self.client.post(reverse("admin:estimator_materialprice_delete", args=[p.pk]), {"post": "yes"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(MaterialPrice.objects.filter(pk=p.pk).exists())

    # --- 2. 新增材料 ---
    def test_manager_adds_material_with_price(self):
        self.client.force_login(self.manager)
        resp = self.client.post(reverse("material_add"), {
            "code": "pth-30", "name": "Promatect-H", "spec": "30mm", "category": "BOARD",
            "unit": "張", "coverage": "2.9768", "unit_price": "1100", "supplier": "WinTech",
            "effective_date": date.today().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        m = Material.objects.get(code="PTH-30")
        self.assertEqual(m.current_price().unit_price, Decimal("1100.00"))
        self.assertEqual(m.current_price().updated_by, "manager2")

    def test_material_without_price(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("material_add"), {
            "code": "X-1", "name": "Test", "category": "SEALANT", "unit": "支", "coverage": "1",
            "effective_date": date.today().isoformat(),
        })
        self.assertFalse(Material.objects.get(code="X-1").prices.exists())

    def test_duplicate_code_rejected(self):
        self.client.force_login(self.manager)
        resp = self.client.post(reverse("material_add"), {
            "code": "PTH-09", "name": "dup", "category": "BOARD", "unit": "張", "coverage": "2.9768",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Material.objects.filter(code="PTH-09").count(), 1)

    def test_viewer_cannot_add_material(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("material_add")).status_code, 403)

    # --- 4. Excel 批量更新 ---
    def _xlsx(self, edits):
        from io import BytesIO
        from openpyxl import load_workbook
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("price_import_template"))
        self.assertEqual(resp.status_code, 200)
        wb = load_workbook(BytesIO(resp.content))
        ws = wb.active
        codes = {ws.cell(r, 1).value: r for r in range(2, ws.max_row + 1)}
        for code, price in edits.items():
            ws.cell(codes[code], 6).value = price
        out = BytesIO()
        wb.save(out)
        return SimpleUploadedFile("prices.xlsx", out.getvalue())

    def test_import_preview_then_confirm(self):
        f = self._xlsx({"PTH-09": 380, "FX-M4-SCREW": 0.35, "AG-50x50x1.0": "abc"})
        resp = self.client.post(reverse("price_import"), {
            "file": f, "default_supplier": "WinTech", "default_date": date.today().isoformat(),
        })
        self.assertContains(resp, "可更新 2 項")
        self.assertContains(resp, "不是數字")
        self.assertEqual(Material.objects.get(code="PTH-09").prices.count(), 1)  # 未確認前不儲存

        resp = self.client.post(reverse("price_import_confirm"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Material.objects.get(code="PTH-09").current_price().unit_price, Decimal("380.00"))
        self.assertEqual(Material.objects.get(code="FX-M4-SCREW").current_price().unit_price, Decimal("0.35"))
        self.assertEqual(Material.objects.get(code="PTH-09").prices.count(), 2)  # 舊價保留

    def test_confirm_twice_does_not_duplicate(self):
        f = self._xlsx({"PTH-09": 380})
        self.client.post(reverse("price_import"), {"file": f, "default_date": date.today().isoformat()})
        self.client.post(reverse("price_import_confirm"))
        self.client.post(reverse("price_import_confirm"))
        self.assertEqual(Material.objects.get(code="PTH-09").prices.count(), 2)

    def test_viewer_cannot_import(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("price_import")).status_code, 403)
        self.assertEqual(self.client.get(reverse("price_import_template")).status_code, 403)


class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.user = User.objects.create_user("exp", password="pw-12345-x")

    def test_export_xlsx(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.client.force_login(self.user)
        resp = self.client.get(reverse("calculator_export"),
                               {"brand": "PROMAT", "system_type": "1", "hours": "2"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        ws = load_workbook(BytesIO(resp.content)).active
        values = [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]
        self.assertIn("R23J17-1A", values)
        self.assertIn(129.33, values)

    def test_export_invalid_redirects(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("calculator_export"), {"brand": "DURASTEEL", "system_type": "1", "hours": "2"})
        self.assertEqual(resp.status_code, 302)

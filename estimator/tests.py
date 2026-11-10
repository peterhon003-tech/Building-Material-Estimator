from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from . import calc, services
from . import price_import as importer
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


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")   # 這組測試檢查中文文字
class SeedAndViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.viewer = User.objects.create_user("viewer", password="pw-12345-x")
        cls.manager = User.objects.create_user("manager", password="pw-12345-x")
        cls.manager.groups.add(Group.objects.get(name="價錢管理員"))

    def test_seed_is_idempotent(self):
        call_command("seed_data", verbosity=0)
        self.assertEqual(FireSystem.objects.count(), 6)        # Ceiling + Gas Pipe，各 1 / 2 / 4 小時
        self.assertEqual(MaterialPrice.objects.filter(material__code="PTH-09").count(), 1)

    def test_two_hour_result(self):
        system = services.find_system("PROMAT", 1, 2)
        r = services.calculate(system)
        costs = {l.item_no: l.cost for l in r.lines}
        self.assertEqual(costs[1], Decimal("129.33"))   # 板
        self.assertEqual(costs[2], Decimal("21.41"))    # 槽鐵 1.0815 × 1.1 × 18
        self.assertEqual(costs[3], Decimal("13.72"))    # 連牆角鐵 0.8605 × 1.1 × 14.50
        self.assertIsNone(costs[4])                     # 連板角鐵：待定
        self.assertEqual(costs[5], Decimal("32.08"))    # 岩棉 1.1 ÷ 0.72 × 21
        self.assertEqual(r.total, Decimal("196.54"))
        self.assertEqual(len(r.pending_lines), 4)

    def test_four_hour_two_layers_rockwool(self):
        r = services.calculate(services.find_system("PROMAT", 1, 4))
        rw = next(l for l in r.lines if l.item_no == 5)
        self.assertEqual(rw.cost, Decimal("91.67"))     # 2 × 1.1 ÷ 0.72 × 30

    def test_calculator_page_with_price_permission(self):
        estimator = User.objects.create_user("est", password="pw-12345-x")
        estimator.groups.add(Group.objects.get(name="估價員"))
        self.client.force_login(estimator)
        resp = self.client.get(reverse("calculator"), {"brand": "PROMAT", "system_type": "1", "hours": "2"})
        self.assertContains(resp, "R23J17-1A")
        self.assertContains(resp, "196.54")
        self.assertContains(resp, "單價 (HK$)")
        self.assertContains(resp, "原料價錢")                       # 選單有價錢頁
        self.assertEqual(self.client.get(reverse("price_list")).status_code, 200)

    def test_material_only_user_sees_no_prices(self):
        """沒有價錢權限：只見材料和用量，網頁內完全沒有價錢資料。"""
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("calculator"), {"brand": "PROMAT", "system_type": "1", "hours": "2"})
        self.assertContains(resp, "R23J17-1A")
        self.assertContains(resp, "0.3695")                         # 板每 m² 用量
        self.assertNotContains(resp, "單價 (HK$)")
        self.assertNotContains(resp, "129.33")
        self.assertNotContains(resp, "350.00")
        self.assertNotContains(resp, "196.54")
        self.assertNotContains(resp, "WinTech")
        self.assertNotContains(resp, "原料價錢")
        self.assertEqual(self.client.get(reverse("price_list")).status_code, 403)
        m = Material.objects.get(code="PTH-09")
        self.assertEqual(self.client.get(reverse("price_history", args=[m.pk])).status_code, 403)

    def test_calculate_without_prices_reads_no_price(self):
        r = services.calculate(services.find_system("PROMAT", 1, 2), include_prices=False)
        self.assertTrue(all(l.unit_price is None and l.cost is None for l in r.lines))
        self.assertEqual(next(l for l in r.lines if l.item_no == 1).qty, Decimal("0.3695"))

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


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")   # 這組測試檢查中文文字
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
    def _sheet(self, user=None):
        from io import BytesIO
        from openpyxl import load_workbook
        self.client.force_login(user or self.manager)
        resp = self.client.get(reverse("price_import_template"))
        self.assertEqual(resp.status_code, 200)
        wb = load_workbook(BytesIO(resp.content))
        return wb, wb.active

    def _rows(self, ws):
        C = importer.COL
        return {ws.cell(r, C["編號"]).value: r for r in range(2, ws.max_row + 1) if ws.cell(r, C["編號"]).value}

    def _upload(self, wb, default_date=None, **extra):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        out = BytesIO()
        wb.save(out)
        return self.client.post(reverse("price_import"), {
            "file": SimpleUploadedFile("prices.xlsx", out.getvalue()),
            "default_date": default_date or date.today().isoformat(), **extra})

    def _xlsx(self, edits):
        """edits：{編號: 新單價}，傳回可上載的檔案。"""
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        wb, ws = self._sheet()
        rows = self._rows(ws)
        for code, price in edits.items():
            ws.cell(rows[code], importer.COL["新單價"]).value = price
        out = BytesIO()
        wb.save(out)
        return SimpleUploadedFile("prices.xlsx", out.getvalue())

    def _set_row(self, ws, row, **values):
        """values 的 key 用欄名，例如 中文名稱="..."。"""
        for header, value in values.items():
            ws.cell(row, importer.COL[header]).value = value

    def _blank_row(self, ws):
        C = importer.COL
        return next(r for r in range(2, ws.max_row + 2) if not ws.cell(r, C["編號"]).value)

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

    def test_template_columns_and_current_values(self):
        C = importer.COL
        wb, ws = self._sheet()
        self.assertEqual([c.value for c in ws[1]], importer.HEADERS)
        rows = self._rows(ws)
        r = rows["PTH-09"]
        m = Material.objects.get(code="PTH-09")
        self.assertEqual(ws.cell(r, C["中文名稱"]).value, m.name)
        self.assertEqual(ws.cell(r, C["類別"]).value, "板")
        self.assertEqual(ws.cell(r, C["計價單位"]).value, "張")
        self.assertAlmostEqual(ws.cell(r, C["每單位涵蓋量"]).value, 2.9768)
        current = ws.cell(r, C["現時生效日期"])
        self.assertEqual(current.value.date(), m.current_price().effective_date)
        self.assertEqual(current.number_format, "yyyy-mm-dd")
        self.assertIsNone(ws.cell(r, C["生效日期"]).value)                     # 要填的生效日期：留空
        self.assertIsNone(ws.cell(rows["FX-M4-SCREW"], C["現時生效日期"]).value)  # 未有價錢

    def test_unchanged_template_has_nothing_to_update(self):
        wb, ws = self._sheet()
        resp = self._upload(wb)
        self.assertFalse(resp.context["result"].has_updates)
        self.assertEqual(resp.context["result"].errors, [])

    def test_preview_warns_when_date_not_later_than_current(self):
        f = self._xlsx({"PTH-09": 380})
        resp = self.client.post(reverse("price_import"), {"file": f, "default_date": "2020-01-01"})
        self.assertContains(resp, "可更新 1 項")
        self.assertEqual(resp.context["result"].warning_count, 1)
        self.assertIn("2020-01-01", resp.context["result"].valid[0].warning)
        f = self._xlsx({"PTH-09": 380})
        resp = self.client.post(reverse("price_import"), {"file": f, "default_date": date.today().isoformat()})
        self.assertEqual(resp.context["result"].warning_count, 0)
        self.client.post(reverse("price_import_confirm"))               # 有提示也可以儲存
        self.assertEqual(Material.objects.get(code="PTH-09").current_price().unit_price, Decimal("380.00"))

    def test_price_manager_can_change_materials(self):
        self.assertTrue(self.manager.has_perm("estimator.change_material"))
        self.assertTrue(self.manager.has_perm("estimator.add_material"))

    def test_add_new_material_with_price(self):
        wb, ws = self._sheet()
        r = self._blank_row(ws)
        self._set_row(ws, r, 動作="新增", 編號="pth-30", 中文名稱="Promatect-H", 中文規格="30mm",
                      英文名稱="Promatect-H", 類別="板", 計價單位="張", 每單位涵蓋量=2.9768, 新單價=1100)
        resp = self._upload(wb)
        result = resp.context["result"]
        self.assertEqual([n.code for n in result.new], ["PTH-30"])
        self.assertEqual([p.code for p in result.valid], ["PTH-30"])
        self.assertFalse(Material.objects.filter(code="PTH-30").exists())     # 未確認前不儲存
        self.client.post(reverse("price_import_confirm"))
        m = Material.objects.get(code="PTH-30")
        self.assertEqual((m.name, m.spec, m.category, m.unit, m.coverage, m.active),
                         ("Promatect-H", "30mm", "BOARD", "張", Decimal("2.9768"), True))
        self.assertEqual(m.current_price().unit_price, Decimal("1100.00"))

    def test_add_errors(self):
        wb, ws = self._sheet()
        r = self._blank_row(ws)
        self._set_row(ws, r, 動作="新增", 編號="PTH-09", 中文名稱="x", 類別="板", 計價單位="張", 每單位涵蓋量=1)
        self._set_row(ws, r + 1, 編號="NEW-1", 新單價=10)                       # 沒有填「新增」
        self._set_row(ws, r + 2, 動作="新增", 編號="NEW-2", 中文名稱="y", 類別="水泥", 計價單位="包", 每單位涵蓋量=1)
        self._set_row(ws, r + 3, 動作="新增", 編號="NEW-3", 類別="板", 計價單位="張", 每單位涵蓋量=1)   # 沒有名稱
        result = self._upload(wb).context["result"]
        self.assertEqual(result.new, [])
        self.assertEqual([row for row, _ in result.errors], [r, r + 1, r + 2, r + 3])
        self.assertIn("已存在", result.errors[0][1])
        self.assertIn("新增", result.errors[1][1])

    def test_change_material_details(self):
        wb, ws = self._sheet()
        r = self._rows(ws)["AG-50x50x1.0"]
        self._set_row(ws, r, 動作="更新", 中文名稱="鍍鋅角鐵", 英文規格="50x50x1.0mm", 每單位涵蓋量=3)
        result = self._upload(wb).context["result"]
        self.assertEqual(len(result.changes), 1)
        change = result.changes[0]
        self.assertTrue(change.coverage_changed)
        self.assertEqual(set(change.values), {"name", "spec_en", "coverage"})
        self.client.post(reverse("price_import_confirm"))
        m = Material.objects.get(code="AG-50x50x1.0")
        self.assertEqual((m.name, m.spec_en, m.coverage), ("鍍鋅角鐵", "50x50x1.0mm", Decimal("3.0000")))
        self.assertEqual(m.prices.count(), 1)                                 # 價錢沒有改動

    def test_deactivate_unused_material_only(self):
        wb, ws = self._sheet()
        rows = self._rows(ws)
        self._set_row(ws, rows["PTH-25"], 動作="停用")                          # 沒有系統使用
        self._set_row(ws, rows["PTH-09"], 動作="停用")                          # 2hr 系統使用中
        result = self._upload(wb).context["result"]
        self.assertEqual([d.code for d in result.deactivate], ["PTH-25"])
        self.assertEqual([row for row, _ in result.errors], [rows["PTH-09"]])
        self.client.post(reverse("price_import_confirm"))
        self.assertFalse(Material.objects.get(code="PTH-25").active)
        self.assertTrue(Material.objects.get(code="PTH-09").active)
        self.assertNotIn("PTH-25", self._rows(self._sheet()[1]))               # 範本不再列出
        self.assertTrue(Material.objects.get(code="PTH-25").prices.exists())   # 紀錄保留

    def test_price_only_user_cannot_change_materials(self):
        from django.contrib.auth.models import Permission
        user = User.objects.create_user("price_only", password="pw-12345-x")
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="estimator", codename__in=["view_materialprice", "add_materialprice"]))
        wb, ws = self._sheet(user)
        rows = self._rows(ws)
        self._set_row(ws, rows["AG-50x50x1.0"], 中文名稱="改名")
        self._set_row(ws, rows["PTH-25"], 動作="停用")
        self._set_row(ws, rows["PTH-09"], 新單價=380)
        r = self._blank_row(ws)
        self._set_row(ws, r, 動作="新增", 編號="NEW-9", 中文名稱="x", 類別="板", 計價單位="張", 每單位涵蓋量=1)
        result = self._upload(wb).context["result"]
        self.assertEqual((result.new, result.changes, result.deactivate), ([], [], []))
        self.assertEqual([p.code for p in result.valid], ["PTH-09"])
        self.assertEqual(len(result.errors), 3)


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")   # 這組測試檢查中文文字
class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.user = User.objects.create_user("exp", password="pw-12345-x")

    def _export_values(self):
        from io import BytesIO
        from openpyxl import load_workbook
        resp = self.client.get(reverse("calculator_export"),
                               {"brand": "PROMAT", "system_type": "1", "hours": "2"})
        self.assertEqual(resp.status_code, 200)
        ws = load_workbook(BytesIO(resp.content)).active
        return [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]

    def test_export_without_price_permission(self):
        self.client.force_login(self.user)
        values = self._export_values()
        self.assertIn("R23J17-1A", values)
        self.assertIn(0.3695, values)
        self.assertNotIn(129.33, values)
        self.assertNotIn("單價 (HK$)", values)

    def test_export_xlsx(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.user.groups.add(Group.objects.get(name="估價員"))
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


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")   # 這組測試檢查中文文字
class ViewModeTests(TestCase):
    """有價錢權限的用戶可以選「只看材料」；沒有權限的用戶不能用參數取得價錢。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.estimator = User.objects.create_user("vm_est", password="pw-12345-x")
        cls.estimator.groups.add(Group.objects.get(name="估價員"))
        cls.plain = User.objects.create_user("vm_plain", password="pw-12345-x")
        cls.params = {"brand": "PROMAT", "system_type": "1", "hours": "2"}

    def _xlsx_values(self, params):
        from io import BytesIO
        from openpyxl import load_workbook
        resp = self.client.get(reverse("calculator_export"), params)
        self.assertEqual(resp.status_code, 200)
        ws = load_workbook(BytesIO(resp.content)).active
        return [c for row in ws.iter_rows(values_only=True) for c in row if c is not None], resp

    def test_estimator_default_shows_prices_and_option(self):
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator"), self.params)
        self.assertContains(resp, 'name="view" value="material"')
        self.assertContains(resp, "196.54")
        self.assertContains(resp, "匯出 Excel（包括價錢）")

    def test_estimator_material_only_view(self):
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator"), {**self.params, "view": "material"})
        self.assertContains(resp, "0.3695")
        self.assertNotContains(resp, "129.33")
        self.assertNotContains(resp, "單價 (HK$)")
        self.assertContains(resp, "匯出 Excel（只有材料）")

    def test_estimator_export_follows_choice(self):
        self.client.force_login(self.estimator)
        values, resp = self._xlsx_values({**self.params, "view": "material"})
        self.assertNotIn(129.33, values)
        self.assertIn("material", resp["Content-Disposition"])
        values, resp = self._xlsx_values({**self.params, "view": "price"})
        self.assertIn(129.33, values)
        self.assertIn("price", resp["Content-Disposition"])

    def test_plain_user_cannot_force_prices(self):
        self.client.force_login(self.plain)
        resp = self.client.get(reverse("calculator"), {**self.params, "view": "price"})
        self.assertNotContains(resp, "129.33")
        self.assertNotContains(resp, 'type="radio"')      # 沒有「包括價錢 / 只看材料」選項
        values, _ = self._xlsx_values({**self.params, "view": "price"})
        self.assertNotIn(129.33, values)


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")   # 這組測試檢查中文文字
class AreaTests(TestCase):
    """輸入總面積：總用量、訂購數量（向上進位）、總價。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.estimator = User.objects.create_user("ar_est", password="pw-12345-x")
        cls.estimator.groups.add(Group.objects.get(name="估價員"))
        cls.plain = User.objects.create_user("ar_plain", password="pw-12345-x")
        cls.params = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}

    def test_calc_order_qty_rounding(self):
        self.assertEqual(calc.order_qty(Decimal("36.95"), "張"), Decimal("37"))
        self.assertEqual(calc.order_qty(Decimal("37"), "張"), Decimal("37"))
        self.assertEqual(calc.order_qty(Decimal("100.5"), "m²"), Decimal("100.5000"))
        self.assertIsNone(calc.order_qty(None, "張"))

    def test_service_totals(self):
        r = services.calculate(services.find_system("PROMAT", 1, 2), area=Decimal("100"))
        board = next(l for l in r.lines if l.item_no == 1)
        self.assertEqual(board.total_qty, Decimal("36.9524"))
        self.assertEqual(board.order_qty, Decimal("37"))
        self.assertEqual(board.total_cost, Decimal("12933.35"))
        self.assertEqual(r.grand_total, Decimal("19655.55"))   # 板 + 槽鐵 + 連牆角鐵 + 岩棉

    def test_page_with_area_and_prices(self):
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator"), self.params)
        self.assertContains(resp, "總面積 100.00 m²")
        self.assertContains(resp, "12933.35")
        self.assertContains(resp, "19655.55")
        self.assertContains(resp, "196.54")                   # 每 m² 合計仍然顯示

    def test_page_with_area_material_only(self):
        self.client.force_login(self.plain)
        resp = self.client.get(reverse("calculator"), self.params)
        self.assertContains(resp, "訂購數量")
        self.assertContains(resp, "36.95")
        self.assertNotContains(resp, "12933.35")
        self.assertNotContains(resp, "總價 (HK$)")

    def test_invalid_area_falls_back_to_per_sqm(self):
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator"), {**self.params, "area": "abc"})
        self.assertContains(resp, "總面積必須是數字")
        self.assertContains(resp, "196.54")
        self.assertNotContains(resp, "訂購數量")

    def test_export_with_area(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator_export"), self.params)
        ws = load_workbook(BytesIO(resp.content)).active
        values = [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]
        self.assertIn("總面積", values)
        self.assertIn(37, values)
        self.assertIn(12933.35, values)


# 後台頁面會用到靜態檔案；測試時不需要先執行 collectstatic
PLAIN_STATIC = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=PLAIN_STATIC, FB_DEFAULT_LANGUAGE="zh-hant")
class AdminCancelButtonTests(TestCase):
    """後台新增頁有「取消」、編輯頁有「返回列表」，都返回列表頁；唯讀頁不加。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.admin = User.objects.create_superuser("cb_admin", password="pw-12345-x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_add_page_has_cancel(self):
        resp = self.client.get(reverse("admin:auth_user_add"))
        self.assertContains(resp, f'href="{reverse("admin:auth_user_changelist")}" class="closelink" data-fb-cancel>取消</a>')

    def test_change_page_has_back_to_list(self):
        m = Material.objects.get(code="PTH-09")
        resp = self.client.get(reverse("admin:estimator_material_change", args=[m.pk]))
        self.assertContains(resp, 'class="closelink" data-fb-cancel>返回列表</a>')
        self.assertContains(resp, "有未儲存的修改")              # 離開確認的程式碼

    def test_read_only_page_has_no_extra_button(self):
        p = MaterialPrice.objects.first()
        resp = self.client.get(reverse("admin:estimator_materialprice_change", args=[p.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "data-fb-cancel")

    def test_price_form_cancel_has_confirm_marker(self):
        m = Material.objects.get(code="PTH-09")
        resp = self.client.get(reverse("price_add", args=[m.pk]))
        self.assertContains(resp, 'data-fb-cancel>取消</a>')


@override_settings(STORAGES=PLAIN_STATIC)
class LanguageTests(TestCase):
    """每次登入用帳戶的預設語言；右上角切換只維持到登出；未設定 = 英文。"""

    @classmethod
    def setUpTestData(cls):
        from .models import UserProfile
        call_command("seed_data", verbosity=0)
        cls.pw = "pw-12345-x"
        cls.user = User.objects.create_user("lang_user", password=cls.pw)       # 沒有設定 → 英文
        cls.user.groups.add(Group.objects.get(name="估價員"))
        cls.zh_user = User.objects.create_user("lang_zh", password=cls.pw)
        cls.zh_user.groups.add(Group.objects.get(name="估價員"))
        UserProfile.objects.create(user=cls.zh_user, language="zh-hant")       # 預設繁體
        cls.params = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}

    def _set(self, lang):
        return self.client.post(reverse("set_language"), {"language": lang, "next": "/"})

    def _calc(self):
        return self.client.get(reverse("calculator"), self.params)

    def test_no_profile_defaults_to_english(self):
        self.client.login(username="lang_user", password=self.pw)
        resp = self._calc()
        self.assertContains(resp, ">Calculate</button>")
        self.assertContains(resp, "G.I. channel")
        self.assertContains(resp, "Unit price (HK$)")
        self.assertContains(resp, "sheet")

    def test_profile_default_used_at_login(self):
        self.client.login(username="lang_zh", password=self.pw)
        resp = self._calc()
        self.assertContains(resp, ">計算</button>")
        self.assertContains(resp, "G.I. 槽鐵")

    def test_switch_lasts_until_logout_only(self):
        from .models import UserProfile
        self.client.login(username="lang_zh", password=self.pw)
        self._set("en")
        self.assertContains(self._calc(), ">Calculate</button>")         # 這次登入有效
        self.assertEqual(UserProfile.objects.get(user=self.zh_user).language, "zh-hant")  # 預設不變
        self.client.logout()
        self.client.login(username="lang_zh", password=self.pw)
        self.assertContains(self._calc(), ">計算</button>")              # 重新登入回到預設

    def test_login_page_choice_does_not_override_account_default(self):
        self._set("zh-hant")                                             # 登入前在登入頁選繁體
        resp = self.client.get(reverse("login"))
        self.assertContains(resp, ">登入</button>")
        self.client.login(username="lang_user", password=self.pw)       # 帳戶未設定 → 英文
        self.assertContains(self._calc(), ">Calculate</button>")

    def test_login_page_defaults_to_english(self):
        resp = self.client.get(reverse("login"))
        self.assertContains(resp, ">Log in</button>")

    def test_other_user_not_affected(self):
        self.client.login(username="lang_user", password=self.pw)
        self._set("zh-hant")
        self.client.logout()
        self.client.login(username="lang_zh", password=self.pw)
        self.assertContains(self._calc(), ">計算</button>")

    def test_simplified_auto_conversion(self):
        try:
            import opencc  # noqa: F401
        except ImportError:
            self.skipTest("opencc 未安裝")
        self.client.login(username="lang_user", password=self.pw)
        self._set("zh-hans")
        resp = self._calc()
        self.assertContains(resp, ">计算</button>")
        self.assertContains(resp, "G.I. 槽铁")

    def test_invalid_language_ignored(self):
        self.client.login(username="lang_zh", password=self.pw)
        self._set("fr")
        self.assertContains(self._calc(), ">計算</button>")

    def test_unsafe_next_redirects_home(self):
        self.client.login(username="lang_user", password=self.pw)
        resp = self.client.post(reverse("set_language"), {"language": "en", "next": "https://evil.example/"})
        self.assertEqual(resp["Location"], "/")

    def test_excel_export_follows_current_language(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.client.login(username="lang_zh", password=self.pw)
        self._set("en")
        resp = self.client.get(reverse("calculator_export"), self.params)
        ws = load_workbook(BytesIO(resp.content)).active
        values = [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]
        self.assertIn("Unit price (HK$)", values)
        self.assertIn("Order qty", values)
        self.assertIn("G.I. channel 50×50×50×0.8mm × 8 ft", values)
        self.assertIn(12933.35, values)

    def test_english_template_can_be_imported_in_chinese(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from django.core.files.uploadedfile import SimpleUploadedFile
        manager = User.objects.create_user("lang_mgr", password=self.pw)
        manager.groups.add(Group.objects.get(name="價錢管理員"))
        self.client.login(username="lang_mgr", password=self.pw)          # 未設定 → 英文
        wb = load_workbook(BytesIO(self.client.get(reverse("price_import_template")).content))
        ws = wb.active
        C = importer.COL
        self.assertEqual(ws.cell(1, C["新單價"]).value, "New price")
        self.assertEqual(ws.cell(1, C["中文名稱"]).value, "Chinese name")
        codes = {ws.cell(r, C["編號"]).value: r for r in range(2, ws.max_row + 1)}
        self.assertEqual(ws.cell(codes["PTH-09"], C["計價單位"]).value, "sheet")       # 計價單位用英文
        self.assertEqual(ws.cell(codes["AG-50x50x1.0"], C["計價單位"]).value, "pc")
        ws.cell(codes["PTH-09"], C["新單價"]).value = 380
        out = BytesIO()
        wb.save(out)
        self._set("zh-hant")                                               # 換繁體才上載
        resp = self.client.post(reverse("price_import"), {
            "file": SimpleUploadedFile("p.xlsx", out.getvalue()),
            "default_date": date.today().isoformat(),
        })
        self.assertContains(resp, "可更新 1 項")
        result = resp.context["result"]
        self.assertEqual((result.errors, result.changes), ([], []))         # 英文單位（pc 等）當作沒有改動

    def test_admin_switcher_and_default_language_field(self):
        admin_user = User.objects.create_superuser("lang_admin", password=self.pw)
        self.client.login(username="lang_admin", password=self.pw)
        resp = self.client.get(reverse("admin:estimator_material_changelist"))
        self.assertContains(resp, 'name="language"')
        self.assertContains(resp, "English name")
        resp = self.client.get(reverse("admin:auth_user_change", args=[self.zh_user.pk]))
        self.assertContains(resp, "Default language")

    def test_existing_users_migration_sets_english(self):
        from importlib import import_module
        from django.apps import apps as global_apps
        from .models import UserProfile
        mig = import_module("estimator.migrations.0003_default_language")
        mig.set_existing_users_to_english(global_apps, None)
        self.assertEqual(UserProfile.objects.get(user=self.zh_user).language, "en")
        self.assertEqual(UserProfile.objects.get(user=self.user).language, "en")


class SessionTests(TestCase):
    """關閉瀏覽器即登出：登入後的 session cookie 沒有到期日（瀏覽器關閉就刪除）。"""

    def test_session_cookie_is_browser_session_only(self):
        User.objects.create_user("sess_user", password="pw-12345-x")
        resp = self.client.post(reverse("login"), {"username": "sess_user", "password": "pw-12345-x"})
        self.assertEqual(resp.status_code, 302)                     # 登入成功
        cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie["max-age"], "")
        self.assertEqual(cookie["expires"], "")


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")
class AdjustTests(TestCase):
    """臨時調整：頁面提供調整資料；匯出調整後的 Excel；不寫入數據庫；價錢權限由伺服器控制。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.estimator = User.objects.create_user("adj_est", password="pw-12345-x")
        cls.estimator.groups.add(Group.objects.get(name="估價員"))
        cls.plain = User.objects.create_user("adj_plain", password="pw-12345-x")
        cls.params = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}

    def _payload(self, view="price"):
        import json
        return {"payload": json.dumps({
            "brand": "PROMAT", "system_type": "1", "hours": "2", "view": view, "area": "100",
            "lines": [
                {"item_no": 1, "description": "Promat 板", "material": "Promatect-H 9mm", "unit": "張",
                 "qty": "0.3695243214189734", "unit_price": "330", "round_up": True, "state": "edited"},
                {"item_no": 9, "description": "運輸費", "material": "", "unit": "次",
                 "qty": "0.01", "unit_price": "500", "round_up": False, "state": "added"},
            ]})}

    def _values(self, resp):
        from io import BytesIO
        from openpyxl import load_workbook
        ws = load_workbook(BytesIO(resp.content)).active
        return [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]

    def _adjust_data(self, resp):
        """只解析頁面上的調整資料（JSON），不搜尋整頁，避免被 JavaScript 程式碼的文字誤導。"""
        import json, re
        m = re.search(r'<script id="adjust-data" type="application/json">(.*?)</script>',
                      resp.content.decode(), re.S)
        self.assertIsNotNone(m, "頁面沒有調整資料")
        return json.loads(m.group(1))

    def test_page_has_adjust_data_with_prices(self):
        self.client.force_login(self.estimator)
        resp = self.client.get(reverse("calculator"), self.params)
        self.assertContains(resp, 'id="adj-toggle"')
        data = self._adjust_data(resp)
        self.assertTrue(data["show_prices"])
        board = next(l for l in data["lines"] if l["item_no"] == 1)
        self.assertEqual(board["unit_price"], "350.00")

    def test_page_adjust_data_without_prices_for_plain_user(self):
        self.client.force_login(self.plain)
        data = self._adjust_data(self.client.get(reverse("calculator"), self.params))
        self.assertFalse(data["show_prices"])
        price_keys = {"unit_price", "cost", "total_cost", "supplier", "price_date"}
        for line in data["lines"]:
            self.assertFalse(price_keys & set(line), f"第 {line['item_no']} 項含有價錢資料")

    def test_export_adjusted_with_prices(self):
        self.client.force_login(self.estimator)
        before = MaterialPrice.objects.count()
        resp = self.client.post(reverse("calculator_export_adjusted"), self._payload())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("adjusted", resp["Content-Disposition"])
        values = self._values(resp)
        self.assertIn("已手動調整（未儲存到系統）", values)
        self.assertIn(12194.30, values)                 # 0.36952… × 100 × 330
        self.assertIn("運輸費", values)
        self.assertIn(500, values)
        self.assertEqual(MaterialPrice.objects.count(), before)          # 沒有寫入數據庫
        self.assertEqual(Material.objects.get(code="PTH-09").current_price().unit_price, Decimal("350.00"))

    def test_plain_user_prices_ignored(self):
        self.client.force_login(self.plain)
        resp = self.client.post(reverse("calculator_export_adjusted"), self._payload())
        values = self._values(resp)
        self.assertIn("運輸費", values)
        self.assertNotIn(12194.30, values)
        self.assertNotIn(330, values)
        self.assertNotIn("單價 (HK$)", values)

    def test_material_view_ignores_prices(self):
        self.client.force_login(self.estimator)
        values = self._values(self.client.post(reverse("calculator_export_adjusted"), self._payload("material")))
        self.assertNotIn(330, values)

    def test_bad_payload(self):
        self.client.force_login(self.estimator)
        self.assertEqual(self.client.post(reverse("calculator_export_adjusted"), {"payload": "x"}).status_code, 400)
        import json
        bad = json.loads(self._payload()["payload"])
        bad["lines"][0]["qty"] = "abc"
        resp = self.client.post(reverse("calculator_export_adjusted"), {"payload": json.dumps(bad)})
        self.assertEqual(resp.status_code, 400)

    def test_get_not_allowed_and_login_required(self):
        self.client.force_login(self.estimator)
        self.assertEqual(self.client.get(reverse("calculator_export_adjusted")).status_code, 405)
        self.client.logout()
        resp = self.client.post(reverse("calculator_export_adjusted"), self._payload())
        self.assertEqual(resp.status_code, 302)


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")
class ProductOptionTests(TestCase):
    """臨時調整的產品下拉選單：同類別可選、用量由伺服器計算、價錢權限、匯出備註。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.estimator = User.objects.create_user("po_est", password="pw-12345-x")
        cls.estimator.groups.add(Group.objects.get(name="估價員"))
        cls.plain = User.objects.create_user("po_plain", password="pw-12345-x")
        cls.params = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}

    def _data(self, user):
        import json, re
        self.client.force_login(user)
        html = self.client.get(reverse("calculator"), self.params).content.decode()
        m = re.search(r'<script id="adjust-data" type="application/json">(.*?)</script>', html, re.S)
        return json.loads(m.group(1))

    def test_channel_options_same_category_original_first(self):
        data = self._data(self.estimator)
        channel = next(l for l in data["lines"] if l["item_no"] == 2)
        codes = [o["code"] for o in channel["options"]]
        self.assertEqual(codes[0], "CH-50x50x50x0.8")
        self.assertTrue(channel["options"][0]["original"])
        self.assertEqual(set(codes), {"CH-30x50x30x0.6", "CH-50x50x50x0.8", "CH-100x50x100x1.0"})
        heavy = next(o for o in channel["options"] if o["code"] == "CH-100x50x100x1.0")
        self.assertFalse(heavy["original"])
        self.assertEqual(heavy["unit_price"], "33.00")
        self.assertEqual(round(float(heavy["qty"]), 4), 1.1897)        # 伺服器按該組件的設定計好（1.0815 × 1.1）

    def test_board_options_only_boards(self):
        data = self._data(self.estimator)
        board = next(l for l in data["lines"] if l["item_no"] == 1)
        self.assertTrue(all(o["code"].startswith(("PTH-", "PRM60-")) for o in board["options"]))

    def test_catalogue_has_all_materials(self):
        data = self._data(self.estimator)
        codes = {c["code"] for c in data["catalogue"]}
        self.assertEqual(codes, set(Material.objects.filter(active=True).values_list("code", flat=True)))

    def test_no_prices_in_options_for_plain_user(self):
        data = self._data(self.plain)
        price_keys = {"unit_price", "supplier", "price_date"}
        for line in data["lines"]:
            for o in line["options"]:
                self.assertFalse(price_keys & set(o))
        for c in data["catalogue"]:
            self.assertFalse(price_keys & set(c))

    def test_export_notes_replacement_and_warning(self):
        import json
        from io import BytesIO
        from openpyxl import load_workbook
        self.client.force_login(self.estimator)
        payload = {"brand": "PROMAT", "system_type": "1", "hours": "2", "view": "price", "area": "100",
                   "lines": [{"item_no": 2, "description": "G.I. 槽鐵", "material": "G.I. 槽鐵 100×50×100×1.0mm × 8尺",
                              "unit": "支", "qty": "0.7390486428", "unit_price": "33", "round_up": True,
                              "state": "edited", "code": "CH-100x50x100x1.0",
                              "replaced_from": "G.I. 槽鐵 50×50×50×0.8mm × 8尺", "off_spec": True}]}
        resp = self.client.post(reverse("calculator_export_adjusted"), {"payload": json.dumps(payload)})
        self.assertEqual(resp.status_code, 200)
        ws = load_workbook(BytesIO(resp.content)).active
        notes = " ".join(str(c) for row in ws.iter_rows(values_only=True) for c in row if isinstance(c, str))
        self.assertIn("已替換：G.I. 槽鐵 50×50×50×0.8mm × 8尺 → G.I. 槽鐵 100×50×100×1.0mm × 8尺", notes)
        self.assertIn("不在測試報告配方內", notes)


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant")
class SystemTypeTests(TestCase):
    """Enclosure for Ceiling / Enclosure for Gas Pipe / Partition。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)

    def _costs(self, system_type, hours=2):
        r = services.calculate(services.find_system("PROMAT", system_type, hours))
        return {l.item_no: l for l in r.lines}, r

    def test_type_choices_order(self):
        self.assertEqual([v for v, _ in FireSystem.TYPE_CHOICES], [1, 3, 2])
        self.assertEqual(dict(FireSystem.TYPE_CHOICES)[1], "Enclosure for Ceiling")

    def test_ceiling_steel_quantities(self):
        lines, _ = self._costs(1)
        self.assertEqual(lines[2].qty, Decimal("1.1897"))         # 槽鐵 1.0815 × 1.1
        self.assertEqual(lines[3].qty, Decimal("0.9466"))         # 連牆角鐵 0.8605 × 1.1
        self.assertIsNone(lines[4].qty)                           # 連板角鐵：待定

    def test_gas_pipe_steel_quantities_and_costs(self):
        lines, r = self._costs(3)
        self.assertEqual((lines[2].qty, lines[2].cost), (Decimal("0.7370"), Decimal("13.27")))   # 0.67 × 1.1 × 18
        self.assertEqual((lines[3].qty, lines[3].cost), (Decimal("0.0550"), Decimal("0.80")))    # 0.05 × 1.1 × 14.50
        self.assertEqual((lines[4].qty, lines[4].cost), (Decimal("1.4960"), Decimal("16.46")))   # 1.36 × 1.1 × 11
        self.assertEqual(lines[1].cost, Decimal("129.33"))         # 板和岩棉與 Ceiling 相同
        self.assertEqual(lines[5].cost, Decimal("32.08"))
        self.assertEqual(r.total, Decimal("191.94"))

    def test_gas_pipe_all_hours(self):
        for hours in (1, 2, 4):
            lines, _ = self._costs(3, hours)
            self.assertEqual(lines[2].qty, Decimal("0.7370"))
            self.assertEqual(lines[4].qty, Decimal("1.4960"))

    def test_calculator_dropdown_and_gas_pipe_page(self):
        user = User.objects.create_user("st_est", password="pw-12345-x")
        user.groups.add(Group.objects.get(name="估價員"))
        self.client.force_login(user)
        resp = self.client.get(reverse("calculator"), {"brand": "PROMAT", "system_type": "3", "hours": "2"})
        self.assertContains(resp, '<option value="3" selected>Enclosure for Gas Pipe</option>', html=True)
        self.assertEqual(resp.context["result"].system.system_type, 3)
        self.assertEqual(resp.context["availability"]["PROMAT"]["3"], [1, 2, 4])

    def test_migration_updates_old_enclosure_but_keeps_manual_changes(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module("estimator.migrations.0004_ceiling_gas_pipe")
        two = services.find_system("PROMAT", 1, 2)
        four = services.find_system("PROMAT", 1, 4)
        # 還原為舊的 Enclosure 設定
        for s in (two, four):
            s.components.filter(item_no=2).update(method="SPACING", spacing_m=Decimal("0.610"),
                                                  fixed_qty_per_sqm=None, note="@610mm c/c")
            s.components.filter(item_no=3).update(fixed_qty_per_sqm=None, note="每 m² 數量待定")
        four.components.filter(item_no=3).update(fixed_qty_per_sqm=Decimal("0.5"))   # 管理員改過
        migration.update_ceiling(apps, None)
        ch = two.components.get(item_no=2)
        self.assertEqual((ch.method, ch.spacing_m, ch.fixed_qty_per_sqm, ch.wastage_pct),
                         ("FIXED", None, Decimal("1.0815"), Decimal("10")))
        self.assertEqual(two.components.get(item_no=3).fixed_qty_per_sqm, Decimal("0.8605"))
        self.assertEqual(four.components.get(item_no=3).fixed_qty_per_sqm, Decimal("0.5"))   # 沒有覆蓋
        self.assertTrue(ch.note_en.startswith("Ceiling: 1.0815"))

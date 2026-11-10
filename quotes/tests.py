import json
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from estimator.models import Material, MaterialPrice

from . import services
from .models import Quotation, QuotationItem, QuotationLine

PARAMS = {"brand": "PROMAT", "system_type": "1", "hours": "2", "area": "100"}
PRICE_HEADERS = {"單價 (HK$)", "每 m² 價錢 (HK$)", "總價 (HK$)", "合計 (HK$)", "每 m² 合計 (HK$)"}
LINE_KEYS = ("item_no", "description", "material", "unit", "qty", "round_up", "state", "method",
             "basis", "note", "code", "unit_price", "supplier", "price_date")


# 測試假設功能已開啟；settings.py 關閉了也照樣測試（停用時的行為見 QuoteSwitchTests）
@override_settings(FB_DEFAULT_LANGUAGE="zh-hant", FB_QUOTES_ENABLED=True, FB_CALC_HISTORY_ENABLED=True)
class QuoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        est_group = Group.objects.get(name="估價員")
        cls.est = User.objects.create_user("q_est", password="pw-12345-x")
        cls.est.groups.add(est_group)
        cls.est2 = User.objects.create_user("q_est2", password="pw-12345-x")
        cls.est2.groups.add(est_group)
        cls.plain = User.objects.create_user("q_plain", password="pw-12345-x")
        cls.staff = User.objects.create_user("q_staff", password="pw-12345-x", is_staff=True)
        cls.staff.groups.add(est_group)

    # ---------- 工具 ----------
    def payload_for(self, user, **params):
        """模擬計價頁 JavaScript 送出的內容（未調整）。"""
        self.client.force_login(user)
        data = self.client.get(reverse("calculator"), {**PARAMS, **params}).context["adjust_data"]
        lines = [{k: l.get(k, "") for k in LINE_KEYS} for l in data["lines"]]
        return {"brand": data["brand"], "system_type": data["system_type"], "hours": data["hours"],
                "view": data["view"], "area": data["area"], "lines": lines}

    def save(self, user, payload, target="new", existing=None, title="", confirm=True):
        self.client.force_login(user)
        data = {"source": "calc", "payload": json.dumps(payload), "target": target, "title": title}
        if confirm:
            data["confirm"] = "1"
        if existing is not None:
            data["existing"] = str(existing)
        return self.client.post(reverse("quote_save"), data)

    def new_quote(self, user=None, **params):
        user = user or self.est
        self.save(user, self.payload_for(user, **params))
        return Quotation.objects.order_by("-pk").first()

    def board(self, item):
        return item.lines.get(item_no=1)

    def edit_post(self, item, user=None, changes=None, extra=None, area="100", title="1/F"):
        """送出「修改項目」表單。changes：{行次序: {欄: 值}}。"""
        self.client.force_login(user or self.est)
        rows = []
        for l in item.lines.all():
            rows.append({"id": str(l.pk), "description": l.description, "material": l.material, "unit": l.unit,
                         "qty": "" if l.qty is None else str(l.qty),
                         "unit_price": "" if l.unit_price is None else str(l.unit_price),
                         "note": l.note, "round_up": l.round_up})
        for idx, ch in (changes or {}).items():
            rows[idx].update(ch)
        rows += extra or []
        data = {"title": title, "area": area, "rows": str(len(rows))}
        for i, r in enumerate(rows):
            for k, v in r.items():
                if k in ("round_up", "delete"):
                    if v:
                        data[f"l{i}_{k}"] = "1"
                else:
                    data[f"l{i}_{k}"] = v
        return self.client.post(reverse("quote_item_edit", args=[item.quotation_id, item.pk]), data)

    def xlsx_values(self, resp):
        wb = load_workbook(BytesIO(resp.content))
        return {str(c.value) for row in wb.active.iter_rows() for c in row if c.value is not None}

    # ---------- 另存為報價 ----------
    def test_first_step_shows_choice_and_creates_nothing(self):
        resp = self.save(self.est, self.payload_for(self.est), confirm=False)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "quotes/save.html")
        self.assertEqual(Quotation.objects.count(), 0)

    def test_save_new_quote_snapshot(self):
        resp = self.save(self.est, self.payload_for(self.est), title="1/F 走廊")
        quote = Quotation.objects.get()
        self.assertRedirects(resp, reverse("quote_detail", args=[quote.pk]))
        self.assertEqual(quote.number, f"Q-{timezone.localdate().year}-0001")
        self.assertEqual(quote.revision, "A")
        self.assertEqual(quote.status, Quotation.DRAFT)
        self.assertEqual(quote.created_by, self.est)
        item = quote.items.get()
        self.assertEqual(item.title, "1/F 走廊")
        self.assertEqual(item.fire_rating_hours, 2)
        self.assertEqual(item.area, Decimal("100.00"))
        self.assertTrue(item.include_prices)
        self.assertFalse(item.adjusted)
        self.assertEqual(item.total_per_sqm, Decimal("174.71"))
        self.assertEqual(item.grand_total, Decimal("17471.97"))
        board = self.board(item)
        self.assertEqual(board.unit_price, Decimal("350.00"))
        self.assertEqual(board.qty, Decimal("0.3695"))
        self.assertEqual(board.order_qty, Decimal("37"))
        self.assertEqual(board.cost, Decimal("129.33"))
        self.assertEqual(board.state, QuotationLine.ORIGINAL)
        self.assertTrue(board.code)
        self.assertEqual(quote.totals(), (Decimal("17471.97"), False))

    def test_later_price_change_does_not_affect_quote(self):
        quote = self.new_quote()
        board = self.board(quote.items.get())
        MaterialPrice.objects.create(material=Material.objects.get(code=board.code), unit_price=Decimal("999"),
                                     effective_date=date.today(), supplier="X")
        self.client.force_login(self.est)
        self.client.get(reverse("quote_detail", args=[quote.pk]))
        item = QuotationItem.objects.get(quotation=quote)
        self.assertEqual(self.board(item).unit_price, Decimal("350.00"))
        self.assertEqual(item.grand_total, Decimal("17471.97"))

    def test_adjusted_lines_are_saved(self):
        payload = self.payload_for(self.est)
        payload["lines"][0].update(unit_price="330", state="edited")
        payload["lines"].append({"item_no": 99, "description": "膠", "material": "Sealant", "unit": "支",
                                 "qty": "0.05", "unit_price": "40", "state": "added", "round_up": True})
        self.save(self.est, payload)
        item = QuotationItem.objects.get()
        self.assertTrue(item.adjusted)
        board = self.board(item)
        self.assertEqual(board.state, QuotationLine.EDITED)
        self.assertEqual(board.cost, Decimal("121.94"))
        added = item.lines.get(item_no=99)
        self.assertEqual(added.state, QuotationLine.ADDED)
        self.assertEqual(added.order_qty, Decimal("5"))
        self.assertEqual(added.total_cost, Decimal("200.00"))

    def test_material_only_user_prices_ignored(self):
        payload = self.payload_for(self.plain)
        for line in payload["lines"]:
            line["unit_price"] = "999"                    # 偽造價錢，伺服器必須忽略
        payload["view"] = "price"
        self.save(self.plain, payload)
        item = QuotationItem.objects.get()
        self.assertFalse(item.include_prices)
        self.assertIsNone(item.total_per_sqm)
        self.assertIsNone(item.grand_total)
        self.assertFalse(item.lines.exclude(unit_price=None).exists())
        self.assertFalse(item.lines.exclude(cost=None).exists())
        self.assertEqual(self.board(item).order_qty, Decimal("37"))

    def test_estimator_material_view_saves_without_prices(self):
        self.save(self.est, self.payload_for(self.est, view="material"))
        item = QuotationItem.objects.get()
        self.assertFalse(item.include_prices)
        self.assertFalse(item.lines.exclude(unit_price=None).exists())

    def test_bad_payload_rejected(self):
        self.client.force_login(self.est)
        resp = self.client.post(reverse("quote_save"), {"source": "calc", "payload": "{bad", "confirm": "1"})
        self.assertEqual(resp.status_code, 400)
        payload = self.payload_for(self.est)
        payload["lines"][0]["qty"] = "abc"
        self.assertEqual(self.save(self.est, payload).status_code, 400)
        self.assertEqual(Quotation.objects.count(), 0)

    def test_add_second_item_to_existing_draft(self):
        quote = self.new_quote()
        resp = self.save(self.est, self.payload_for(self.est, hours="4"), target="existing", existing=quote.pk)
        self.assertRedirects(resp, reverse("quote_detail", args=[quote.pk]))
        items = list(quote.items.all())
        self.assertEqual([i.position for i in items], [1, 2])
        self.assertEqual([i.fire_rating_hours for i in items], [2, 4])
        total, partial = quote.totals()
        self.assertEqual(total, items[0].grand_total + items[1].grand_total)
        self.assertFalse(partial)

    def test_cannot_add_to_someone_elses_draft(self):
        quote = self.new_quote(self.est)
        self.save(self.est2, self.payload_for(self.est2), target="existing", existing=quote.pk)
        self.assertEqual(quote.items.count(), 1)

    def test_staff_can_add_to_someone_elses_draft(self):
        quote = self.new_quote(self.est)
        self.save(self.staff, self.payload_for(self.staff, hours="4"), target="existing", existing=quote.pk)
        self.assertEqual(quote.items.count(), 2)

    def test_step_one_preselects_quote_from_calculator(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        data = {"source": "calc", "payload": json.dumps(self.payload_for(self.est)), "to_quote": str(quote.pk)}
        resp = self.client.post(reverse("quote_save"), data)
        self.assertEqual(resp.context["preselect"], str(quote.pk))

    def test_numbers_increase(self):
        q1 = services.create_quotation(self.est)
        q2 = services.create_quotation(self.est)
        year = timezone.localdate().year
        self.assertEqual((q1.number, q2.number), (f"Q-{year}-0001", f"Q-{year}-0002"))

    def test_next_revision(self):
        self.assertEqual(services.next_revision("A"), "B")
        self.assertEqual(services.next_revision("Z"), "AA")
        self.assertEqual(services.next_revision("AZ"), "BA")

    # ---------- 查看和權限 ----------
    def test_everyone_can_view_but_only_owner_edits(self):
        quote = self.new_quote(self.est)
        self.client.force_login(self.est2)
        resp = self.client.get(reverse("quote_detail", args=[quote.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_edit"])
        self.client.post(reverse("quote_detail", args=[quote.pk]), {"customer_name": "Hacker"})
        quote.refresh_from_db()
        self.assertEqual(quote.customer_name, "")
        item = quote.items.get()
        self.client.post(reverse("quote_item_delete", args=[quote.pk, item.pk]))
        self.assertTrue(QuotationItem.objects.filter(pk=item.pk).exists())

    def test_owner_saves_customer_details(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        self.client.post(reverse("quote_detail", args=[quote.pk]), {
            "customer_name": "ABC 工程", "contact": "陳生 9123 4567", "project": "九龍某工地", "remarks": "有效期 30 日"})
        quote.refresh_from_db()
        self.assertEqual((quote.customer_name, quote.contact, quote.project, quote.remarks),
                         ("ABC 工程", "陳生 9123 4567", "九龍某工地", "有效期 30 日"))
        self.assertEqual(quote.updated_by, "q_est")

    def test_staff_can_edit_any_draft(self):
        quote = self.new_quote(self.est)
        self.client.force_login(self.staff)
        self.client.post(reverse("quote_detail", args=[quote.pk]), {"customer_name": "By staff"})
        quote.refresh_from_db()
        self.assertEqual(quote.customer_name, "By staff")

    def test_material_only_user_never_sees_prices(self):
        quote = self.new_quote(self.est)
        self.client.force_login(self.plain)
        resp = self.client.get(reverse("quote_detail", args=[quote.pk]))
        self.assertFalse(resp.context["show_prices"])
        self.assertNotContains(resp, 'id="quote-total"')
        resp = self.client.get(reverse("quote_list"))
        self.assertFalse(resp.context["can_see_price"])
        resp = self.client.get(reverse("quote_export", args=[quote.pk]))
        self.assertFalse(PRICE_HEADERS & self.xlsx_values(resp))
        self.assertNotIn("350.0", self.xlsx_values(resp))

    def test_plain_owner_cannot_edit_item_with_prices(self):
        self.save(self.plain, self.payload_for(self.plain))
        quote = Quotation.objects.get()
        self.save(self.staff, self.payload_for(self.staff), target="existing", existing=quote.pk)
        priced = quote.items.get(include_prices=True)
        resp = self.edit_post(priced, user=self.plain, changes={0: {"qty": "1"}})
        self.assertRedirects(resp, reverse("quote_detail", args=[quote.pk]))
        self.assertEqual(self.board(priced).qty, Decimal("0.3695"))
        plain_item = quote.items.get(include_prices=False)
        self.edit_post(plain_item, user=self.plain, changes={0: {"qty": "0.5"}})
        self.assertEqual(self.board(plain_item).qty, Decimal("0.5000"))

    # ---------- 修改項目 ----------
    def test_unchanged_edit_keeps_exact_figures(self):
        quote = self.new_quote()
        item = quote.items.get()
        resp = self.edit_post(item)
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.grand_total, Decimal("17471.97"))
        self.assertEqual(item.title, "1/F")
        self.assertFalse(item.lines.exclude(state=QuotationLine.ORIGINAL).exists())

    def test_edit_price_area_delete_and_add(self):
        quote = self.new_quote()
        item = quote.items.get()
        last = item.lines.count() - 1
        self.edit_post(item, area="50", changes={0: {"unit_price": "330"}, last: {"delete": True}},
                       extra=[{"id": "", "description": "膠", "material": "Sealant", "unit": "支",
                               "qty": "0.05", "unit_price": "40", "round_up": True}])
        item.refresh_from_db()
        self.assertEqual(item.area, Decimal("50.00"))
        self.assertTrue(item.adjusted)
        board = self.board(item)
        self.assertEqual(board.state, QuotationLine.EDITED)
        self.assertEqual(board.cost, Decimal("121.94"))
        self.assertEqual(board.order_qty, Decimal("19"))       # 0.3695 × 50 = 18.48 → 19
        added = item.lines.get(state=QuotationLine.ADDED)
        self.assertEqual(added.total_cost, Decimal("100.00"))   # 0.05 × 50 × 40
        self.assertEqual(item.lines.count(), last + 1)
        self.assertEqual(item.total_per_sqm, sum(l.cost for l in item.lines.all() if l.cost is not None))

    def test_edit_rejects_bad_number(self):
        quote = self.new_quote()
        item = quote.items.get()
        resp = self.edit_post(item, changes={0: {"qty": "-1"}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.board(item).qty, Decimal("0.3695"))

    def test_move_and_delete_items(self):
        quote = self.new_quote()
        self.save(self.est, self.payload_for(self.est, hours="4"), target="existing", existing=quote.pk)
        first, second = quote.items.all()
        self.client.post(reverse("quote_item_move", args=[quote.pk, second.pk, "up"]))
        self.assertEqual([i.pk for i in quote.items.all()], [second.pk, first.pk])
        self.client.post(reverse("quote_item_delete", args=[quote.pk, second.pk]))
        self.assertEqual([(i.pk, i.position) for i in quote.items.all()], [(first.pk, 1)])

    # ---------- 發出、取消、新版本 ----------
    def test_issue_locks_quote(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        self.client.post(reverse("quote_issue", args=[quote.pk]))
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.ISSUED)
        self.assertIsNotNone(quote.issued_at)
        self.client.post(reverse("quote_detail", args=[quote.pk]), {"customer_name": "Changed"})
        item = quote.items.get()
        self.edit_post(item, changes={0: {"qty": "1"}})
        self.save(self.est, self.payload_for(self.est), target="existing", existing=quote.pk)
        quote.refresh_from_db()
        self.assertEqual(quote.customer_name, "")
        self.assertEqual(self.board(item).qty, Decimal("0.3695"))
        self.assertEqual(quote.items.count(), 1)

    def test_empty_quote_cannot_be_issued(self):
        quote = services.create_quotation(self.est)
        self.client.force_login(self.est)
        self.client.post(reverse("quote_issue", args=[quote.pk]))
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.DRAFT)

    def test_new_revision_copies_and_keeps_old(self):
        quote = self.new_quote()
        quote.customer_name = "ABC"
        quote.save()
        self.client.force_login(self.est)
        self.client.post(reverse("quote_issue", args=[quote.pk]))
        resp = self.client.post(reverse("quote_revise", args=[quote.pk]))
        rev_b = Quotation.objects.get(number=quote.number, revision="B")
        self.assertRedirects(resp, reverse("quote_detail", args=[rev_b.pk]))
        self.assertEqual(rev_b.status, Quotation.DRAFT)
        self.assertEqual(rev_b.customer_name, "ABC")
        self.assertEqual(rev_b.created_by, self.est)
        self.assertEqual(rev_b.revised_from, quote)
        item_b = rev_b.items.get()
        self.assertEqual(item_b.grand_total, Decimal("17471.97"))
        self.assertEqual(item_b.lines.count(), quote.items.get().lines.count())
        # 修改新版本不影響舊版本
        self.edit_post(item_b, changes={0: {"unit_price": "330"}})
        self.assertEqual(self.board(quote.items.get()).unit_price, Decimal("350.00"))
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.ISSUED)
        # 舊版本不可以再建立新版本；草稿也不用
        self.client.post(reverse("quote_revise", args=[quote.pk]))
        self.client.post(reverse("quote_revise", args=[rev_b.pk]))
        self.assertEqual(Quotation.objects.filter(number=quote.number).count(), 2)

    def test_other_user_cannot_revise_or_cancel(self):
        quote = self.new_quote()
        self.client.force_login(self.est2)
        self.assertEqual(self.client.post(reverse("quote_cancel", args=[quote.pk])).status_code, 403)
        quote.status = Quotation.ISSUED
        quote.save()
        self.assertEqual(self.client.post(reverse("quote_revise", args=[quote.pk])).status_code, 403)

    def test_cancel(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        self.client.post(reverse("quote_cancel", args=[quote.pk]))
        quote.refresh_from_db()
        self.assertEqual(quote.status, Quotation.CANCELLED)
        self.assertFalse(quote.can_edit(self.est))

    def test_list_shows_latest_revision_only_by_default(self):
        quote = self.new_quote()
        services.issue(quote, self.est)
        rev_b = services.new_revision(quote, self.est)
        self.client.force_login(self.est2)
        resp = self.client.get(reverse("quote_list"))
        self.assertEqual([q.pk for q in resp.context["page"].object_list], [rev_b.pk])
        resp = self.client.get(reverse("quote_list"), {"all_revisions": "1"})
        self.assertEqual({q.pk for q in resp.context["page"].object_list}, {quote.pk, rev_b.pk})
        self.assertEqual(resp.context["page"].object_list[0].item_count, 1)

    def test_list_newest_first(self):
        old = services.create_quotation(self.est)
        new = services.create_quotation(self.est)
        services.touch(old, self.est)                     # 最近修改的排最前
        self.client.force_login(self.est)
        resp = self.client.get(reverse("quote_list"))
        self.assertEqual([q.pk for q in resp.context["page"].object_list], [old.pk, new.pk])

    # ---------- 匯出 Excel ----------
    def test_export_with_and_without_prices(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        resp = self.client.get(reverse("quote_export", args=[quote.pk]))
        self.assertEqual(resp["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        values = self.xlsx_values(resp)
        self.assertIn(f"報價 {quote.label}", values)
        self.assertIn("單價 (HK$)", values)
        values = self.xlsx_values(self.client.get(reverse("quote_export", args=[quote.pk]), {"view": "material"}))
        self.assertFalse(PRICE_HEADERS & values)

    # ---------- 由計價頁和計價紀錄進入 ----------
    def test_calculator_has_save_button_and_keeps_target(self):
        self.client.force_login(self.est)
        resp = self.client.get(reverse("calculator"), {**PARAMS, "to_quote": "5"})
        self.assertContains(resp, 'id="quote-btn"')
        self.assertContains(resp, '<input type="hidden" name="to_quote" value="5">')

    def test_convert_history_record(self):
        from history.models import CalcRecord
        self.client.force_login(self.est)
        self.client.get(reverse("calculator"), PARAMS)
        rec = CalcRecord.objects.get(user=self.est)
        self.assertContains(self.client.get(reverse("history_detail", args=[rec.pk])), 'id="to-quote-btn"')
        resp = self.client.post(reverse("quote_save"), {"source": "record", "record": str(rec.pk),
                                                        "confirm": "1", "target": "new"})
        quote = Quotation.objects.get()
        self.assertRedirects(resp, reverse("quote_detail", args=[quote.pk]))
        item = quote.items.get()
        self.assertTrue(item.include_prices)
        self.assertEqual(item.grand_total, Decimal("17471.97"))
        self.assertEqual(self.board(item).order_qty, Decimal("37"))
        # 別人的計價紀錄不可以轉換
        self.client.force_login(self.est2)
        resp = self.client.post(reverse("quote_save"), {"source": "record", "record": str(rec.pk),
                                                        "confirm": "1", "target": "new"})
        self.assertEqual(resp.status_code, 404)

    @override_settings(FB_DEFAULT_LANGUAGE="en")
    def test_english_interface(self):
        quote = self.new_quote()
        self.client.force_login(self.est)
        resp = self.client.get(reverse("quote_detail", args=[quote.pk]))
        self.assertContains(resp, "Customer details")
        self.assertContains(resp, f"Quotation {quote.label}")


@override_settings(FB_DEFAULT_LANGUAGE="zh-hant", FB_QUOTES_ENABLED=False, FB_CALC_HISTORY_ENABLED=True)
class QuoteSwitchTests(TestCase):
    """FB_QUOTES_ENABLED = False：隱藏選單和按鈕，網址 404，數據保留。"""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)
        cls.est = User.objects.create_user("s_est", password="pw-12345-x", is_staff=True)
        cls.est.groups.add(Group.objects.get(name="估價員"))
        cls.quote = services.create_quotation(cls.est)

    def setUp(self):
        self.client.force_login(self.est)

    def test_pages_return_404(self):
        self.assertEqual(self.client.get(reverse("quote_list")).status_code, 404)
        self.assertEqual(self.client.get(reverse("quote_detail", args=[self.quote.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("quote_export", args=[self.quote.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("quote_save"), {"source": "calc"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("quote_issue", args=[self.quote.pk])).status_code, 404)

    def test_menu_and_buttons_hidden(self):
        from history.models import CalcRecord
        resp = self.client.get(reverse("calculator"), {**PARAMS, "to_quote": "5"})
        self.assertNotIn("fb_quotes_url", resp.context)
        self.assertNotContains(resp, 'id="quote-btn"')
        self.assertNotContains(resp, 'name="to_quote"')
        rec = CalcRecord.objects.get(user=self.est)
        self.assertNotContains(self.client.get(reverse("history_detail", args=[rec.pk])), 'id="to-quote-btn"')

    def test_data_kept(self):
        self.assertTrue(Quotation.objects.filter(pk=self.quote.pk).exists())
        with self.settings(FB_QUOTES_ENABLED=True):
            self.assertEqual(self.client.get(reverse("quote_detail", args=[self.quote.pk])).status_code, 200)

"""報價的建立、加入項目、修改、發出和建立新版本。"""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from estimator import adjust, calc
from estimator.i18n import tr

from .models import Quotation, QuotationItem, QuotationLine

EXACT_PLACES = Decimal("0.000000000001")
MAX_NUMBER_TRIES = 5


class QuoteError(ValueError):
    """可以直接顯示給用戶的錯誤（訊息已翻譯）。"""


# ---------- 編號和版本 ----------

def next_number(year=None):
    """下一個報價編號，例如 Q-2026-0001（每年重新開始）。"""
    year = year or timezone.localdate().year
    prefix = f"Q-{year}-"
    last = (Quotation.objects.filter(number__startswith=prefix)
            .order_by("-number").values_list("number", flat=True).first())
    seq = int(last[len(prefix):]) + 1 if last and last[len(prefix):].isdigit() else 1
    return f"{prefix}{seq:04d}"


def next_revision(rev):
    """A → B … Z → AA → AB …"""
    letters = list(rev or "A")
    i = len(letters) - 1
    while i >= 0:
        if letters[i] != "Z":
            letters[i] = chr(ord(letters[i]) + 1)
            return "".join(letters)
        letters[i] = "A"
        i -= 1
    return "A" + "".join(letters)


def create_quotation(user):
    """新增一張空白草稿。兩個人同時建立時，編號撞了就再試。"""
    for _ in range(MAX_NUMBER_TRIES):
        try:
            with transaction.atomic():
                return Quotation.objects.create(number=next_number(), created_by=user,
                                                updated_by=user.get_username())
        except IntegrityError:
            continue
    raise QuoteError(tr("暫時未能建立報價編號，請再試。"))


def latest_revision(quote):
    return Quotation.objects.filter(number=quote.number).order_by("-revision").first()


def _revision_key(rev):
    return (len(rev), rev)


def is_latest(quote):
    revs = Quotation.objects.filter(number=quote.number).values_list("revision", flat=True)
    return max(revs, key=_revision_key) == quote.revision


def touch(quote, user):
    quote.updated_by = user.get_username()
    quote.save(update_fields=["updated_by", "updated_at"])


# ---------- 加入項目 ----------

def _exact(value):
    return None if value is None else Decimal(value).quantize(EXACT_PLACES)


def _new_item(quote, **fields):
    last = quote.items.order_by("-position").values_list("position", flat=True).first() or 0
    return QuotationItem.objects.create(quotation=quote, position=last + 1, **fields)


def add_item_from_rows(quote, user, system, area, rows, include_prices, title="", t=tr):
    """由計價頁（可能已臨時調整）送來的明細建立一個項目。

    數字一律由伺服器按送來的用量和單價重新計算；include_prices=False 時忽略所有價錢。
    """
    computed = adjust.compute_rows(rows, area, include_prices, t=t)
    adjusted = any(r.get("state") in ("edited", "added") for r in rows)
    with transaction.atomic():
        item = _new_item(
            quote, title=(title or "").strip()[:200], brand=system.brand, system_type=system.system_type,
            fire_rating_hours=system.fire_rating_hours, system_label=str(system)[:200],
            frr_label=system.frr_label, report_no=system.report_no, area=area,
            include_prices=include_prices, adjusted=adjusted,
            price_date=date.today() if include_prices else None,
        )
        for pos, (r, c) in enumerate(zip(rows, computed), start=1):
            state = r.get("state") if r.get("state") in ("original", "edited", "added") else "added"
            QuotationLine.objects.create(
                item=item, position=pos, item_no=c["item_no"], description=c["description"],
                material=c["material"], code=c["code"], unit=c["unit"][:20], method=c["method"][:50],
                basis=c["basis"], qty_exact=_exact(c["qty_exact"]), qty=c["qty"], round_up=c["round_up"],
                total_qty=c["total_qty"], order_qty=c["order_qty"],
                unit_price=c["unit_price"], supplier=c["supplier"], price_date=c["price_date"],
                cost=c["cost"], total_cost=c["total_cost"], note=c["note"][:500], state=state,
            )
        item.recalc_totals()
        item.save()
        touch(quote, user)
    return item


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def add_item_from_record(quote, user, record, include_prices, title=""):
    """由計價紀錄（快照）建立項目：直接複製當時的數字，不重新計算。"""
    with transaction.atomic():
        item = _new_item(
            quote, title=(title or "").strip()[:200], brand=record.brand, system_type=record.system_type,
            fire_rating_hours=record.fire_rating_hours, system_label=record.system_label[:200],
            report_no=record.report_no, area=record.area, include_prices=include_prices,
            price_date=record.created_at.date() if include_prices else None,
        )
        for pos, l in enumerate(record.lines, start=1):
            qty = _dec(l.get("qty"))
            QuotationLine.objects.create(
                item=item, position=pos, item_no=int(l.get("item_no") or pos),
                description=str(l.get("description") or "")[:200], material=str(l.get("material") or "")[:200],
                unit=str(l.get("unit") or "")[:20], qty_exact=qty, qty=qty,
                total_qty=_dec(l.get("total_qty")), order_qty=_dec(l.get("order_qty")),
                round_up=str(l.get("unit") or "") not in calc.NO_ROUND_UNITS,
                unit_price=_dec(l.get("unit_price")) if include_prices else None,
                cost=_dec(l.get("cost")) if include_prices else None,
                total_cost=_dec(l.get("total_cost")) if include_prices else None,
                note=str(l.get("note") or "")[:500],
            )
        item.recalc_totals()
        item.save()
        touch(quote, user)
    return item


# ---------- 修改項目 ----------

def update_item(item, user, title, area, rows, can_price, t=tr):
    """儲存「修改項目」頁的內容。

    rows：[{id, description, material, unit, qty, unit_price, note, round_up, delete}]，
    id 空白 = 新增的行。qty 沒有改動時沿用未進位的用量，避免四捨五入誤差。
    can_price=False 時不會改動價錢（這個項目本身沒有價錢）。
    """
    existing = {l.pk: l for l in item.lines.all()}
    with_prices = item.include_prices and can_price
    keep = []
    for r in rows:
        line_id = r.get("id")
        line = existing.get(int(line_id)) if str(line_id or "").isdigit() else None
        if line is None and line_id:
            raise QuoteError(t("資料格式不正確"))
        if r.get("delete"):
            continue
        texts = {k: adjust._text(r.get(k)) for k in ("description", "material", "unit", "note")}
        if line is None and not any(texts[k] for k in ("description", "material")) and not adjust._text(r.get("qty")):
            continue                                        # 空白的新增行
        qty_raw = adjust._text(r.get("qty")).replace(",", "")
        qty = adjust.parse_number(qty_raw, adjust.MAX_QTY, "每 m² 用量", t)
        if line is not None and line.qty is not None and qty == line.qty:
            qty = line.qty_exact if line.qty_exact is not None else line.qty   # 沒有改動
        if with_prices:
            price = adjust.parse_number(r.get("unit_price"), adjust.MAX_PRICE, "單價", t)
        else:
            price = line.unit_price if (line is not None and item.include_prices) else None
        keep.append((line, texts, qty, price, bool(r.get("round_up"))))

    with transaction.atomic():
        item.title = (title or "").strip()[:200]
        item.area = area
        kept_ids = set()
        for pos, (line, texts, qty, price, round_up) in enumerate(keep, start=1):
            if line is None:
                line = QuotationLine(item=item, state=QuotationLine.ADDED, item_no=pos)
            else:
                changed = (texts["description"] != line.description or texts["material"] != line.material
                           or texts["unit"] != line.unit or qty != line.qty_exact or price != line.unit_price
                           or round_up != line.round_up)
                if changed and line.state == QuotationLine.ORIGINAL:
                    line.state = QuotationLine.EDITED
                if price != line.unit_price:
                    line.supplier, line.price_date = "", None
            line.position = pos
            line.description = texts["description"][:200]
            line.material = texts["material"][:200]
            line.unit = texts["unit"][:20]
            line.note = texts["note"][:500]
            line.round_up = round_up
            line.qty_exact = _exact(qty)
            line.unit_price = price
            nums = adjust.line_numbers(qty, price, area, round_up)
            for k, v in nums.items():
                setattr(line, k, v)
            line.save()
            kept_ids.add(line.pk)
        item.lines.exclude(pk__in=kept_ids).delete()
        item.adjusted = item.adjusted or item.lines.exclude(state=QuotationLine.ORIGINAL).exists() \
            or len(kept_ids) != len(existing)
        item.recalc_totals()
        item.save()
        touch(item.quotation, user)
    return item


def delete_item(item, user):
    quote = item.quotation
    with transaction.atomic():
        item.delete()
        for pos, it in enumerate(quote.items.order_by("position", "id"), start=1):
            if it.position != pos:
                it.position = pos
                it.save(update_fields=["position"])
        touch(quote, user)


def move_item(item, user, direction):
    quote = item.quotation
    items = list(quote.items.order_by("position", "id"))
    i = items.index(item)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
        with transaction.atomic():
            for pos, it in enumerate(items, start=1):
                if it.position != pos:
                    it.position = pos
                    it.save(update_fields=["position"])
            touch(quote, user)


# ---------- 狀態 ----------

def issue(quote, user):
    if not quote.is_draft:
        raise QuoteError(tr("只有草稿可以發出。"))
    if not quote.items.exists():
        raise QuoteError(tr("報價未有任何項目，不能發出。"))
    quote.status = Quotation.ISSUED
    quote.issued_at = timezone.now()
    quote.updated_by = user.get_username()
    quote.save()


def cancel(quote, user):
    if quote.status == Quotation.CANCELLED:
        return
    quote.status = Quotation.CANCELLED
    quote.updated_by = user.get_username()
    quote.save()


def new_revision(quote, user):
    """複製成下一個版本（草稿）。舊版本保持不變。"""
    if quote.is_draft:
        raise QuoteError(tr("草稿可以直接修改，不用建立新版本。"))
    if not is_latest(quote):
        raise QuoteError(tr("已有較新的版本，請由最新版本建立。"))
    with transaction.atomic():
        new = Quotation.objects.create(
            number=quote.number, revision=next_revision(max(
                Quotation.objects.filter(number=quote.number).values_list("revision", flat=True),
                key=_revision_key)),
            customer_name=quote.customer_name, contact=quote.contact, project=quote.project,
            remarks=quote.remarks, revised_from=quote, created_by=quote.created_by,
            updated_by=user.get_username(),
        )
        for item in quote.items.all():
            lines = list(item.lines.all())
            item.pk = None
            item._state.adding = True
            item.quotation = new
            item.save()
            for line in lines:
                line.pk = None
                line._state.adding = True
                line.item = item
                line.save()
    return new

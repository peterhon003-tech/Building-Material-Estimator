import json
from datetime import date

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from estimator import services as est_services
from estimator.i18n import tr
from estimator.views import can_see_price, parse_area

from . import services
from .export import build_quote_xlsx
from .forms import QuotationForm
from .models import Quotation, QuotationItem
from .switch import require_enabled

MAX_EDIT_ROWS = 100
BLANK_ROWS = 3


def _show_prices(request):
    """這次是否顯示價錢：要有價錢權限，而且沒有選「只看材料」。由伺服器決定。"""
    return can_see_price(request.user) and request.GET.get("view") != "material"


def _editable_drafts(user):
    qs = Quotation.objects.filter(status=Quotation.DRAFT)
    if not (user.is_staff or user.is_superuser):
        qs = qs.filter(created_by=user)
    return qs.order_by("-updated_at")[:50]


def _get_quote(pk):
    return get_object_or_404(Quotation.objects.select_related("created_by"), pk=pk)


def _forbid(request, quote):
    """不可以修改時：顯示原因並返回報價頁。"""
    if quote.is_draft:
        messages.error(request, tr("只有建立人或系統管理員可以修改這張報價。"))
    else:
        messages.error(request, tr("這張報價已鎖定（{s}），不可以修改。如要修改，請建立新版本。",
                                   s=quote.get_status_display()))
    return redirect("quote_detail", pk=quote.pk)


# ---------- 列表 ----------

@require_enabled
@login_required
def quote_list(request):
    qs = Quotation.objects.select_related("created_by").annotate(
        item_count=Count("items", distinct=True),
        priced_total=Sum("items__grand_total", filter=Q(items__include_prices=True)),
    )
    status = request.GET.get("status", "")
    if status in dict(Quotation.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if request.GET.get("mine"):
        qs = qs.filter(created_by=request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer_name__icontains=q) | Q(project__icontains=q)
                       | Q(contact__icontains=q))
    show_all_revisions = bool(request.GET.get("all_revisions"))
    if not show_all_revisions:
        newer = Quotation.objects.filter(number=OuterRef("number"), pk__gt=OuterRef("pk"))
        qs = qs.filter(~Exists(newer))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "quotes/list.html", {
        "page": page, "can_see_price": can_see_price(request.user),
        "status_choices": Quotation.STATUS_CHOICES, "f": {
            "status": status, "mine": request.GET.get("mine", ""), "q": q,
            "all_revisions": show_all_revisions,
        },
    })


# ---------- 報價頁 ----------

@require_enabled
@login_required
def quote_detail(request, pk):
    quote = _get_quote(pk)
    can_edit = quote.can_edit(request.user)
    form = QuotationForm(instance=quote)
    if request.method == "POST":
        if not can_edit:
            return _forbid(request, quote)
        form = QuotationForm(request.POST, instance=quote)
        if form.is_valid():
            quote = form.save(commit=False)
            quote.updated_by = request.user.get_username()
            quote.save()
            messages.success(request, tr("已儲存客戶資料。"))
            return redirect("quote_detail", pk=quote.pk)

    show = _show_prices(request)
    items = list(quote.items.prefetch_related("lines"))
    total, partial = quote.totals()
    revisions = Quotation.objects.filter(number=quote.number).order_by("pk")
    return render(request, "quotes/detail.html", {
        "quote": quote, "items": items, "form": form, "can_edit": can_edit,
        "can_manage": quote.can_manage(request.user), "is_latest": services.is_latest(quote),
        "show_prices": show, "price_allowed": can_see_price(request.user),
        "view_mode": "material" if request.GET.get("view") == "material" else "price",
        "total": total, "partial": partial, "revisions": revisions,
        "has_area_items": any(i.area is not None for i in items),
    })


# ---------- 另存為報價（由計價頁或計價紀錄） ----------

def _source_from_calculator(request):
    """讀取計價頁送來的明細。傳回 (system, area, rows, include_prices)。"""
    try:
        data = json.loads(request.POST.get("payload", ""))
        system = est_services.find_system(str(data.get("brand", "")), int(data.get("system_type")),
                                          int(data.get("hours")))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(tr("資料格式不正確")) from None
    if not system:
        raise ValueError(tr("請先選擇有效的品牌、系統和耐火時間。"))
    # 價錢權限由伺服器決定：沒有權限或選了「只看材料」，送來的價錢一律忽略
    include_prices = can_see_price(request.user) and data.get("view") != "material"
    area, _ = parse_area(str(data.get("area") or ""))
    rows = data.get("lines")
    from estimator.adjust import compute_rows
    compute_rows(rows, area, include_prices, t=tr)          # 先檢查一次，有錯誤會 raise ValueError
    return system, area, rows, include_prices


def _source_from_record(request):
    if not apps.is_installed("history"):
        raise Http404()
    from history.models import CalcRecord
    qs = CalcRecord.objects.all()
    if not request.user.is_staff:
        qs = qs.filter(user=request.user)
    rid = request.POST.get("record", "")
    if not rid.isdigit():
        raise ValueError(tr("資料格式不正確")) from None
    record = get_object_or_404(qs, pk=int(rid))
    return record, record.include_prices and can_see_price(request.user)


@require_enabled
@require_POST
@login_required
def save_to_quote(request):
    """第一步：選擇「新報價」或「加入現有草稿」；第二步（confirm=1）：建立。"""
    source = request.POST.get("source", "calc")
    try:
        if source == "record":
            record, include_prices = _source_from_record(request)
            summary = {"system": record.system_label, "area": record.area, "lines": len(record.lines),
                       "include_prices": include_prices,
                       "total": record.grand_total if include_prices else None}
        else:
            system, area, rows, include_prices = _source_from_calculator(request)
            summary = {"system": str(system), "area": area, "lines": len(rows),
                       "include_prices": include_prices, "total": None,
                       "adjusted": any(isinstance(r, dict) and r.get("state") in ("edited", "added") for r in rows)}
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    drafts = _editable_drafts(request.user)
    if request.POST.get("confirm"):
        target = request.POST.get("target", "new")
        title = request.POST.get("title", "")
        if target == "new":
            try:
                quote = services.create_quotation(request.user)
            except services.QuoteError as e:
                messages.error(request, str(e))
                return redirect("quote_list")
        else:
            existing = request.POST.get("existing", "")
            if target != "existing" or not existing.isdigit():
                return HttpResponseBadRequest(tr("資料格式不正確"))
            quote = get_object_or_404(Quotation, pk=int(existing))
            if not quote.can_edit(request.user):
                return _forbid(request, quote)
        try:
            if source == "record":
                services.add_item_from_record(quote, request.user, record, include_prices, title=title)
            else:
                services.add_item_from_rows(quote, request.user, system, area, rows, include_prices,
                                            title=title, t=tr)
        except ValueError as e:
            return HttpResponseBadRequest(str(e))
        if target == "new":
            messages.success(request, tr("已建立報價 {q}，請填寫客戶資料。", q=quote.label))
        else:
            messages.success(request, tr("已加入報價 {q}。", q=quote.label))
        return redirect("quote_detail", pk=quote.pk)

    to_quote = request.POST.get("to_quote", "")
    return render(request, "quotes/save.html", {
        "summary": summary, "drafts": drafts, "source": source,
        "payload": request.POST.get("payload", ""), "record": request.POST.get("record", ""),
        "preselect": to_quote if to_quote.isdigit() and any(str(d.pk) == to_quote for d in drafts) else "new",
        "can_see_price": can_see_price(request.user),
    })


# ---------- 修改項目 ----------

def _rows_from_post(post):
    try:
        count = min(int(post.get("rows", "0")), MAX_EDIT_ROWS + BLANK_ROWS)
    except ValueError:
        count = 0
    rows = []
    for i in range(count):
        p = f"l{i}_"
        rows.append({
            "id": post.get(p + "id", ""), "description": post.get(p + "description", ""),
            "material": post.get(p + "material", ""), "unit": post.get(p + "unit", ""),
            "qty": post.get(p + "qty", ""), "unit_price": post.get(p + "unit_price", ""),
            "note": post.get(p + "note", ""), "round_up": bool(post.get(p + "round_up")),
            "delete": bool(post.get(p + "delete")),
        })
    return rows


def _rows_from_item(item):
    rows = [{"id": str(l.pk), "description": l.description, "material": l.material, "unit": l.unit,
             "qty": "" if l.qty is None else str(l.qty),
             "unit_price": "" if l.unit_price is None else str(l.unit_price),
             "note": l.note, "round_up": l.round_up, "delete": False, "state": l.get_state_display(),
             "basis": l.basis}
            for l in item.lines.all()]
    rows += [{"id": "", "description": "", "material": "", "unit": "", "qty": "", "unit_price": "",
              "note": "", "round_up": True, "delete": False, "state": "", "basis": ""}
             for _ in range(BLANK_ROWS)]
    return rows


@require_enabled
@login_required
def item_edit(request, pk, item_pk):
    quote = _get_quote(pk)
    item = get_object_or_404(QuotationItem, pk=item_pk, quotation=quote)
    if not quote.can_edit(request.user):
        return _forbid(request, quote)
    price_ok = can_see_price(request.user)
    if item.include_prices and not price_ok:
        messages.error(request, tr("這個項目包括價錢，你沒有查看價錢的權限，不可以修改。"))
        return redirect("quote_detail", pk=quote.pk)
    with_prices = item.include_prices and price_ok

    title, area_raw = item.title, "" if item.area is None else str(item.area)
    if request.method == "POST":
        title = request.POST.get("title", "")
        area_raw = request.POST.get("area", "")
        rows = _rows_from_post(request.POST)
        area, area_error = parse_area(area_raw)
        try:
            if area_error:
                raise ValueError(area_error)
            if sum(1 for r in rows if not r["delete"]) > MAX_EDIT_ROWS + BLANK_ROWS:
                raise ValueError(tr("項目太多（上限 {n} 項）", n=MAX_EDIT_ROWS))
            services.update_item(item, request.user, title, area, rows, price_ok, t=tr)
        except ValueError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, tr("已儲存項目 {n}。", n=item.position))
            return redirect(f"{_detail_url(quote)}#item-{item.pk}")
    else:
        rows = _rows_from_item(item)
    return render(request, "quotes/item_edit.html", {
        "quote": quote, "item": item, "rows": rows, "row_count": len(rows),
        "with_prices": with_prices, "title": title, "area_raw": area_raw,
    })


def _detail_url(quote):
    from django.urls import reverse
    return reverse("quote_detail", args=[quote.pk])


@require_enabled
@require_POST
@login_required
def item_delete(request, pk, item_pk):
    quote = _get_quote(pk)
    item = get_object_or_404(QuotationItem, pk=item_pk, quotation=quote)
    if not quote.can_edit(request.user):
        return _forbid(request, quote)
    services.delete_item(item, request.user)
    messages.success(request, tr("已刪除項目。"))
    return redirect("quote_detail", pk=quote.pk)


@require_enabled
@require_POST
@login_required
def item_move(request, pk, item_pk, direction):
    quote = _get_quote(pk)
    item = get_object_or_404(QuotationItem, pk=item_pk, quotation=quote)
    if not quote.can_edit(request.user):
        return _forbid(request, quote)
    if direction not in ("up", "down"):
        raise Http404()
    services.move_item(item, request.user, direction)
    return redirect(f"{_detail_url(quote)}#item-{item.pk}")


# ---------- 發出、取消、新版本 ----------

@require_enabled
@require_POST
@login_required
def quote_issue(request, pk):
    quote = _get_quote(pk)
    if not quote.can_edit(request.user):
        return _forbid(request, quote)
    try:
        services.issue(quote, request.user)
    except services.QuoteError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, tr("已發出報價 {q}，內容已鎖定。", q=quote.label))
    return redirect("quote_detail", pk=quote.pk)


@require_enabled
@require_POST
@login_required
def quote_cancel(request, pk):
    quote = _get_quote(pk)
    if not quote.can_manage(request.user):
        return HttpResponseForbidden(tr("只有建立人或系統管理員可以取消這張報價。"))
    services.cancel(quote, request.user)
    messages.success(request, tr("已取消報價 {q}。", q=quote.label))
    return redirect("quote_detail", pk=quote.pk)


@require_enabled
@require_POST
@login_required
def quote_revise(request, pk):
    quote = _get_quote(pk)
    if not quote.can_manage(request.user):
        return HttpResponseForbidden(tr("只有建立人或系統管理員可以建立新版本。"))
    try:
        new = services.new_revision(quote, request.user)
    except services.QuoteError as e:
        messages.error(request, str(e))
        return redirect("quote_detail", pk=quote.pk)
    messages.success(request, tr("已建立新版本 {q}（草稿），舊版本 {old} 保持不變。", q=new.label, old=quote.label))
    return redirect("quote_detail", pk=new.pk)


# ---------- 匯出 Excel ----------

@require_enabled
@login_required
def quote_export(request, pk):
    quote = _get_quote(pk)
    show = _show_prices(request)
    content = build_quote_xlsx(quote, user=request.user.get_username(), show_prices=show, t=tr)
    kind = "price" if show else "material"
    filename = f"{quote.number}-Rev{quote.revision}-{kind}-{date.today():%Y-%m-%d}.xlsx"
    resp = HttpResponse(content,
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

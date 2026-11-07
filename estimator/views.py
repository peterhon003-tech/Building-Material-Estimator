from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import price_import as importer
from .export import build_calc_xlsx
from . import services
from .forms import MaterialForm, PriceForm, PriceImportForm
from .i18n import LANGUAGE_CODES, all_languages, localized, tr
from .models import FireSystem, Material, MaterialPrice, UserProfile

IMPORT_SESSION_KEY = "price_import_rows"
PRICE_VIEW_PERM = "estimator.view_materialprice"


def can_see_price(user):
    """有「查看材料價錢」權限才看到價錢（估價員、價錢管理員、超級用戶）。"""
    return user.has_perm(PRICE_VIEW_PERM)


MAX_AREA = Decimal("1000000")


def parse_area(raw):
    """讀取總面積輸入。傳回 (面積或 None, 錯誤訊息或 "")。"""
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None, ""
    try:
        area = Decimal(raw)
    except Exception:
        return None, tr("總面積必須是數字。")
    if not area.is_finite() or area <= 0:
        return None, tr("總面積必須大於 0。")
    if area > MAX_AREA:
        return None, tr("總面積太大，請檢查輸入。")
    return area.quantize(Decimal("0.01")), ""


def show_prices(request):
    """這次是否顯示價錢。

    沒有價錢權限 → 一定不顯示。
    有權限 → 預設顯示；用戶選「只看材料」（?view=material）就不顯示。
    """
    return can_see_price(request.user) and request.GET.get("view") != "material"


@login_required
def calculator(request):
    brand = request.GET.get("brand", "")
    system_type = request.GET.get("system_type", "")
    hours = request.GET.get("hours", "")

    area_raw = request.GET.get("area", "")
    area, area_error = parse_area(area_raw)

    result = None
    not_available = False
    if brand and system_type and hours:
        try:
            system = services.find_system(brand, int(system_type), int(hours))
        except ValueError:
            system = None
        if system:
            result = services.calculate(system, include_prices=show_prices(request), area=area)
        else:
            not_available = True

    return render(request, "estimator/calculator.html", {
        "brands": FireSystem.BRAND_CHOICES,
        "types": FireSystem.TYPE_CHOICES,
        "hours_choices": FireSystem.HOURS_CHOICES,
        "selected": {"brand": brand, "system_type": system_type, "hours": hours},
        "availability": services.availability(),
        "result": result,
        "not_available": not_available,
        "can_see_price": show_prices(request),          # 這次是否顯示價錢欄
        "price_allowed": can_see_price(request.user),   # 是否可以選擇「包括價錢」
        "view_mode": "material" if request.GET.get("view") == "material" else "price",
        "area_raw": area_raw,
        "area_error": area_error,
    })


@login_required
def calculator_export(request):
    try:
        system = services.find_system(
            request.GET.get("brand", ""), int(request.GET.get("system_type", "")),
            int(request.GET.get("hours", "")),
        )
    except ValueError:
        system = None
    if not system:
        messages.error(request, tr("請先選擇有效的品牌、系統和耐火時間。"))
        return redirect("calculator")
    with_prices = show_prices(request)
    area, _ = parse_area(request.GET.get("area", ""))
    result = services.calculate(system, include_prices=with_prices, area=area)
    content = build_calc_xlsx(result, user=request.user.get_username(), show_prices=with_prices, t=tr)
    kind = "price" if with_prices else "material"
    filename = (f"{system.brand}-{dict(FireSystem.TYPE_CHOICES)[system.system_type]}-"
                f"{system.fire_rating_hours}hr-{kind}-{result.on_date:%Y-%m-%d}.xlsx")
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------- 原料價錢 ----------

@permission_required(PRICE_VIEW_PERM, raise_exception=True)
def price_list(request):
    today = date.today()
    rows = []
    for m in Material.objects.filter(active=True):
        rows.append({"material": m, "price": m.current_price(today)})
    return render(request, "estimator/prices.html", {
        "rows": rows,
        "can_edit": request.user.has_perm("estimator.add_materialprice"),
        "can_add_material": request.user.has_perm("estimator.add_material"),
    })


@permission_required(PRICE_VIEW_PERM, raise_exception=True)
def price_history(request, pk):
    material = get_object_or_404(Material, pk=pk)
    return render(request, "estimator/price_history.html", {
        "material": material,
        "prices": material.prices.all(),
        "current": material.current_price(),
        "can_edit": request.user.has_perm("estimator.add_materialprice"),
    })


@permission_required("estimator.add_materialprice", raise_exception=True)
def price_add(request, pk):
    material = get_object_or_404(Material, pk=pk)
    current = material.current_price()

    if request.method == "POST":
        form = PriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.material = material
            price.updated_by = request.user.get_username()
            price.save()
            messages.success(request, tr("已更新 {m} 的價錢：${p}（{d} 起生效）",
                                         m=material, p=price.unit_price, d=price.effective_date))
            return redirect("price_list")
    else:
        form = PriceForm(initial={
            "unit_price": current.unit_price if current else None,
            "supplier": current.supplier if current else "",
            "effective_date": date.today(),
        })

    return render(request, "estimator/price_form.html", {
        "material": material, "current": current, "form": form,
    })


# ---------- 新增材料 ----------

@permission_required("estimator.add_material", raise_exception=True)
def material_add(request):
    form = MaterialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            material = form.save()
            price = form.cleaned_data.get("unit_price")
            if price is not None:
                MaterialPrice.objects.create(
                    material=material, unit_price=price,
                    supplier=form.cleaned_data.get("supplier", ""),
                    effective_date=form.cleaned_data["effective_date"],
                    note=tr("新增材料時輸入"), updated_by=request.user.get_username(),
                )
        messages.success(request, tr("已新增材料 {code} {name}", code=material.code, name=material))
        return redirect("price_history", pk=material.pk)
    return render(request, "estimator/material_form.html", {"form": form})


# ---------- Excel 批量更新價錢 ----------

def _materials_lookup():
    data = {}
    for m in Material.objects.filter(active=True):
        p = m.current_price()
        data[m.code] = (str(m), p.unit_price if p else None, p.effective_date if p else None)
    return data


@permission_required("estimator.add_materialprice", raise_exception=True)
def price_import_template(request):
    rows = []
    for m in Material.objects.filter(active=True):
        p = m.current_price()
        rows.append((m.code, localized(m.name, m.name_en), localized(m.spec, m.spec_en), m.display_unit(),
                     p.unit_price if p else None, p.supplier if p else ""))
    content = importer.build_template(rows, t=tr)
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="price-template-{date.today():%Y-%m-%d}.xlsx"'
    return resp


@permission_required("estimator.add_materialprice", raise_exception=True)
def price_import(request):
    result = None
    request.session.pop(IMPORT_SESSION_KEY, None)   # 每次上載都清除上一次的預覽
    if request.method == "POST":
        form = PriceImportForm(request.POST, request.FILES)
        if form.is_valid():
            result = importer.parse_workbook(
                form.cleaned_data["file"], _materials_lookup(),
                form.cleaned_data["default_supplier"], form.cleaned_data["default_date"], t=tr,
                header_aliases={h: all_languages(h) for h in importer.HEADERS},
            )
            request.session[IMPORT_SESSION_KEY] = [r.to_session() for r in result.valid]
    else:
        form = PriceImportForm()
    return render(request, "estimator/price_import.html", {"form": form, "result": result})


@require_POST
@permission_required("estimator.add_materialprice", raise_exception=True)
def price_import_confirm(request):
    rows = request.session.pop(IMPORT_SESSION_KEY, None)
    if not rows:
        messages.error(request, tr("沒有可儲存的資料，請重新上載。"))
        return redirect("price_import")

    user = request.user.get_username()
    materials = {m.code: m for m in Material.objects.filter(code__in=[r["code"] for r in rows])}
    created = 0
    with transaction.atomic():
        for r in rows:
            m = materials.get(r["code"])
            if not m:
                continue
            MaterialPrice.objects.create(
                material=m, unit_price=Decimal(r["new_price"]), supplier=r["supplier"],
                effective_date=date.fromisoformat(r["effective_date"]),
                note=r["note"] or tr("Excel 匯入"), updated_by=user,
            )
            created += 1
    messages.success(request, tr("已從 Excel 更新 {n} 項價錢。", n=created))
    return redirect("price_list")


# ---------- 介面語言 ----------

@require_POST
def set_language(request):
    """切換介面語言。已登入：存入帳戶；未登入（登入頁）：只存 cookie。"""
    lang = request.POST.get("language", "")
    nxt = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        nxt = "/"
    response = redirect(nxt)
    if lang in LANGUAGE_CODES:
        if request.user.is_authenticated:
            UserProfile.objects.update_or_create(user=request.user, defaults={"language": lang})
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=365 * 24 * 3600,
                            samesite="Lax")
    return response

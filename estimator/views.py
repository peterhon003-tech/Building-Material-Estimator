from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import price_import as importer
from .export import build_calc_xlsx
from . import services
from .forms import MaterialForm, PriceForm, PriceImportForm
from .models import FireSystem, Material, MaterialPrice

IMPORT_SESSION_KEY = "price_import_rows"
PRICE_VIEW_PERM = "estimator.view_materialprice"


def can_see_price(user):
    """有「查看材料價錢」權限才看到價錢（估價員、價錢管理員、超級用戶）。"""
    return user.has_perm(PRICE_VIEW_PERM)


@login_required
def calculator(request):
    brand = request.GET.get("brand", "")
    system_type = request.GET.get("system_type", "")
    hours = request.GET.get("hours", "")

    result = None
    not_available = False
    if brand and system_type and hours:
        try:
            system = services.find_system(brand, int(system_type), int(hours))
        except ValueError:
            system = None
        if system:
            result = services.calculate(system, include_prices=can_see_price(request.user))
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
        "can_see_price": can_see_price(request.user),
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
        messages.error(request, "請先選擇有效的品牌、系統和耐火時間。")
        return redirect("calculator")
    show_prices = can_see_price(request.user)
    result = services.calculate(system, include_prices=show_prices)
    content = build_calc_xlsx(result, user=request.user.get_username(), show_prices=show_prices)
    filename = (f"{system.brand}-{system.get_system_type_display()}-"
                f"{system.fire_rating_hours}hr-{result.on_date:%Y-%m-%d}.xlsx")
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
            messages.success(request, f"已更新 {material} 的價錢：${price.unit_price}（{price.effective_date} 起生效）")
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
                    note="新增材料時輸入", updated_by=request.user.get_username(),
                )
        messages.success(request, f"已新增材料 {material.code} {material}")
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
        rows.append((m.code, m.name, m.spec, m.unit,
                     p.unit_price if p else None, p.supplier if p else ""))
    content = importer.build_template(rows)
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
                form.cleaned_data["default_supplier"], form.cleaned_data["default_date"],
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
        messages.error(request, "沒有可儲存的資料，請重新上載。")
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
                note=r["note"] or "Excel 匯入", updated_by=user,
            )
            created += 1
    messages.success(request, f"已從 Excel 更新 {created} 項價錢。")
    return redirect("price_list")

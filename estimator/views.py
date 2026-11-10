import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import price_import as importer
from .export import build_calc_xlsx
from . import services
from .hooks import calculation_done
from .forms import MaterialForm, PriceForm, PriceImportForm
from .i18n import LANGUAGE_CODES, all_languages, tr
from .middleware import SESSION_KEY as LANGUAGE_SESSION_KEY
from .models import FireSystem, Material, MaterialPrice, SystemComponent

IMPORT_SESSION_KEY = "price_import_rows"

# 臨時調整功能在網頁上用到的文字（按目前語言翻譯後交給 JavaScript）
ADJUST_TEXT = {
    "adjust": "調整", "done": "完成調整", "delete": "刪除這一項",
    "reset_confirm": "還原到系統計算的結果？所有調整會被清除。",
    "manual": "手動輸入", "added": "手動新增", "tbc": "待定", "na": "待提供",
    "invalid": "有數字格式不正確（標示紅色），請修正後再匯出。",
    "item": "項目", "material": "材料 / 規格", "unit": "單位", "qty": "每 m² 用量", "price": "單價 (HK$)",
    "original": "原配方", "off_spec": "不在測試報告配方內，請確認是否符合耐火要求",
    "overwrite": "更換產品會覆蓋這一行的修改，繼續？", "choose": "選擇材料…",
}
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
    adjust_data = None
    not_available = False
    if brand and system_type and hours:
        try:
            system = services.find_system(brand, int(system_type), int(hours))
        except ValueError:
            system = None
        if system:
            result = services.calculate(system, include_prices=show_prices(request), area=area,
                                        with_options=True)
            adjust_data = services.adjust_payload(
                result, brand, system_type, hours,
                "material" if request.GET.get("view") == "material" else "price")
            # 通知附加功能（例如計價紀錄）；沒有任何接收者時甚麼都不做
            calculation_done.send(sender=None, request=request, result=result, params={
                "brand": brand, "system_type": system_type, "hours": hours, "area": area,
                "view": "material" if request.GET.get("view") == "material" else "price",
            })
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
        "adjust_data": adjust_data,
        "adjust_i18n": {k: tr(v) for k, v in ADJUST_TEXT.items()},
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
    return _xlsx_response(content, system, with_prices, result.on_date)


def _xlsx_response(content, system, with_prices, on_date, adjusted=False):
    kind = "price" if with_prices else "material"
    extra = "-adjusted" if adjusted else ""
    type_name = dict(FireSystem.TYPE_CHOICES)[system.system_type].replace(" ", "-")
    filename = (f"{system.brand}-{type_name}-"
                f"{system.fire_rating_hours}hr-{kind}{extra}-{on_date:%Y-%m-%d}.xlsx")
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_POST
@login_required
def calculator_export_adjusted(request):
    """匯出臨時調整後的結果。調整內容由網頁送來，只用於這次匯出，不會儲存。"""
    try:
        data = json.loads(request.POST.get("payload", ""))
        system = services.find_system(str(data.get("brand", "")), int(data.get("system_type")),
                                      int(data.get("hours")))
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest(tr("資料格式不正確"))
    if not system:
        return HttpResponseBadRequest(tr("請先選擇有效的品牌、系統和耐火時間。"))
    # 價錢權限由伺服器決定：沒有權限或選了「只看材料」，送來的價錢一律忽略
    with_prices = can_see_price(request.user) and data.get("view") != "material"
    area, _ = parse_area(str(data.get("area") or ""))
    try:
        result = services.adjusted_result(system, area, data.get("lines"), with_prices, t=tr)
    except ValueError as e:
        return HttpResponseBadRequest(str(e))
    content = build_calc_xlsx(result, user=request.user.get_username(), show_prices=with_prices,
                              t=tr, adjusted=True)
    return _xlsx_response(content, system, with_prices, result.on_date, adjusted=True)


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


# ---------- Excel 批量更新（價錢、新增 / 修改 / 停用材料） ----------

KNOWN_UNITS = ["張", "支", "件", "粒", "m²", "m", "米", "公斤", "kg", "套", "卷", "罐"]
ACTION_WORDS = {"新增": ["add", "new"], "停用": ["deactivate", "disable"], "更新": ["update"]}


def _import_options(request):
    """parse_workbook 用的別名表和權限。"""
    units = set(Material.objects.values_list("unit", flat=True)) | set(KNOWN_UNITS)
    unit_aliases = {}
    for u in units:
        for alias in all_languages(u) | {u}:
            key = alias.lower()
            if key in unit_aliases and unit_aliases[key] not in (u, None):
                unit_aliases[key] = None            # 不清楚（例如英文 pc 可以是「支」或「件」）
            elif key not in unit_aliases:
                unit_aliases[key] = u
    for u in units:
        unit_aliases[u.lower()] = u                 # 中文寫法一定清楚
    category_aliases = {}
    for code, zh in Material.CATEGORIES:
        category_aliases[code.lower()] = code
        for alias in all_languages(zh) | {zh}:
            category_aliases[alias.lower()] = code
    action_aliases = {}
    for action, extra in ACTION_WORDS.items():
        for alias in all_languages(action) | {action} | set(extra):
            action_aliases[alias.lower()] = "" if action == importer.ACTION_UPDATE else action
    return {
        "header_aliases": {h: all_languages(h) for h in importer.HEADERS},
        "category_aliases": category_aliases, "unit_aliases": unit_aliases, "action_aliases": action_aliases,
        "category_names": {code: tr(zh) for code, zh in Material.CATEGORIES},
        "can_add": request.user.has_perm("estimator.add_material"),
        "can_change": request.user.has_perm("estimator.change_material"),
    }


def _materials_lookup():
    """所有材料（包括已停用）的現時資料，用來比對上載的內容。"""
    used = {}
    for c in SystemComponent.objects.filter(system__active=True).select_related("system", "material"):
        label = str(c.system)
        used.setdefault(c.material.code, [])
        if label not in used[c.material.code]:
            used[c.material.code].append(label)
    data = {}
    for m in Material.objects.all():
        p = m.current_price() if m.active else None
        data[m.code] = importer.MaterialInfo(
            name=m.name, spec=m.spec, name_en=m.name_en, spec_en=m.spec_en, category=m.category,
            unit=m.unit, coverage=m.coverage, price=p.unit_price if p else None,
            price_date=p.effective_date if p else None, active=m.active, used_in=used.get(m.code, []),
            unit_names={u.lower() for u in all_languages(m.unit)})
    return data


@permission_required("estimator.add_materialprice", raise_exception=True)
def price_import_template(request):
    rows = []
    names = {code: tr(zh) for code, zh in Material.CATEGORIES}
    for m in Material.objects.filter(active=True):
        p = m.current_price()
        rows.append({
            "code": m.code, "name": m.name, "spec": m.spec, "name_en": m.name_en, "spec_en": m.spec_en,
            "category_label": names.get(m.category, m.category), "unit": m.display_unit(), "coverage": m.coverage,
            "price": p.unit_price if p else None, "price_date": p.effective_date if p else None,
            "supplier": p.supplier if p else "",
        })
    content = importer.build_template(rows, t=tr, categories=list(names.values()),
                                      actions=[tr("更新"), tr("新增"), tr("停用")])
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
                **_import_options(request),
            )
            request.session[IMPORT_SESSION_KEY] = result.to_session()
    else:
        form = PriceImportForm()
    return render(request, "estimator/price_import.html", {"form": form, "result": result})


@require_POST
@permission_required("estimator.add_materialprice", raise_exception=True)
def price_import_confirm(request):
    data = request.session.pop(IMPORT_SESSION_KEY, None)
    if isinstance(data, list):                       # 舊版本的預覽資料
        data = {"prices": data}
    if not data or not any(data.get(k) for k in ("prices", "new", "changes", "deactivate")):
        messages.error(request, tr("沒有可儲存的資料，請重新上載。"))
        return redirect("price_import")

    user = request.user.get_username()
    can_add = request.user.has_perm("estimator.add_material")
    can_change = request.user.has_perm("estimator.change_material")
    counts = {"new": 0, "changes": 0, "deactivate": 0, "prices": 0}
    skipped = []
    with transaction.atomic():
        # 1. 新增材料（先做，之後的價錢才找得到）
        for r in data.get("new", []) if can_add else []:
            if Material.objects.filter(code=r["code"]).exists():
                skipped.append(r["code"])
                continue
            f = r["fields"]
            Material.objects.create(code=r["code"], name=f["name"], spec=f["spec"], name_en=f["name_en"],
                                    spec_en=f["spec_en"], category=f["category"], unit=f["unit"],
                                    coverage=Decimal(f["coverage"]))
            counts["new"] += 1
        # 2. 修改材料資料
        allowed = {key for _, key in importer.DETAIL_FIELDS}
        for r in data.get("changes", []) if can_change else []:
            m = Material.objects.filter(code=r["code"], active=True).first()
            if not m:
                skipped.append(r["code"])
                continue
            fields = []
            for key, value in r["values"].items():
                if key in allowed:
                    setattr(m, key, Decimal(value) if key == "coverage" else value)
                    fields.append(key)
            if fields:
                m.save(update_fields=fields)
                counts["changes"] += 1
        # 3. 停用材料（再檢查一次是否仍在使用中的系統）
        for r in data.get("deactivate", []) if can_change else []:
            m = Material.objects.filter(code=r["code"], active=True).first()
            if not m or SystemComponent.objects.filter(material=m, system__active=True).exists():
                skipped.append(r["code"])
                continue
            m.active = False
            m.save(update_fields=["active"])
            counts["deactivate"] += 1
        # 4. 價錢
        materials = {m.code: m for m in Material.objects.filter(
            code__in=[r["code"] for r in data.get("prices", [])], active=True)}
        for r in data.get("prices", []):
            m = materials.get(r["code"])
            if not m:
                skipped.append(r["code"])
                continue
            MaterialPrice.objects.create(
                material=m, unit_price=Decimal(r["new_price"]), supplier=r["supplier"],
                effective_date=date.fromisoformat(r["effective_date"]),
                note=r["note"] or tr("Excel 匯入"), updated_by=user,
            )
            counts["prices"] += 1
    messages.success(request, tr("已儲存：新增材料 {a} 項、修改材料資料 {b} 項、停用材料 {c} 項、更新價錢 {d} 項。",
                                 a=counts["new"], b=counts["changes"], c=counts["deactivate"], d=counts["prices"]))
    if skipped:
        messages.warning(request, tr("以下項目在預覽後已被改動，未有儲存：{codes}", codes="、".join(sorted(set(skipped)))))
    return redirect("price_list")


# ---------- 介面語言 ----------

@require_POST
def set_language(request):
    """右上角切換語言：只維持到登出（存在 session），不改帳戶的預設語言。
    帳戶預設語言由管理員在「系統管理 → 用戶 → 用戶設定」設定。"""
    lang = request.POST.get("language", "")
    nxt = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        nxt = "/"
    response = redirect(nxt)
    if lang in LANGUAGE_CODES:
        request.session[LANGUAGE_SESSION_KEY] = lang
    return response

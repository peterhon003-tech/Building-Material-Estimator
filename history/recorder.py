"""寫入和清理計價紀錄。"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from estimator.i18n import current_language

DEDUP_MINUTES = 10


def enabled():
    return getattr(settings, "FB_CALC_HISTORY_ENABLED", True)


def keep_days():
    return int(getattr(settings, "FB_CALC_HISTORY_DAYS", 180))


def _s(v):
    return None if v is None else str(v)


def snapshot_lines(result):
    """把每一行存成文字（快照）。沒有價錢時不存任何價錢欄。"""
    rows = []
    for l in result.lines:
        row = {"item_no": l.item_no, "description": l.description, "material": l.material,
               "unit": l.unit, "qty": _s(l.qty), "total_qty": _s(l.total_qty),
               "order_qty": _s(l.order_qty), "note": l.note}
        if result.include_prices:
            row.update({"unit_price": _s(l.unit_price), "cost": _s(l.cost),
                        "total_cost": _s(l.total_cost)})
        rows.append(row)
    return rows


def purge(now=None):
    """刪除超過保留日數的紀錄，傳回刪除數目。"""
    from .models import CalcRecord
    now = now or timezone.now()
    deleted, _ = CalcRecord.objects.filter(created_at__lt=now - timedelta(days=keep_days())).delete()
    return deleted


def record(user, result, params, now=None):
    """記錄一次計價。同一用戶 10 分鐘內用相同條件再計，只更新同一筆，不另外新增。"""
    from .models import CalcRecord
    if not enabled() or not user.is_authenticated:
        return None
    now = now or timezone.now()
    system = result.system
    key = {"user": user, "brand": system.brand, "system_type": system.system_type,
           "fire_rating_hours": system.fire_rating_hours, "area": result.area,
           "view_mode": params.get("view", "price")}
    values = {
        "created_at": now, "system_label": str(system), "report_no": system.report_no,
        "include_prices": result.include_prices,
        "total_per_sqm": result.total if result.include_prices else None,
        "grand_total": result.grand_total if (result.include_prices and result.area) else None,
        "language": current_language(), "lines": snapshot_lines(result),
    }
    recent = (CalcRecord.objects.filter(**key, created_at__gte=now - timedelta(minutes=DEDUP_MINUTES))
              .order_by("-created_at").first())
    if recent:
        for k, v in values.items():
            setattr(recent, k, v)
        recent.save()
        rec = recent
    else:
        rec = CalcRecord.objects.create(**key, **values)
    purge(now)
    return rec

"""材料修改紀錄：記錄改之前 → 改之後。Excel 匯入、系統管理、新增材料頁和更新價錢頁共用。"""
from decimal import Decimal

from .i18n import tr
from .models import Material, MaterialLog

# 要記錄的欄位和顯示名稱（名稱同時是翻譯的 key）
TRACKED = [
    ("code", "編號"), ("name", "中文名稱"), ("spec", "中文規格"), ("name_en", "英文名稱"),
    ("spec_en", "英文規格"), ("category", "類別"), ("unit", "中文計價單位"), ("unit_en", "英文計價單位"),
    ("coverage", "每單位涵蓋量"), ("active", "使用中"),
]
PRICE_FIELDS = [("unit_price", "單價"), ("supplier", "供應商"), ("effective_date", "生效日期"), ("note", "備註")]
LABELS = dict(TRACKED + PRICE_FIELDS)


def _s(value):
    """儲存用的文字：數字去掉多餘的 0，是否用 True / False。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return str(value)


def snapshot(material):
    return {f: _s(getattr(material, f)) for f, _ in TRACKED}


def diff(before, after):
    return [{"field": f, "old": before.get(f, ""), "new": after.get(f, "")}
            for f, _ in TRACKED if before.get(f, "") != after.get(f, "")]


def _who(user):
    if user is not None and getattr(user, "is_authenticated", False):
        return user, user.get_username()
    return None, ""


def log(material, user, source, action, changes=None, batch=None, note=""):
    u, name = _who(user)
    return MaterialLog.objects.create(
        material=material, code=material.code, user=u, username=name, source=source, action=action,
        changes=changes or [], batch=batch, note=note[:200])


def log_created(material, user, source, batch=None, note=""):
    after = snapshot(material)
    changes = [{"field": f, "old": "", "new": after[f]} for f, _ in TRACKED if after[f] not in ("", None)]
    return log(material, user, source, MaterialLog.CREATED, changes, batch, note)


def log_changed(material, before, user, source, batch=None, note=""):
    """比較 before（snapshot）和現在；有改動才記錄。啟用 / 停用另記為對應動作。"""
    changes = diff(before, snapshot(material))
    if not changes:
        return None
    action = MaterialLog.CHANGED
    if [c["field"] for c in changes] == ["active"]:
        action = MaterialLog.REACTIVATED if material.active else MaterialLog.DEACTIVATED
    return log(material, user, source, action, changes, batch, note)


def log_price(price, user, source, batch=None, old=None):
    """新價錢。old：之前的現時價錢（MaterialPrice 或 None）。"""
    changes = []
    for f, _ in PRICE_FIELDS:
        new = _s(getattr(price, f))
        prev = _s(getattr(old, f)) if old is not None else ""
        if new != "" or prev != "":
            changes.append({"field": f, "old": prev, "new": new})
    return log(price.material, user, source, MaterialLog.PRICE, changes, batch)


def display(change):
    """給網頁顯示：(欄位名稱, 改之前, 改之後)，類別和是否都翻譯好。"""
    field = change.get("field", "")
    names = {code: tr(zh) for code, zh in Material.CATEGORIES}

    def fmt(v):
        if isinstance(v, bool):
            return tr("是") if v else tr("否")
        if field == "category":
            return names.get(v, v)
        return v if v not in ("", None) else "—"

    return tr(LABELS.get(field, field)), fmt(change.get("old")), fmt(change.get("new"))

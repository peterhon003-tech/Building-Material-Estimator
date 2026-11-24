# -*- coding: utf-8 -*-
"""設定每個系統的防火膠用量（每 m² 固定數量）。

用法（先試行，不會改動任何東西）：
  測試版（Windows 命令提示字元，在 C:\\fireboard）：
    docker compose exec -T web python manage.py shell < set_sealant_usage.py
  正式版（Ubuntu）：
    cd /opt/fireboard
    sudo docker compose exec -T web python manage.py shell < /mnt/c/fireboard/set_sealant_usage.py

看清楚列出的改動後，加 -e APPLY=1 才真正儲存：
    docker compose exec -T -e APPLY=1 web python manage.py shell < set_sealant_usage.py

規則（來源：sealant.pdf）：
  天花 (Enclosure for Ceiling)        Hilti CP 606 0.68  Promaseal-A 0.65 支/m²
  煤氣喉 (Enclosure for Gas Pipe)     Hilti CP 606 0.96  Promaseal-A 0.93 支/m²
  間牆 (Partition Promina / Promat-H) Hilti CP 606 1.36  Promaseal-A 1.3  支/m²
1. 已有防火膠（材料類別 = 膠）的組件：計算方式改為「固定數量」，每 m² 固定數量按上表；
   不會更換材料，損耗 % 不變。
2. 天花和煤氣喉系統如果沒有防火膠組件：新增一行，材料 Hilti CP 606 白色（FS-CP-606W），
   固定數量 0.68（天花）／0.96（煤氣喉），損耗 0%，圖例編號 = 該系統最大編號 + 1。
"""
import os
from decimal import Decimal

from django.db import transaction

from estimator.models import FireSystem, Material, SystemComponent

APPLY = os.environ.get("APPLY") == "1"

HILTI = {"FS-CP-606W", "FS-CP-606G"}
PROMASEAL = {"FS-PRMS-A", "SL-PROMASEAL-A"}
# system_type: 1 天花, 3 煤氣喉, 2/4 間牆
USAGE = {
    "hilti": {1: Decimal("0.68"), 3: Decimal("0.96"), 2: Decimal("1.36"), 4: Decimal("1.36")},
    "promaseal": {1: Decimal("0.65"), 3: Decimal("0.93"), 2: Decimal("1.3"), 4: Decimal("1.3")},
}


def product(code):
    if code in HILTI:
        return "hilti"
    if code in PROMASEAL:
        return "promaseal"
    return None


rows = (SystemComponent.objects.select_related("system", "material")
        .filter(material__category="SEALANT").order_by("system__system_type", "system__id", "item_no"))

changes, skipped = [], []
for c in rows:
    kind = product(c.material.code)
    target = USAGE.get(kind, {}).get(c.system.system_type)
    label = f"{c.system} | 項目 {c.item_no} | {c.material.code}"
    if target is None:
        skipped.append(f"{label}：不認識這款膠或這類系統，不改")
        continue
    if c.method == "FIXED" and c.fixed_qty_per_sqm == target:
        skipped.append(f"{label}：已經是 固定數量 {target}，不用改")
        continue
    changes.append((c, target, f"{label}：{c.get_method_display()} {c.fixed_qty_per_sqm} → 固定數量 {target}"))
    if c.formula.strip():
        skipped.append(f"{label}：[注意] 有自訂公式「{c.formula}」，它會蓋過固定數量，請在系統管理檢查")

# ---------- 2. 天花／煤氣喉系統：新增防火膠組件 ----------
NEW_CODE = "FS-CP-606W"
new_material = Material.objects.filter(code=NEW_CODE).first()
additions = []
for system in FireSystem.objects.filter(system_type__in=(1, 3)).order_by("system_type", "id"):
    if system.components.filter(material__category="SEALANT").exists():
        continue
    if new_material is None:
        skipped.append(f"{system}：沒有防火膠，但找不到材料 {NEW_CODE}，請先匯入 Excel")
        continue
    qty = USAGE["hilti"][system.system_type]
    last = system.components.order_by("-item_no").values_list("item_no", flat=True).first() or 0
    additions.append((system, last + 1, qty,
                      f"{system} | 新增項目 {last + 1} | {NEW_CODE}：固定數量 {qty}"))

print("========== 防火膠用量 ==========")
print("模式：" + ("儲存改動" if APPLY else "試行（不會儲存）"))
print(f"\n會改動 {len(changes)} 個組件：")
for _, _, text in changes:
    print("  " + text)
print(f"\n會新增 {len(additions)} 個組件：")
for _, _, _, text in additions:
    print("  " + text)
print(f"\n不改 / 注意 {len(skipped)} 項：")
for text in skipped:
    print("  " + text)

if APPLY and (changes or additions):
    from estimator.activity_log import record
    with transaction.atomic():
        for c, target, text in changes:
            c.method = "FIXED"
            c.fixed_qty_per_sqm = target
            c.save(update_fields=["method", "fixed_qty_per_sqm"])
            record("admin_change", None, username="set_sealant_usage",
                   detail=f"防火膠用量（腳本）：{text}")
        for system, item_no, qty, text in additions:
            SystemComponent.objects.create(
                system=system, item_no=item_no, description="防火膠", description_en="Firestop sealant",
                material=new_material, method="FIXED", layers=1, fixed_qty_per_sqm=qty, wastage_pct=0)
            record("admin_add", None, username="set_sealant_usage",
                   detail=f"防火膠用量（腳本）：{text}")
    print(f"\n[完成] 已修改 {len(changes)} 個、新增 {len(additions)} 個組件。也記錄在「系統管理 → 使用紀錄」。")
elif changes or additions:
    print("\n未儲存。確認無誤後，加 -e APPLY=1 再執行一次。")
else:
    print("\n沒有需要改動的組件。")

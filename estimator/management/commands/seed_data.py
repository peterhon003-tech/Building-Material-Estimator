"""載入初始材料、價錢和系統配方，並建立「價錢管理員」群組。

只會新增缺少的資料，不會覆蓋已修改的內容，所以每次啟動執行也安全。
"""
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from estimator.models import FireSystem, Material, MaterialPrice, SystemComponent
from estimator.seed import COMPONENTS_EN, DRAWING, MATERIALS, MATERIALS_EN, NOTES_EN, SYSTEMS

ESTIMATOR_GROUP = "估價員"
ESTIMATOR_PERMS = ["view_material", "view_materialprice"]
PRICE_MANAGER_GROUP = "價錢管理員"
PRICE_MANAGER_PERMS = ["view_material", "add_material", "view_materialprice", "add_materialprice"]


def _dec(v):
    return None if v is None else Decimal(v)


class Command(BaseCommand):
    help = "載入初始材料、價錢、系統配方（只新增，不覆蓋）"

    @transaction.atomic
    def handle(self, *args, **options):
        materials = {}
        new_m = new_p = 0
        for code, name, spec, cat, unit, coverage, source, price in MATERIALS:
            m, created = Material.objects.get_or_create(
                code=code,
                defaults={"name": name, "spec": spec, "category": cat, "unit": unit,
                          "coverage": Decimal(coverage)},
            )
            new_m += created
            materials[code] = m
            if source and price and not m.prices.exists():
                supplier, eff, note = source
                MaterialPrice.objects.create(
                    material=m, supplier=supplier, unit_price=Decimal(price),
                    effective_date=eff, note=note, updated_by="seed_data",
                )
                new_p += 1

        new_s = 0
        for spec in SYSTEMS:
            system, created = FireSystem.objects.get_or_create(
                brand=spec["brand"], system_type=spec["system_type"],
                fire_rating_hours=spec["fire_rating_hours"],
                defaults={"frr_label": spec["frr_label"], "report_no": spec["report_no"],
                          "overall_thickness_mm": spec["overall_thickness_mm"],
                          "drawing_ref": DRAWING},
            )
            if not created:
                continue
            new_s += 1
            for item, desc, mcode, method, layers, spacing, fixed, waste, note in spec["components"]:
                SystemComponent.objects.create(
                    system=system, item_no=item, description=desc, material=materials[mcode],
                    method=method, layers=layers, spacing_m=_dec(spacing),
                    fixed_qty_per_sqm=_dec(fixed), wastage_pct=Decimal(waste), note=note,
                )

        # 英文名稱：只填空白的欄位，不覆蓋管理員已修改的內容
        new_en = 0
        for code, (name_en, spec_en) in MATERIALS_EN.items():
            m = Material.objects.filter(code=code).first()
            if not m:
                continue
            changed = []
            if name_en and not m.name_en:
                m.name_en = name_en
                changed.append("name_en")
            if spec_en and not m.spec_en:
                m.spec_en = spec_en
                changed.append("spec_en")
            if changed:
                m.save(update_fields=changed)
                new_en += 1
        for c in SystemComponent.objects.all():
            changed = []
            if not c.description_en and c.description in COMPONENTS_EN:
                c.description_en = COMPONENTS_EN[c.description]
                changed.append("description_en")
            if not c.note_en and c.note in NOTES_EN:
                c.note_en = NOTES_EN[c.note]
                changed.append("note_en")
            if changed:
                c.save(update_fields=changed)
                new_en += 1

        for name, perms in [(ESTIMATOR_GROUP, ESTIMATOR_PERMS),
                            (PRICE_MANAGER_GROUP, PRICE_MANAGER_PERMS)]:
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.add(*Permission.objects.filter(
                content_type__app_label="estimator", codename__in=perms))

        if options.get("verbosity", 1) > 0:
            self.stdout.write(self.style.SUCCESS(
                f"seed_data 完成：新增材料 {new_m}、價錢 {new_p}、系統 {new_s}、補上英文 {new_en} 項"))

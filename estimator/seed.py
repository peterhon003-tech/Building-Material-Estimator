"""初始數據：來自供應商報價單及 Easy Smart Promat Enclosure System 圖則（01-03-2024）。

標記「待定」的項目（角鐵、螺絲、螺栓每 m² 數量，以及螺絲、螺栓、人工價錢）
文件內沒有資料，需要工程同事確認後在 admin 或價錢頁輸入。
"""
from datetime import date

BOARD_SHEET_M2 = "2.9768"   # 1.22 m × 2.44 m
STEEL_LENGTH_M = "2.44"     # 8 尺
ROCKWOOL_PC_M2 = "0.72"     # 1.2 m × 0.6 m

WINTECH = ("WinTech Century", date(2026, 3, 13), "報價單 WTCFD260278，有效至 2026 年底")
KINCHEONG = ("建昌五金", date(2025, 1, 7), "報價單 2025-01-07 生效")
WARWICK = ("Warwick Building Material", date(2022, 2, 14), "TANDA Rockwool 價目表 2022-02-14")

# (編號, 名稱, 規格, 類別, 單位, 每單位涵蓋量, 價錢來源, 單價)
MATERIALS = [
    ("PRM60-09", "Promina 60", "9mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "288.00"),
    ("PRM60-12", "Promina 60", "12mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "390.00"),
    ("PTH-09", "Promatect-H", "9mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "350.00"),
    ("PTH-12", "Promatect-H", "12mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "465.00"),
    ("PTH-15", "Promatect-H", "15mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "585.00"),
    ("PTH-20", "Promatect-H", "20mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "760.00"),
    ("PTH-25", "Promatect-H", "25mm", "BOARD", "張", BOARD_SHEET_M2, WINTECH, "930.00"),

    ("CH-30x50x30x0.6", "G.I. 槽鐵", "30×50×30×0.6mm × 8尺", "CHANNEL", "支", STEEL_LENGTH_M, KINCHEONG, "10.50"),
    ("CH-50x50x50x0.8", "G.I. 槽鐵", "50×50×50×0.8mm × 8尺", "CHANNEL", "支", STEEL_LENGTH_M, KINCHEONG, "18.00"),
    ("CH-100x50x100x1.0", "G.I. 槽鐵", "100×50×100×1.0mm × 8尺", "CHANNEL", "支", STEEL_LENGTH_M, KINCHEONG, "33.00"),

    ("AG-50x50x0.6", "G.I. 角鐵", "50×50×0.6mm × 8尺", "ANGLE", "支", STEEL_LENGTH_M, KINCHEONG, "9.00"),
    ("AG-50x50x0.8", "G.I. 角鐵", "50×50×0.8mm × 8尺", "ANGLE", "支", STEEL_LENGTH_M, KINCHEONG, "11.00"),
    ("AG-50x50x1.0", "G.I. 角鐵", "50×50×1.0mm × 8尺", "ANGLE", "支", STEEL_LENGTH_M, KINCHEONG, "14.50"),
    ("AG-50x50x2.0", "G.I. 角鐵", "50×50×2.0mm × 8尺", "ANGLE", "支", STEEL_LENGTH_M, KINCHEONG, "33.00"),

    ("RW-R60-50", "TANDA 岩棉 R60", "50mm 60kg/m³ (1200×600)", "ROCKWOOL", "件", ROCKWOOL_PC_M2, WARWICK, "21.00"),
    ("RW-R100-50", "TANDA 岩棉 R100", "50mm 100kg/m³ (1200×600)", "ROCKWOOL", "件", ROCKWOOL_PC_M2, WARWICK, "30.00"),

    ("FX-M4-SCREW", "M4 自攻螺絲", "", "FIXING", "粒", "1", None, None),
    ("FX-M8-ANCHOR", "M8 膨脹螺栓", "", "FIXING", "粒", "1", None, None),
    ("LB-ENCL", "Enclosure 安裝人工", "", "LABOUR", "m²", "1", None, None),
]

DRAWING = "Easy Smart F.R.R. -/60/60, -/120/120 & -/240/240 Promat Enclosure System (01-03-2024)"
WASTE = "10"  # 暫定損耗 %，待確認

# 圖例編號沿用圖則：1 板、2 槽鐵、3 連牆角鐵、4 連板角鐵、5 岩棉、6 螺絲、7 膨脹螺栓
# 元組：(圖例編號, 項目, 材料編號, 計算方式, 層數, 間距 m, 每 m² 固定數量, 損耗 %, 備註)
SYSTEMS = [
    {
        "brand": "PROMAT", "system_type": 1, "fire_rating_hours": 1,
        "frr_label": "-/60/60", "report_no": "R23D34-1A", "overall_thickness_mm": 60,
        "components": [
            (1, "Promat 板", "PRM60-09", "AREA", 1, None, None, WASTE, ""),
            (2, "G.I. 槽鐵", "CH-30x50x30x0.6", "SPACING", 1, "1.220", None, WASTE, "@1220mm c/c"),
            (3, "連牆角鐵", "AG-50x50x0.6", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (4, "連板角鐵", "AG-50x50x0.6", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (5, "岩棉", "RW-R60-50", "AREA", 1, None, None, WASTE, "50mm × 60kg/m³"),
            (6, "M4 自攻螺絲", "FX-M4-SCREW", "FIXED", 1, None, None, "0", "@200mm c/c，每 m² 數量待定"),
            (7, "M8 膨脹螺栓", "FX-M8-ANCHOR", "FIXED", 1, None, None, "0", "@ max 500mm c/c，每 m² 數量待定"),
            (8, "安裝人工", "LB-ENCL", "FIXED", 1, None, "1", "0", "人工價待定"),
        ],
    },
    {
        "brand": "PROMAT", "system_type": 1, "fire_rating_hours": 2,
        "frr_label": "-/120/120", "report_no": "R23J17-1A", "overall_thickness_mm": 60,
        "components": [
            (1, "Promat 板", "PTH-09", "AREA", 1, None, None, WASTE, ""),
            (2, "G.I. 槽鐵", "CH-50x50x50x0.8", "SPACING", 1, "0.610", None, WASTE, "@610mm c/c"),
            (3, "連牆角鐵", "AG-50x50x1.0", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (4, "連板角鐵", "AG-50x50x0.8", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (5, "岩棉", "RW-R60-50", "AREA", 1, None, None, WASTE, "50mm × 60kg/m³"),
            (6, "M4 自攻螺絲", "FX-M4-SCREW", "FIXED", 1, None, None, "0", "@200mm c/c，每 m² 數量待定"),
            (7, "M8 膨脹螺栓", "FX-M8-ANCHOR", "FIXED", 1, None, None, "0", "@ max 600mm c/c，每 m² 數量待定"),
            (8, "安裝人工", "LB-ENCL", "FIXED", 1, None, "1", "0", "人工價待定"),
        ],
    },
    {
        "brand": "PROMAT", "system_type": 1, "fire_rating_hours": 4,
        "frr_label": "-/240/240", "report_no": "R22C10-1A Issue 1", "overall_thickness_mm": 120,
        "components": [
            (1, "Promat 板", "PTH-20", "AREA", 1, None, None, WASTE, ""),
            (2, "G.I. 槽鐵", "CH-100x50x100x1.0", "SPACING", 1, "0.610", None, WASTE, "@610mm c/c；報價單寫 1.0×50×100×50，請確認規格"),
            (3, "連牆角鐵", "AG-50x50x2.0", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (4, "連板角鐵", "AG-50x50x1.0", "FIXED", 1, None, None, WASTE, "每 m² 數量待定"),
            (5, "岩棉", "RW-R100-50", "AREA", 2, None, None, WASTE, "2 × 50mm × 100kg/m³"),
            (6, "M4 自攻螺絲", "FX-M4-SCREW", "FIXED", 1, None, None, "0", "@200mm c/c，每 m² 數量待定"),
            (7, "M8 膨脹螺栓", "FX-M8-ANCHOR", "FIXED", 1, None, None, "0", "@ max 500mm c/c，每 m² 數量待定"),
            (8, "安裝人工", "LB-ENCL", "FIXED", 1, None, "1", "0", "人工價待定"),
        ],
    },
]


# ---------- 英文名稱（英文介面用；簡體會自動由繁體轉換）----------
# 材料編號 → (英文名稱, 英文規格)。留空 = 和中文相同
MATERIALS_EN = {
    "CH-30x50x30x0.6": ("G.I. channel", "30×50×30×0.6mm × 8 ft"),
    "CH-50x50x50x0.8": ("G.I. channel", "50×50×50×0.8mm × 8 ft"),
    "CH-100x50x100x1.0": ("G.I. channel", "100×50×100×1.0mm × 8 ft"),
    "AG-50x50x0.6": ("G.I. angle", "50×50×0.6mm × 8 ft"),
    "AG-50x50x0.8": ("G.I. angle", "50×50×0.8mm × 8 ft"),
    "AG-50x50x1.0": ("G.I. angle", "50×50×1.0mm × 8 ft"),
    "AG-50x50x2.0": ("G.I. angle", "50×50×2.0mm × 8 ft"),
    "RW-R60-50": ("TANDA rockwool R60", ""),
    "RW-R100-50": ("TANDA rockwool R100", ""),
    "FX-M4-SCREW": ("M4 self-tapping screw", ""),
    "FX-M8-ANCHOR": ("M8 expansion anchor bolt", ""),
    "LB-ENCL": ("Enclosure installation labour", ""),
}

# 組件項目（中文）→ 英文
COMPONENTS_EN = {
    "Promat 板": "Promat board",
    "G.I. 槽鐵": "G.I. channel",
    "連牆角鐵": "Wall angle",
    "連板角鐵": "Board angle",
    "岩棉": "Rockwool",
    "M4 自攻螺絲": "M4 self-tapping screw",
    "M8 膨脹螺栓": "M8 expansion anchor bolt",
    "安裝人工": "Installation labour",
}

# 組件備註（中文）→ 英文
NOTES_EN = {
    "@1220mm c/c": "@1220mm c/c",
    "@610mm c/c": "@610mm c/c",
    "每 m² 數量待定": "Quantity per m² to be confirmed",
    "50mm × 60kg/m³": "50mm × 60kg/m³",
    "2 × 50mm × 100kg/m³": "2 × 50mm × 100kg/m³",
    "@200mm c/c，每 m² 數量待定": "@200mm c/c, quantity per m² to be confirmed",
    "@ max 500mm c/c，每 m² 數量待定": "@ max 500mm c/c, quantity per m² to be confirmed",
    "@ max 600mm c/c，每 m² 數量待定": "@ max 600mm c/c, quantity per m² to be confirmed",
    "人工價待定": "Labour rate to be confirmed",
    "@610mm c/c；報價單寫 1.0×50×100×50，請確認規格":
        "@610mm c/c; quotation shows 1.0×50×100×50, please confirm the size",
}

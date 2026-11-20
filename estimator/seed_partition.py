"""Partition 系統的初始配方和 stud 表（seed_data 啟動時建立，只新增缺少的系統，不覆蓋已修改的內容）。

來源：
- Promina：RED 評估報告 R21M15-2A（2 小時），Promat 圖則 1008b/22-P
- Promatect-H 2 小時：RED 評估報告 R22F02-1A，Promat 圖則 1019a/22-P
- Promatect-H 4 小時：RED 評估報告 R22F02-2A，Promat 圖則 1019b/22-P
1 小時沒有測試報告：材料按 2 小時規格，人工用 1 小時價錢（用戶確認）。

報告前後不一致的地方，用較保守的數值（用戶確認 / 已告知）：
- R21M15-2A 200 N/mm²、牆高 6000mm：第 6 頁 1.0mm，圖則 1.5mm → 用 1.5mm
- R22F02-2A 200 N/mm²、150×50×1.5mm：第 7 頁 7200mm，圖則 7.0m → 用 7000mm

所需材料（未有就不建立該系統，請先匯入）：PRM60-09、PTH-09、RW-R100-40、RW-R100-50、FX-M4-SCREW、
FX-M6-ANCHOR、SL-PROMASEAL-A、LB-PART-1/2/4，及最少一款槽鐵（STUD_DEFAULT，只在找不到合用 stud 時作佔位）。
"""
PROMINA, PROMAT_H = 4, 2
WASTE = "10"
STUD_DEFAULT = "CH-50x50x50x0.8"
SEALANT = "SL-PROMASEAL-A"
# M4 自攻螺絲每 m² 粒數（按報告間距估算，用戶確認）：
#   2 小時：stud 每 m² 1 ÷ 0.61 = 1.64m，@200mm → 8.2 粒/面，兩面 16.4
#   4 小時：內層 @400 → 4.1、外層 @200 → 8.2、外層板邊（橫縫每 m² 1 ÷ 2.44 = 0.41m）@250 → 1.6；
#           每面 13.9，兩面 27.9
SCREWS_2HR = "16.4"
SCREWS_4HR = "27.9"

PROMINA_REPORT = "R21M15-2A"
PROMAT_H_2HR_REPORT = "R22F02-1A"
PROMAT_H_4HR_REPORT = "R22F02-2A"

# ---------- stud 表：(屈服強度, web, flange, 厚度, 最高牆高 mm) ----------

def _by_thickness(stress, thicknesses, rows):
    """報告的「每種厚度最高牆高」表 → 規則清單。rows：[(web, flange, [高度 或 None, ...])]"""
    out = []
    for web, flange, heights in rows:
        for t, h in zip(thicknesses, heights):
            if h:
                out.append((stress, web, flange, t, h))
    return out


# Promina（報告按牆高列出所需 stud）
PROMINA_RULES = [
    (350, "50", "38", "0.6", 3300), (350, "75", "50", "0.8", 4000), (350, "75", "50", "1.2", 5000),
    (350, "100", "50", "1.5", 6000), (350, "100", "50", "2.5", 7000),
    (200, "50", "38", "0.8", 3100), (200, "75", "50", "0.8", 4000), (200, "75", "50", "1.2", 5000),
    (200, "100", "50", "1.5", 6000), (200, "100", "50", "2.5", 7000),
]
PROMINA_HEIGHTS = {"350": [3300, 4000, 5000, 6000, 7000], "200": [3100, 4000, 5000, 6000, 7000]}

_T2 = ["0.6", "0.8", "1.0", "1.2", "1.5", "2.0", "2.5", "3.0"]
PROMAT_H_2HR_RULES = (
    _by_thickness(350, _T2, [
        ("75", "50", [4500, 4800, 5100, 5400, 5700, 6000, 6200, 6400]),
        ("100", "50", [5600, 6000, 6300, 6600, 6900, 7200, 7500, 7700]),
    ])
    + _by_thickness(200, _T2, [
        ("75", "50", [4200, 4500, 4800, 5000, 5300, 5600, 5800, 6000]),
        ("100", "50", [5200, 5600, 5900, 6100, 6400, 6800, 7000, 7200]),
        ("150", "50", [6900, 7100, 7300, 7500, 7700, None, None, None]),
    ])
)

_T4 = ["0.8", "1.0", "1.2", "1.5", "2.0", "2.5", "3.0"]
PROMAT_H_4HR_RULES = (
    _by_thickness(350, _T4, [
        ("100", "50", [4700, 5100, 5300, 5600, 6000, 6300, 6500]),
        ("150", "50", [6400, 6700, 7000, 7400, 7700, None, None]),
    ])
    + _by_thickness(200, _T4, [
        ("100", "50", [4600, 4900, 5200, 5400, 5600, 5900, 6400]),
        ("150", "50", [6200, 6400, 6800, 7000, 7600, 7700, None]),
    ])
)

# 報告 Table 4.1.3 的高度（Promat-H 的牆高選項）
PROMAT_H_HEIGHTS = {"350": [3000, 4000, 5000, 6000, 7000, 7700], "200": [3000, 4000, 5000, 6000, 7000, 7700]}

# ---------- 配方 ----------
# (圖例編號, 項目, 英文項目, 材料編號, 計算方式, 層數, 間距 m, 每 m² 固定數量, 損耗 %, 備註, 英文備註)
# 蓋縫板條：100mm 闊；2 小時兩面直縫每 1.22m 一條 = 2 × 0.1 ÷ 1.22 = 0.1639 m²/m² ÷ 2.9768 m²/張 = 0.0551 張
#           4 小時內層橫縫每 2.44m 一條（兩面）= 2 × 0.1 ÷ 2.44 = 0.0820 m²/m² ÷ 2.9768 = 0.0275 張

def _two_hour(board, board_desc, board_desc_en, labour):
    return [
        (1, board_desc, board_desc_en, board, "AREA", 2, None, None, WASTE,
         "每面 1 層 9mm", "1 layer of 9mm each side"),
        (2, "蓋縫板條", "Cover strip", board, "FIXED", 1, None, "0.0551", WASTE,
         "100mm 闊，兩面直縫：約 0.164 m² 板/m²", "100mm wide at vertical joints, both sides: approx. 0.164 m² board/m²"),
        (3, "岩棉", "Rockwool", "RW-R100-40", "AREA", 2, None, None, WASTE,
         "報告最少 75mm × 100kg/m³：用 2 × 40mm", "Report min. 75mm × 100kg/m³: 2 × 40mm used"),
        (4, "Stud（直槽）", "Stud", STUD_DEFAULT, "STUD", 1, "0.610", None, WASTE,
         "@610mm c/c", "@610mm c/c"),
        (5, "頂底槽", "Top & bottom track", STUD_DEFAULT, "TRACK", 1, None, None, WASTE, "", ""),
        (6, "M6 膨脹螺栓", "M6 expansion anchor", "FX-M6-ANCHOR", "ANCHOR", 1, "0.500", None, "0",
         "頂底槽 @500mm c/c", "Top & bottom track @500mm c/c"),
        (7, "M4 自攻螺絲", "M4 self-tapping screw", "FX-M4-SCREW", "FIXED", 1, None, SCREWS_2HR, "0",
         "@200mm 沿 stud：每面 1 ÷ 0.61 ÷ 0.2 = 8.2 粒/m²，兩面 16.4 粒",
         "@200mm along studs: 1 ÷ 0.61 ÷ 0.2 = 8.2 nos/m² per side, 16.4 nos both sides"),
        (8, "PROMASEAL-A 防火膠", "PROMASEAL-A sealant", SEALANT, "FIXED", 1, None, None, "0",
         "封邊位，每 m² 數量待定", "Perimeter gaps; quantity per m² to be confirmed"),
        (9, "安裝人工", "Installation labour", labour, "FIXED", 1, None, "1", "0", "", ""),
    ]


def _four_hour(labour):
    return [
        (1, "Promatect-H 板", "Promatect-H board", "PTH-09", "AREA", 4, None, None, WASTE,
         "每面 2 層 9mm", "2 layers of 9mm each side"),
        (2, "岩棉", "Rockwool", "RW-R100-50", "AREA", 2, None, None, WASTE,
         "2 × 50mm × 100kg/m³", "2 × 50mm × 100kg/m³"),
        (3, "Stud（直槽）", "Stud", STUD_DEFAULT, "STUD", 1, "0.610", None, WASTE, "@610mm c/c", "@610mm c/c"),
        (4, "頂底槽", "Top & bottom track", STUD_DEFAULT, "TRACK", 1, None, None, WASTE, "", ""),
        (5, "M6 膨脹螺栓", "M6 expansion anchor", "FX-M6-ANCHOR", "ANCHOR", 1, "0.600", None, "0",
         "頂底槽 @600mm c/c", "Top & bottom track @600mm c/c"),
        (6, "M4 自攻螺絲", "M4 self-tapping screw", "FX-M4-SCREW", "FIXED", 1, None, SCREWS_4HR, "0",
         "每面：內層 @400 沿 stud 4.1 + 外層 @200 沿 stud 8.2 + 外層板邊 @250 約 1.6 = 13.9 粒/m²，兩面 27.9 粒",
         "Per side: inner @400 along studs 4.1 + outer @200 along studs 8.2 + outer board edges @250 approx. 1.6 "
         "= 13.9 nos/m²; both sides 27.9 nos"),
        (9, "PROMASEAL-A 防火膠", "PROMASEAL-A sealant", SEALANT, "FIXED", 1, None, None, "0",
         "封邊位，每 m² 數量待定", "Perimeter gaps; quantity per m² to be confirmed"),
        (10, "蓋縫板條", "Cover strip", "PTH-09", "FIXED", 1, None, "0.0275", WASTE,
         "100mm 闊，內層橫縫：約 0.082 m² 板/m²", "100mm wide at inner-layer horizontal joints: approx. 0.082 m² board/m²"),
        (11, "安裝人工", "Installation labour", labour, "FIXED", 1, None, "1", "0", "", ""),
    ]


ONE_HOUR_NOTE = "1 小時沒有測試報告：材料按 2 小時規格（{report}），人工按 1 小時價錢。"

PARTITIONS = [
    {"brand": "PROMAT", "system_type": PROMINA, "fire_rating_hours": 1, "frr_label": "-/60/60",
     "report_no": f"{PROMINA_REPORT}（按 2 小時）", "drawing_ref": "Promat 1008b/22-P（按 2 小時）",
     "notes": ONE_HOUR_NOTE.format(report=PROMINA_REPORT),
     "rules": PROMINA_RULES, "heights": PROMINA_HEIGHTS,
     "components": _two_hour("PRM60-09", "Promina 60 板", "Promina 60 board", "LB-PART-1")},
    {"brand": "PROMAT", "system_type": PROMINA, "fire_rating_hours": 2, "frr_label": "-/120/120",
     "report_no": PROMINA_REPORT, "drawing_ref": "Promat 1008b/22-P", "notes": "",
     "rules": PROMINA_RULES, "heights": PROMINA_HEIGHTS,
     "components": _two_hour("PRM60-09", "Promina 60 板", "Promina 60 board", "LB-PART-2")},
    {"brand": "PROMAT", "system_type": PROMAT_H, "fire_rating_hours": 1, "frr_label": "-/60/60",
     "report_no": f"{PROMAT_H_2HR_REPORT}（按 2 小時）", "drawing_ref": "Promat 1019a/22-P（按 2 小時）",
     "notes": ONE_HOUR_NOTE.format(report=PROMAT_H_2HR_REPORT),
     "rules": PROMAT_H_2HR_RULES, "heights": PROMAT_H_HEIGHTS,
     "components": _two_hour("PTH-09", "Promatect-H 板", "Promatect-H board", "LB-PART-1")},
    {"brand": "PROMAT", "system_type": PROMAT_H, "fire_rating_hours": 2, "frr_label": "-/120/120",
     "report_no": PROMAT_H_2HR_REPORT, "drawing_ref": "Promat 1019a/22-P", "notes": "",
     "rules": PROMAT_H_2HR_RULES, "heights": PROMAT_H_HEIGHTS,
     "components": _two_hour("PTH-09", "Promatect-H 板", "Promatect-H board", "LB-PART-2")},
    {"brand": "PROMAT", "system_type": PROMAT_H, "fire_rating_hours": 4, "frr_label": "-/240/240",
     "report_no": PROMAT_H_4HR_REPORT, "drawing_ref": "Promat 1019b/22-P", "notes": "",
     "rules": PROMAT_H_4HR_RULES, "heights": PROMAT_H_HEIGHTS,
     "components": _four_hour("LB-PART-4")},
]


def required_codes(spec):
    return sorted({c[3] for c in spec["components"]})

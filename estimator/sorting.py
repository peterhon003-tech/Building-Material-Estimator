"""多重排序（有分頁的列表，由伺服器排序）。

網址參數 sort=鍵1,-鍵2,…：按鍵1 升序，再按鍵2 降序……（「-」= 降序）。
網頁上按欄位標題排序，Shift+按加入下一層；由 templates/includes/multisort.html 的 JavaScript 產生網址。
沒有分頁的表格（原料價錢、計價明細）直接在瀏覽器排序，不經這裡。
"""
from django.db.models import F

PARAM = "sort"
MAX_LEVELS = 5


def parse(value, allowed):
    """「time,-code」→ [("time", False), ("code", True)]；不認識或重複的鍵會略過。"""
    specs, seen = [], set()
    for part in (value or "").split(","):
        part = part.strip()
        key = part.lstrip("-")
        if key and key in allowed and key not in seen:
            specs.append((key, part.startswith("-")))
            seen.add(key)
    return specs[:MAX_LEVELS]


def to_param(specs):
    return ",".join(("-" if desc else "") + key for key, desc in specs)


def apply(qs, request, fields, default):
    """按網址的 sort 參數排序。

    fields：{鍵: 欄位名稱或表達式，或它們的 tuple（同一方向按多個欄位排）}。只有列出的鍵可以排序，
    所以沒有權限看的欄位（例如價錢）不要放進來。
    default：沒有 sort 參數時的 order_by。
    傳回 (排好的 queryset, 實際使用的 sort 參數字串)。空值一律排在最後。
    """
    specs = parse(request.GET.get(PARAM, ""), fields)
    if not specs:
        return qs.order_by(*default), ""
    order = []
    for key, desc in specs:
        exprs = fields[key] if isinstance(fields[key], (tuple, list)) else (fields[key],)
        for expr in exprs:
            expr = F(expr) if isinstance(expr, str) else expr
            order.append(expr.desc(nulls_last=True) if desc else expr.asc(nulls_last=True))
    order.append("-pk")                      # 次序完全相同時固定次序，分頁才不會重複或遺漏
    return qs.order_by(*order), to_param(specs)

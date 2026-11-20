"""組件的計算公式（不依賴 Django，方便測試）。

每個組件有一條「預設公式」（按計算方式），管理員可以在系統管理填「自訂公式」取代。
公式計出的是「每 m² 用量」（以材料的計價單位計，例如張、支、件、粒、m²）。

可用變數（中文）：
  層數          組件的層數
  涵蓋量        材料每單位的面積（m²）或長度（m），即材料的「每單位涵蓋量」
  間距          組件的間距 c/c（m）；Stud 未填時用 0.61
  每平方米數量  組件的「每 m² 固定數量」
  損耗          組件的損耗 %（例如 10 即 10%）
  牆高          Partition 的牆高（m）；其他系統沒有這個變數
可用符號：+ - × ÷ * / ( )，及 最大(a, b)、最小(a, b)。

安全：只容許上述變數、數字和運算，不會執行任何其他程式碼。
"""
import ast
from decimal import Decimal, DivisionByZero, InvalidOperation

from . import calc

# 中文變數 → 內部名稱（長的放前面，避免「每平方米數量」被部分取代）
VARIABLES = {
    "每平方米數量": "fixed",
    "涵蓋量": "coverage",
    "層數": "layers",
    "間距": "spacing",
    "損耗": "wastage",
    "牆高": "height",
}
DISPLAY_ORDER = ["層數", "涵蓋量", "間距", "每平方米數量", "損耗", "牆高"]
FUNCTIONS = {"最大": "max_", "最小": "min_"}
_SYMBOLS = {"×": "*", "÷": "/", "（": "(", "）": ")", "，": ",", "＋": "+", "－": "-", "＊": "*", "／": "/"}

DEFAULT = {
    calc.AREA: "層數 ÷ 涵蓋量 × (1 + 損耗 ÷ 100)",
    calc.SPACING: "1 ÷ 間距 ÷ 涵蓋量 × (1 + 損耗 ÷ 100)",
    calc.FIXED: "每平方米數量 × (1 + 損耗 ÷ 100)",
    calc.STUD: "1 ÷ 間距 ÷ 涵蓋量 × (1 + 損耗 ÷ 100)",
    calc.TRACK: "2 ÷ 牆高 ÷ 涵蓋量 × (1 + 損耗 ÷ 100)",
    calc.ANCHOR: "2 ÷ 間距 ÷ 牆高 × (1 + 損耗 ÷ 100)",
}


class FormulaError(ValueError):
    pass


def default_for(method):
    return DEFAULT.get(method, "")


def _translate(text):
    s = text or ""
    for k, v in _SYMBOLS.items():
        s = s.replace(k, v)
    for k, v in FUNCTIONS.items():
        s = s.replace(k, v)
    for k, v in VARIABLES.items():
        s = s.replace(k, v)
    return s.strip()


def _parse(text):
    src = _translate(text)
    if not src:
        raise FormulaError("公式是空白的。")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise FormulaError("公式格式不正確，請檢查括號和符號。")
    allowed_names = set(VARIABLES.values())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
                             ast.Div, ast.USub, ast.UAdd, ast.Load)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name) and (node.id in allowed_names or node.id in FUNCTIONS.values()):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FUNCTIONS.values() and len(node.args) == 2 and not node.keywords:
            continue
        if isinstance(node, ast.Name):
            raise FormulaError(f"不認識「{_back(node.id)}」。可用變數：{'、'.join(DISPLAY_ORDER)}。")
        raise FormulaError("公式只可以用數字、變數、+ - × ÷ ( ) 和 最大()、最小()。")
    # 函數名稱不可以單獨當作變數使用
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FUNCTIONS.values():
            parent_ok = any(isinstance(p, ast.Call) and p.func is node for p in ast.walk(tree))
            if not parent_ok:
                raise FormulaError("最大、最小 要寫成 最大(a, b)。")
    return tree


def _back(name):
    for k, v in {**VARIABLES, **FUNCTIONS}.items():
        if v == name:
            return k
    return name


def variables_used(text):
    """公式用到的中文變數（按 VARIABLES 次序）。"""
    tree = _parse(text)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return [k for k in DISPLAY_ORDER if VARIABLES[k] in names]


class _Missing(Exception):
    pass


def _eval(node, values):
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        v = values.get(node.id)
        if v is None:
            raise _Missing(node.id)
        return Decimal(str(v))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, values), _eval(node.right, values)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return a / b
    if isinstance(node, ast.Call):
        a, b = (_eval(x, values) for x in node.args)
        return max(a, b) if node.func.id == "max_" else min(a, b)
    raise FormulaError("公式不正確。")


def evaluate(text, values):
    """計算公式。values 的鍵是中文變數名稱。用到的變數沒有數值（None）或除以 0 → 傳回 None（待定）。"""
    tree = _parse(text)
    inner = {VARIABLES[k]: v for k, v in values.items() if k in VARIABLES}
    try:
        return _eval(tree, inner)
    except (_Missing, DivisionByZero, InvalidOperation, ZeroDivisionError):
        return None


def validate(text, allow_height=True):
    """檢查公式；有問題傳回錯誤訊息，沒有問題傳回 ""。"""
    try:
        used = variables_used(text)
    except FormulaError as e:
        return str(e)
    if not allow_height and "牆高" in used:
        return "只有 Partition 系統才可以用「牆高」。"
    sample = {k: Decimal("1.5") for k in VARIABLES}
    if evaluate(text, sample) is None:
        return "公式計算時出錯（例如除以 0），請檢查。"
    return ""

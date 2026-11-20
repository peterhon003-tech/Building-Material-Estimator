"""組件的計算公式（不依賴 Django，方便測試）。

每個組件有一條「預設公式」（按計算方式），管理員可以在系統管理填「自訂公式」取代。
公式計出的是「每 m² 用量」（以材料的計價單位計，例如張、支、件、粒、m²）。

寫法和一般數學算式一樣：
  符號      + 加、- 減、* 乘、/ 除、^ 次方、% 百分比、( ) 括號；空格可有可無
            例如 3^2 = 9、10% = 0.1、損耗% = 損耗 ÷ 100
  次序      先括號，再 %，再 ^（由右至左，2^3^2 = 2^9），再 * /，最後 + -；同級由左至右
            -3^2 = -9（和一般數學一樣，先計次方）
  數字      例如 2、0.61、100
  函數      最大(a, b)、最小(a, b)
  變數（中文繁體、簡體或英文都可以，英文不分大小寫）
    層數 layers              組件的層數
    涵蓋量 coverage          材料每單位的面積（m²）或長度（m），即材料的「每單位涵蓋量」
    間距 spacing             組件的間距 c/c（m）；Stud 未填時用 0.61
    每平方米數量 qty_per_m2  組件的「每 m² 固定數量」
    損耗 wastage             組件的損耗 %（例如 10 即 10%）
    牆高 height              Partition 的牆高（m）；其他系統沒有這個變數
  函數英文寫法：max(a, b)、min(a, b)
  × 和 ÷ 也接受（舊公式照用），但英文字母 x 不當作乘號。

安全：公式由本模組自己逐字解讀，只認上述符號、數字、變數和函數，不會執行任何程式碼。
"""
import re
import unicodedata
from decimal import Decimal

from . import calc

# 內部名稱 → 中文變數；DISPLAY_ORDER 是列出變數的次序
VARIABLES = {
    "每平方米數量": "fixed",
    "涵蓋量": "coverage",
    "層數": "layers",
    "間距": "spacing",
    "損耗": "wastage",
    "牆高": "height",
}
DISPLAY_ORDER = ["層數", "涵蓋量", "間距", "每平方米數量", "損耗", "牆高"]
# 簡體寫法也接受
_ALIASES = {"每平方米数量": "每平方米數量", "涵盖量": "涵蓋量", "层数": "層數", "间距": "間距",
            "损耗": "損耗", "墙高": "牆高"}
FUNCTIONS = {"最大": "max", "最小": "min"}
# 英文名稱（顯示用第一個）；輸入時不分大小寫
ENGLISH = {"層數": "layers", "涵蓋量": "coverage", "間距": "spacing", "每平方米數量": "qty_per_m2",
           "損耗": "wastage", "牆高": "height", "最大": "max", "最小": "min"}
_EN_INPUT = {**{v: k for k, v in ENGLISH.items()}, "qty_per_sqm": "每平方米數量"}
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_OPERATORS = {"+": "+", "-": "-", "*": "*", "/": "/", "×": "*", "÷": "/", "(": "(", ")": ")", ",": ",",
              "^": "^", "%": "%"}

DEFAULT = {
    calc.AREA: "層數 / 涵蓋量 * (1 + 損耗 / 100)",
    calc.SPACING: "1 / 間距 / 涵蓋量 * (1 + 損耗 / 100)",
    calc.FIXED: "每平方米數量 * (1 + 損耗 / 100)",
    calc.STUD: "1 / 間距 / 涵蓋量 * (1 + 損耗 / 100)",
    calc.TRACK: "2 / 牆高 / 涵蓋量 * (1 + 損耗 / 100)",
    calc.ANCHOR: "2 / 間距 / 牆高 * (1 + 損耗 / 100)",
}


class FormulaError(ValueError):
    """template 是固定的中文句子（可翻譯），kwargs 填入 {名稱}。"""

    def __init__(self, template, **kwargs):
        self.template, self.kwargs = template, kwargs
        super().__init__(template.format(**kwargs) if kwargs else template)


def default_for(method):
    return DEFAULT.get(method, "")


# ---------- 逐字解讀（tokenize） ----------

_NAMES = sorted(list(VARIABLES) + list(_ALIASES) + list(FUNCTIONS), key=len, reverse=True)


def _tokens(text):
    """把公式切成 (種類, 值)：num / var / func / op。"""
    s = unicodedata.normalize("NFKC", text or "")      # 全形數字、括號、逗號 → 半形
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < len(s) and s[i + 1].isdigit()):
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] == "."):
                j += 1
            raw = s[i:j]
            if raw.count(".") > 1:
                raise FormulaError("數字「{n}」不正確。", n=raw)
            out.append(("num", Decimal(raw)))
            i = j
            continue
        if ch in _OPERATORS:
            out.append(("op", _OPERATORS[ch]))
            i += 1
            continue
        word = _WORD.match(s, i)
        if word:
            raw = word.group()
            name = _EN_INPUT.get(raw.lower())
            if name is None:
                if _looks_like_x(raw):
                    raise FormulaError("不認識「{w}」。乘號請用 *，除號請用 /。", w=raw)
                raise FormulaError("不認識「{w}」。可用變數：層數、涵蓋量、間距、每平方米數量、損耗、牆高。", w=raw)
            out.append(("func", (name, raw)) if name in FUNCTIONS else ("var", name))
            i = word.end()
            continue
        name = next((n for n in _NAMES if s.startswith(n, i)), None)
        if name:
            if name in FUNCTIONS:
                out.append(("func", (name, name)))
            else:
                out.append(("var", _ALIASES.get(name, name)))
            i += len(name)
            continue
        # 不認識：取到下一個符號或空格為止，方便在訊息中顯示
        j = i
        while j < len(s) and not s[j].isspace() and s[j] not in _OPERATORS and not _WORD.match(s, j) \
                and not any(s.startswith(n, j) for n in _NAMES):
            j += 1
        bad = s[i:j] or ch
        raise FormulaError("不認識「{w}」。可用變數：層數、涵蓋量、間距、每平方米數量、損耗、牆高。", w=bad)
    if not out:
        raise FormulaError("公式是空白的。")
    return out


def _looks_like_x(word):
    """例如 x、x2、layersx2：把 x 當作乘號寫錯了。"""
    parts = word.lower().split("x")
    return len(parts) > 1 and all(p == "" or p.isdigit() or p in _EN_INPUT for p in parts)


def localize(text, english):
    """顯示用：english=True 把中文變數 / 函數換成英文；否則把英文換成中文（繁體）。計法不變。"""
    text = text or ""
    if english:
        for name in sorted(list(ENGLISH) + list(_ALIASES), key=len, reverse=True):
            text = text.replace(name, ENGLISH[_ALIASES.get(name, name)])
        return text
    return _WORD.sub(lambda m: _EN_INPUT.get(m.group().lower(), m.group()), text)


# ---------- 文法（先括號，再 * /，最後 + -） ----------

class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, value, message, **kwargs):
        kind, v = self.take()
        if kind != "op" or v != value:
            raise FormulaError(message, **kwargs)

    def parse(self):
        node = self.expr()
        if self.i < len(self.t):
            kind, v = self.peek()
            if kind == "op" and v == ")":
                raise FormulaError("括號不配對：多了「)」。")
            raise FormulaError("公式中間缺少運算符號（+ - * /）。")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.factor())
        return node

    def factor(self):
        kind, v = self.peek()
        if kind == "op" and v in ("+", "-"):
            self.take()
            inner = self.factor()
            return ("neg", inner) if v == "-" else inner
        return self.power()

    def power(self):
        """a ^ b：由右至左；指數可以有正負號，例如 2^-1。"""
        node = self.postfix()
        if self.peek() == ("op", "^"):
            self.take()
            node = ("bin", "^", node, self.factor())
        return node

    def postfix(self):
        """a%：即 a ÷ 100。"""
        node = self.primary()
        while self.peek() == ("op", "%"):
            self.take()
            node = ("pct", node)
        return node

    def primary(self):
        kind, v = self.take()
        if kind == "num":
            return ("num", v)
        if kind == "var":
            return ("var", v)
        if kind == "func":
            name, raw = v
            self.expect("(", "{f} 要寫成 {f}(a, b)。", f=raw)
            a = self.expr()
            self.expect(",", "{f} 要有兩個數，用逗號分隔：{f}(a, b)。", f=raw)
            b = self.expr()
            self.expect(")", "括號不配對：缺少「)」。")
            return ("call", FUNCTIONS[name], a, b)
        if kind == "op" and v == "(":
            node = self.expr()
            self.expect(")", "括號不配對：缺少「)」。")
            return node
        if kind is None:
            raise FormulaError("公式不完整：最後缺少數字或變數。")
        if v == ")":
            raise FormulaError("括號內是空的，或多了「)」。")
        raise FormulaError("「{s}」前面缺少數字或變數。", s=v)


def _parse(text):
    return _Parser(_tokens(text)).parse()


def variables_used(text):
    """公式用到的中文變數（按 DISPLAY_ORDER 次序）。"""
    found = {v for kind, v in _tokens(text) if kind == "var"}
    _parse(text)                                   # 同時檢查文法
    return [k for k in DISPLAY_ORDER if k in found]


class _Missing(Exception):
    pass


def _eval(node, values):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "var":
        v = values.get(node[1])
        if v is None:
            raise _Missing(node[1])
        return Decimal(str(v))
    if kind == "neg":
        return -_eval(node[1], values)
    if kind == "pct":
        return _eval(node[1], values) / 100
    if kind == "call":
        a, b = _eval(node[2], values), _eval(node[3], values)
        return max(a, b) if node[1] == "max" else min(a, b)
    _, op, left, right = node
    a, b = _eval(left, values), _eval(right, values)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "^":
        if a == 0 and b < 0:
            raise ZeroDivisionError
        if b == b.to_integral_value() and abs(b) <= 1000:
            return a ** int(b)                     # 整數次方：準確
        return a ** b                               # 例如 4^0.5 = 2；負數的小數次方 → 計不到
    if b == 0:
        raise ZeroDivisionError
    return a / b


def evaluate(text, values):
    """計算公式。values 的鍵是中文變數名稱。用到的變數沒有數值（None）或除以 0 → 傳回 None（待定）。"""
    tree = _parse(text)
    try:
        result = _eval(tree, values)
        return result if result.is_finite() else None
    except (_Missing, ArithmeticError):
        return None


def check(text, allow_height=True):
    """檢查公式；沒有問題傳回 None，有問題傳回 (句子範本, 填入值)，方便翻譯。"""
    try:
        used = variables_used(text)
    except FormulaError as e:
        return e.template, e.kwargs
    if not allow_height and "牆高" in used:
        return "只有 Partition 系統才可以用「牆高」。", {}
    sample = {k: Decimal("1.5") for k in VARIABLES}
    if evaluate(text, sample) is None:
        return "公式計算時出錯（例如除以 0），請檢查。", {}
    return None


def validate(text, allow_height=True):
    """檢查公式；有問題傳回錯誤訊息（中文），沒有問題傳回 ""。"""
    problem = check(text, allow_height)
    if not problem:
        return ""
    template, kwargs = problem
    return template.format(**kwargs) if kwargs else template

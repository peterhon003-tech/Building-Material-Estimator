"""三語介面：繁體中文（原文）、簡體中文（自動轉換）、英文（對照表）。

- 程式和網頁裡所有文字都用繁體中文寫，經 tr() 顯示：
    繁體 → 原文
    簡體 → 用 OpenCC 由繁體自動轉換，不用另外維護
    英文 → 查 translations_en.EN 對照表；找不到就顯示繁體原文
- 數據庫內容（材料名稱、項目、備註）用 localized()：英文欄有填就用英文，簡體同樣自動轉換。
"""
from functools import lru_cache

from django.utils import translation
from django.utils.functional import lazy

from .translations_en import EN

ZH_HANT = "zh-hant"
ZH_HANS = "zh-hans"
EN_CODE = "en"
LANGUAGES = [
    (ZH_HANT, "繁體中文"),
    (ZH_HANS, "简体中文"),
    (EN_CODE, "English"),
]
LANGUAGE_CODES = {code for code, _ in LANGUAGES}

_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        try:
            from opencc import OpenCC
            _converter = OpenCC("t2s")
        except Exception:          # 未安裝 opencc 時，簡體顯示繁體
            _converter = False
    return _converter


@lru_cache(maxsize=4096)
def to_simplified(text):
    conv = _get_converter()
    return conv.convert(text) if conv else text


def current_language():
    lang = (translation.get_language() or ZH_HANT).lower()
    if lang.startswith("en"):
        return EN_CODE
    if lang in ("zh-hans", "zh-cn", "zh-sg"):
        return ZH_HANS
    return ZH_HANT


def tr(text, lang=None, **kwargs):
    """翻譯一段繁體中文。kwargs 用來填入 {名稱} 位置，例如 tr("共 {n} 項", n=3)。"""
    if text is None:
        return ""
    text = str(text)
    lang = lang or current_language()
    if lang == EN_CODE:
        out = EN.get(text, text)
    elif lang == ZH_HANS:
        out = to_simplified(text)
    else:
        out = text
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            out = text.format(**kwargs)
    return out


# 延遲翻譯：用於 model 欄位名稱、選項等，在顯示時才按當時語言翻譯
tl = lazy(tr, str)


def localized(text_zh, text_en="", lang=None):
    """數據庫內容：英文介面優先用英文欄，未填就用繁體；簡體自動轉換。"""
    lang = lang or current_language()
    if lang == EN_CODE:
        return text_en or text_zh or ""
    if lang == ZH_HANS:
        return to_simplified(text_zh or "")
    return text_zh or ""


def all_languages(text):
    """一段文字在三種語言的寫法，例如 Excel 匯入時辨認任何語言的欄名。"""
    return {tr(text, lang) for lang in LANGUAGE_CODES}

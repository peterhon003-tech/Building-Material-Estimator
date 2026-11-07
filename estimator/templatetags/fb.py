"""範本翻譯：{% load fb %}

    {% t "計價" %}                     → 按目前語言顯示
    {% t "以下 {n} 項用量待定：" n=3 %}  → 填入變數
    {{ value|t }}                      → 翻譯變數內容（例如計價單位「張」）
"""
from django import template

from ..i18n import LANGUAGES, current_language, tr

register = template.Library()


@register.simple_tag(name="t")
def t_tag(text, **kwargs):
    return tr(text, **kwargs)


@register.filter(name="t")
def t_filter(value):
    return tr(value)


@register.simple_tag
def language_choices():
    return LANGUAGES


@register.simple_tag
def lang_code():
    return current_language()

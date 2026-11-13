from datetime import date

from django import forms

from .i18n import tl
from .models import Material, MaterialPrice


class PriceForm(forms.ModelForm):
    class Meta:
        model = MaterialPrice
        fields = ["unit_price", "supplier", "effective_date", "note"]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_unit_price(self):
        value = self.cleaned_data["unit_price"]
        if value < 0:
            raise forms.ValidationError(tl("單價不可以是負數。"))
        return value


class MaterialForm(forms.ModelForm):
    """新增材料，可同時輸入第一個價錢。"""

    unit_price = forms.DecimalField(
        label=tl("單價 (HK$)"), required=False, min_value=0, max_digits=12, decimal_places=2,
        help_text=tl("可留空，之後再在「原料價錢」頁輸入"),
    )
    supplier = forms.CharField(label=tl("供應商"), required=False, max_length=100)
    effective_date = forms.DateField(
        label=tl("生效日期"), required=False, initial=date.today,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = Material
        fields = ["code", "name", "spec", "name_en", "spec_en", "category", "unit", "unit_en", "coverage"]
        help_texts = {
            "code": tl("不可重複，例如 PTH-30、AG-50x50x1.5"),
            "coverage": tl("板：每張面積 m²（1220×2440 = 2.9768）；鐵料：每支長度 m（8 尺 = 2.44）；"
                           "岩棉：每件面積 m²（1200×600 = 0.72）；其他填 1"),
        }

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean_coverage(self):
        value = self.cleaned_data["coverage"]
        if value is None or value <= 0:
            raise forms.ValidationError(tl("每單位涵蓋量必須大於 0。"))
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("unit_price") is not None and not cleaned.get("effective_date"):
            self.add_error("effective_date", tl("有輸入單價時，請填寫生效日期。"))
        return cleaned


class PriceImportForm(forms.Form):
    MAX_BYTES = 5 * 1024 * 1024

    file = forms.FileField(label=tl("Excel 檔案 (.xlsx)"))
    default_supplier = forms.CharField(
        label=tl("預設供應商"), required=False, max_length=100,
        help_text=tl("Excel「供應商」欄留空、而材料未有現時供應商時（例如新材料）用這個值"),
    )
    default_date = forms.DateField(
        label=tl("預設生效日期"), initial=date.today,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text=tl("Excel「生效日期」欄留空的行會用這個日期"),
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(tl("請上載 .xlsx 格式的 Excel 檔。"))
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError(tl("檔案太大（上限 5 MB）。"))
        return f

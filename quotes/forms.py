from django import forms

from .models import Quotation


class QuotationForm(forms.ModelForm):
    class Meta:
        model = Quotation
        fields = ["customer_name", "contact", "project", "remarks"]
        widgets = {
            "customer_name": forms.TextInput(attrs={"style": "width:100%"}),
            "contact": forms.TextInput(attrs={"style": "width:100%"}),
            "project": forms.Textarea(attrs={"rows": 2, "style": "width:100%"}),
            "remarks": forms.Textarea(attrs={"rows": 3, "style": "width:100%"}),
        }

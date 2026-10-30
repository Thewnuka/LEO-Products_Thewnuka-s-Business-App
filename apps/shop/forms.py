from django import forms
from django.conf import settings

from apps.accounts.forms import BootstrapFormMixin

from .services import SORTS


class ShopSearchForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, max_length=100, label="Search",
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Search tea, tea bags, sweets…"}))
    sort = forms.ChoiceField(required=False, choices=list(SORTS.items()), label="Sort by")

    def values(self):
        """(search text, sort key); invalid input falls back to defaults."""
        if not self.is_bound:
            return "", "relevant"
        self.is_valid()
        return self.cleaned_data.get("q", "") or "", self.cleaned_data.get("sort") or "relevant"


class AddToCartForm(forms.Form):
    variation = forms.IntegerField(min_value=1, error_messages={"required": "Please choose a product option."})
    quantity = forms.IntegerField(min_value=1, max_value=settings.CART_MAX_QUANTITY_PER_ITEM, initial=1,
                                  error_messages={"min_value": "Quantity must be at least 1.",
                                                  "max_value": f"You can order up to {settings.CART_MAX_QUANTITY_PER_ITEM} of one item online.",
                                                  "invalid": "Enter a whole number."})


class UpdateQuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=0, max_value=settings.CART_MAX_QUANTITY_PER_ITEM)

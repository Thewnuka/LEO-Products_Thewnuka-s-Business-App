from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.forms import BootstrapFormMixin
from apps.catalog.models import Category, ProductVariation, Unit

from .models import InventoryItem, Purchase, PurchaseLine, StockMovement, Supplier
from .services import ITEM_SORTS, MANUAL_TYPES, to_stock_quantity

T = StockMovement.Type
QTY_WIDGET = {"step": "any", "min": "0", "inputmode": "decimal"}


class UnitOptionSelect(forms.Select):
    """Adds data-measurement / data-base to unit options (used by inventory.js to filter units)."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        unit = getattr(value, "instance", None)
        if unit is not None:
            option["attrs"]["data-measurement"] = unit.measurement_type
            option["attrs"]["data-convertible"] = "1" if unit.base_quantity else "0"
        return option


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------
class InventoryItemForm(BootstrapFormMixin, forms.ModelForm):
    """Create or edit a stock record. The quantity itself is never edited here."""

    opening_quantity = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=14, decimal_places=3, label="Opening stock",
        widget=forms.NumberInput(attrs=QTY_WIDGET),
        help_text="How much you hold right now. Leave empty or 0 if none. Recorded as an “Opening stock” movement.",
    )

    class Meta:
        model = InventoryItem
        fields = ["kind", "variation", "name", "category", "stock_unit", "count_label",
                  "reorder_level", "minimum_level", "maximum_level", "allow_negative", "is_active", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "stock_unit": UnitOptionSelect,
            "reorder_level": forms.NumberInput(attrs=QTY_WIDGET),
            "minimum_level": forms.NumberInput(attrs=QTY_WIDGET),
            "maximum_level": forms.NumberInput(attrs=QTY_WIDGET),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].widget = forms.RadioSelect(choices=InventoryItem.Kind.choices, attrs={"class": "form-check-input"})
        untracked = ProductVariation.objects.filter(inventory_item__isnull=True).select_related("product", "unit")
        self.fields["variation"].queryset = untracked.order_by("product__name", "sort_order", "quantity")
        self.fields["variation"].label_from_instance = lambda v: f"{v.product.name} – {v.display_name} ({v.sku})"
        self.fields["variation"].empty_label = "Choose a product variation"
        self.fields["variation"].label = "Product variation"
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["category"].empty_label = "— No category —"
        self.fields["stock_unit"].queryset = Unit.objects.filter(is_active=True)
        self.fields["stock_unit"].label_from_instance = lambda u: f"{u.symbol} – {u.name}"
        self.fields["stock_unit"].label = "Stock unit"
        self.fields["is_active"].label = "Active"
        # Only the Owner may allow negative stock (Capability.CONFIGURE_STOCK_RULES).
        from apps.accounts.roles import Capability, has_capability

        if not has_capability(user, Capability.CONFIGURE_STOCK_RULES):
            del self.fields["allow_negative"]
        if self.instance.pk:
            # Type and link are fixed once created; opening stock is entered only at creation.
            for name in ("kind", "variation", "opening_quantity"):
                del self.fields[name]
            if self.instance.is_finished:
                for name in ("name", "category", "stock_unit"):
                    del self.fields[name]
            else:
                del self.fields["count_label"]
                if self.instance.movements.exists():
                    self.fields["stock_unit"].disabled = True
                    self.fields["stock_unit"].help_text = "Fixed because stock has been recorded in this unit."

    def clean(self):
        cleaned = super().clean()
        # (The model is not filled in yet at this point, so check the submitted values.)
        opening = cleaned.get("opening_quantity")
        if (opening and cleaned.get("kind") == InventoryItem.Kind.FINISHED_GOOD
                and opening != opening.to_integral_value()):
            self.add_error("opening_quantity", "Use whole packets for finished products.")
        return cleaned


class ItemFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search",
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Item, product or SKU"}))
    state = forms.ChoiceField(required=False, label="Stock status", choices=[("", "Any status"), ("ATTENTION", "Needs reorder (low or out)")]
                              + list(InventoryItem.State.choices))
    kind = forms.ChoiceField(required=False, label="Type", choices=[("", "All types")] + list(InventoryItem.Kind.choices))
    category = forms.ModelChoiceField(Category.objects.all(), required=False, empty_label="All categories")
    unit = forms.ChoiceField(required=False, label="Unit")
    active = forms.ChoiceField(required=False, label="Active", choices=[("", "Active and inactive"), ("yes", "Active only"), ("no", "Inactive only")])
    sort = forms.ChoiceField(required=False, label="Sort by", choices=[(k, v[0]) for k, v in ITEM_SORTS.items()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].choices = [("", "Any unit"), ("packets", "Packets (finished products)")] + [
            (str(u.pk), f"{u.symbol} – {u.name}") for u in Unit.objects.all()]

    def filters(self):
        if not self.is_bound:
            return {}
        self.is_valid()
        data = dict(self.cleaned_data)
        if data.get("category"):
            data["category"] = data["category"].pk
        return data


# ---------------------------------------------------------------------------
# Stock adjustments
# ---------------------------------------------------------------------------
class StockAdjustmentForm(BootstrapFormMixin, forms.Form):
    movement_type = forms.ChoiceField(label="What happened?",
                                      choices=[(t.value, t.label) for t in MANUAL_TYPES])
    direction = forms.ChoiceField(required=False, label="Direction (other adjustments)",
                                  choices=[("", "—"), ("in", "Add to stock"), ("out", "Remove from stock")])
    quantity = forms.DecimalField(min_value=Decimal("0"), max_digits=14, decimal_places=3,
                                  widget=forms.NumberInput(attrs=QTY_WIDGET),
                                  help_text="For a correction, enter the counted total you actually have.")
    unit = forms.ModelChoiceField(Unit.objects.none(), required=False, widget=UnitOptionSelect,
                                  help_text="Defaults to the stock unit.")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=500,
                             help_text="Required. Explain the change, e.g. “Broken packets found during unpacking”.")

    def __init__(self, *args, item, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        if item.is_finished:
            del self.fields["unit"]
            self.fields["quantity"].label = f"Quantity ({item.count_label})"
        else:
            self.fields["unit"].queryset = Unit.objects.filter(measurement_type=item.stock_unit.measurement_type)
            self.fields["unit"].label_from_instance = lambda u: f"{u.symbol} – {u.name}"
            self.fields["unit"].empty_label = f"{item.stock_unit.symbol} (stock unit)"

    def clean(self):
        cleaned = super().clean()
        mtype, qty, direction = cleaned.get("movement_type"), cleaned.get("quantity"), cleaned.get("direction")
        if mtype == T.OTHER and direction not in ("in", "out"):
            self.add_error("direction", "Choose whether this adds or removes stock.")
        if mtype != T.CORRECTION and qty is not None and qty <= 0:
            self.add_error("quantity", "Enter a quantity greater than zero.")
        if qty is not None and not self.errors:
            try:
                to_stock_quantity(self.item, qty, cleaned.get("unit"))
            except ValidationError as error:
                self.add_error("quantity", error)
        return cleaned


class MovementFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Item", widget=forms.TextInput(attrs={"type": "search", "placeholder": "Item or product name"}))
    movement_type = forms.ChoiceField(required=False, label="Type", choices=[("", "All types")] + list(T.choices))
    date_from = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
class SupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "registration_number", "notes", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2}),
                   "phone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].label = "Active"


class SupplierFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"type": "search", "placeholder": "Supplier, contact, phone or email"}))
    active = forms.ChoiceField(required=False, label="Status", choices=[("", "All"), ("yes", "Active"), ("no", "Inactive")])


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------
class ItemOptionSelect(forms.Select):
    """Inventory item options carry their stock unit info for inventory.js."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        item = getattr(value, "instance", None)
        if item is not None:
            option["attrs"]["data-finished"] = "1" if item.is_finished else "0"
            if not item.is_finished:
                option["attrs"]["data-measurement"] = item.stock_unit.measurement_type
                option["attrs"]["data-stock-unit"] = item.stock_unit_id
            option["attrs"]["data-count-label"] = item.count_label
        return option


class PurchaseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["supplier", "purchase_date", "invoice_number", "notes"]
        widgets = {"purchase_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Supplier.objects.filter(is_active=True)
        if self.instance.pk:
            suppliers = suppliers | Supplier.objects.filter(pk=self.instance.supplier_id)
        self.fields["supplier"].queryset = suppliers.order_by("name")
        self.fields["supplier"].empty_label = "Choose a supplier"


class PurchaseLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseLine
        fields = ["item", "quantity", "unit", "unit_cost"]
        widgets = {"item": ItemOptionSelect, "unit": UnitOptionSelect,
                   "quantity": forms.NumberInput(attrs=QTY_WIDGET),
                   "unit_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"})}
        labels = {"unit_cost": "Unit cost (LKR)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        items = InventoryItem.objects.filter(is_active=True).select_related("stock_unit", "variation__product", "variation__unit")
        if self.instance.pk:
            items = items | InventoryItem.objects.filter(pk=self.instance.item_id)
        self.fields["item"].queryset = items.order_by("kind", "name", "variation__product__name")
        self.fields["item"].label_from_instance = lambda i: i.display_name
        self.fields["item"].empty_label = "Choose an item"
        self.fields["unit"].queryset = Unit.objects.filter(is_active=True)
        self.fields["unit"].label_from_instance = lambda u: u.symbol
        self.fields["unit"].empty_label = "Stock unit"
        self.fields["unit"].required = False
        for name in ("item", "quantity", "unit", "unit_cost"):  # the page explains these once, above the lines
            self.fields[name].help_text = ""

    def clean(self):
        cleaned = super().clean()
        item, unit = cleaned.get("item"), cleaned.get("unit")
        if item and item.is_finished:
            cleaned["unit"] = None  # finished goods are counted in packets
            self.instance.unit = None
        return cleaned


class BasePurchaseLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not kept:
            raise ValidationError("Add at least one item to the purchase.")


PurchaseLineFormSet = forms.inlineformset_factory(
    Purchase, PurchaseLine, form=PurchaseLineForm, formset=BasePurchaseLineFormSet,
    extra=1, can_delete=True, min_num=0,
)


class PurchaseFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"type": "search", "placeholder": "Reference or invoice no."}))
    supplier = forms.ModelChoiceField(Supplier.objects.all(), required=False, empty_label="All suppliers")
    status = forms.ChoiceField(required=False, choices=[("", "Any status")] + list(Purchase.Status.choices))
    date_from = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def filters(self):
        if not self.is_bound:
            return {}
        self.is_valid()
        data = dict(self.cleaned_data)
        if data.get("supplier"):
            data["supplier"] = data["supplier"].pk
        return data


class CancelPurchaseForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}), max_length=500)

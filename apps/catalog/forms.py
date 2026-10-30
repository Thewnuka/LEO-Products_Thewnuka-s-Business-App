from django import forms

from apps.accounts.forms import BootstrapFormMixin

from .images import process_image
from .models import Category, MeasurementType, Product, ProductVariation, Unit
from .services import PRODUCT_SORTS


class ImageUploadMixin:
    """
    Validates and re-encodes the `image` field (see images.process_image)
    and adds a "Remove current image" checkbox when an image exists.
    """

    def _setup_image_field(self):
        field = self.fields["image"]
        field.widget = forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "class": "form-control"})
        field.help_text = "JPG, PNG or WebP, up to 5 MB. Large images are resized automatically."
        if self.instance.pk and self.instance.image:
            self.fields["remove_image"] = forms.BooleanField(required=False, label="Remove current image")

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "content_type"):  # a new upload (not the existing file)
            return process_image(image)
        return image

    def _apply_image_removal(self, obj):
        if self.cleaned_data.get("remove_image") and "image" not in self.changed_data:
            obj.image = ""


# ---------------------------------------------------------------------------
# Categories & units
# ---------------------------------------------------------------------------
class CategoryForm(BootstrapFormMixin, ImageUploadMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["parent", "name", "description", "image", "sort_order", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parents = Category.objects.main()
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["parent"].empty_label = "— None (this is a main category) —"
        self.fields["parent"].label = "Main category"
        self.fields["is_active"].label = "Active"
        self._setup_image_field()

    def save(self, commit=True):
        obj = super().save(commit=False)
        self._apply_image_removal(obj)
        if commit:
            obj.save()
        return obj


class UnitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["measurement_type", "name", "symbol", "attach_symbol", "base_quantity", "sort_order", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].label = "Active"
        if self.instance.pk and self.instance.variations.exists():
            # Changing the type would make existing variations inconsistent.
            self.fields["measurement_type"].disabled = True
            self.fields["measurement_type"].help_text = "Locked because variations already use this unit."

    def clean_symbol(self):
        return self.cleaned_data["symbol"].strip()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class SubcategorySelect(forms.Select):
    """Adds data-parent to each option so the page can filter subcategories by main category."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-parent"] = instance.parent_id
        return option


class ProductForm(BootstrapFormMixin, ImageUploadMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "subcategory", "description", "image", "status", "slug"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "subcategory": SubcategorySelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        main = Category.objects.main()
        sub = Category.objects.sub().select_related("parent")
        if self.instance.pk:  # keep inactive categories selectable if already used
            main = main.filter(is_active=True) | main.filter(pk=self.instance.category_id)
            sub = sub.filter(is_active=True) | sub.filter(pk=self.instance.subcategory_id)
        else:
            main, sub = main.filter(is_active=True), sub.filter(is_active=True)
        self.fields["category"].queryset = main.order_by("sort_order", "name")
        self.fields["subcategory"].queryset = sub.order_by("parent__sort_order", "sort_order", "name")
        self.fields["subcategory"].label_from_instance = lambda c: c.name
        self.fields["category"].empty_label = "Choose a main category"
        self.fields["subcategory"].empty_label = "— No subcategory —"
        self.fields["subcategory"].widget.attrs["data-subcategory-for"] = self["category"].auto_id
        self.fields["slug"].required = False
        if not self.instance.pk:
            self.fields["status"].choices = [(Product.Status.DRAFT, "Draft"), (Product.Status.INACTIVE, "Inactive")]
            self.fields["status"].help_text = "New products start as Draft. Activate after adding variations."
        self._setup_image_field()

    def clean_slug(self):
        from django.utils.text import slugify

        slug = slugify(self.cleaned_data.get("slug") or "")
        if slug and Product.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another product already uses this web address.")
        return slug

    def save(self, commit=True):
        obj = super().save(commit=False)
        self._apply_image_removal(obj)
        if commit:
            obj.save()
        return obj


class ProductFilterForm(BootstrapFormMixin, forms.Form):
    """Validates list filters from the URL; invalid values are simply ignored."""

    q = forms.CharField(required=False, label="Search",
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Product name or SKU"}))
    category = forms.ModelChoiceField(Category.objects.main(), required=False, empty_label="All main categories",
                                      label="Main category")
    subcategory = forms.ModelChoiceField(Category.objects.sub().select_related("parent"), required=False,
                                         empty_label="All subcategories", widget=SubcategorySelect)
    status = forms.ChoiceField(required=False, choices=[("", "Any status")] + list(Product.Status.choices))
    measurement = forms.ChoiceField(required=False, label="Measurement",
                                    choices=[("", "Any measurement")] + list(MeasurementType.choices))
    sort = forms.ChoiceField(required=False, label="Sort by",
                             choices=[(k, label) for k, (_, label) in PRODUCT_SORTS.items()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subcategory"].label_from_instance = lambda c: c.name
        self.fields["subcategory"].widget.attrs["data-subcategory-for"] = self["category"].auto_id

    def filters(self):
        """Clean values for services.filter_products. Invalid individual values are ignored."""
        data = {}
        if self.is_bound:
            self.is_valid()
            data = self.cleaned_data  # contains every field that validated on its own
        return {
            "q": data.get("q") or "",
            "category": data["category"].pk if data.get("category") else None,
            "subcategory": data["subcategory"].pk if data.get("subcategory") else None,
            "status": data.get("status") or "",
            "measurement": data.get("measurement") or "",
            "sort": data.get("sort") or "",
        }


class ProductStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Product.Status.choices)


# ---------------------------------------------------------------------------
# Variations
# ---------------------------------------------------------------------------
class UnitSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-measurement"] = instance.measurement_type
        return option


class VariationForm(BootstrapFormMixin, ImageUploadMixin, forms.ModelForm):
    class Meta:
        model = ProductVariation
        fields = ["measurement_type", "quantity", "unit", "name", "sku", "selling_price", "wholesale_price",
                  "image", "sort_order", "is_active"]
        widgets = {
            "unit": UnitSelect,
            "quantity": forms.NumberInput(attrs={"step": "any", "min": "0", "inputmode": "decimal"}),
            "selling_price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}),
            "wholesale_price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}),
        }
        labels = {"selling_price": "Selling price (LKR)", "wholesale_price": "Wholesale price (LKR)"}

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.product = product
        units = Unit.objects.active()
        if self.instance.pk:
            units = units | Unit.objects.filter(pk=self.instance.unit_id)
        self.fields["unit"].queryset = units.order_by("measurement_type", "sort_order", "symbol")
        self.fields["unit"].label_from_instance = lambda u: f"{u.symbol} – {u.name}"
        self.fields["unit"].widget.attrs["data-unit-for"] = self["measurement_type"].auto_id
        self.fields["sku"].widget.attrs.update({"style": "text-transform: uppercase", "autocomplete": "off"})
        self.fields["is_active"].label = "Active"
        self.fields["name"].label = "Variation name (optional)"
        self._setup_image_field()

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if sku and ProductVariation.objects.filter(sku__iexact=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This SKU is already used by another variation.")
        return sku

    def clean(self):
        cleaned = super().clean()
        unit, quantity = cleaned.get("unit"), cleaned.get("quantity")
        # Checked here because Django skips constraints on fields not in the form (product).
        if unit and quantity and ProductVariation.objects.filter(
            product=self.instance.product, unit=unit, quantity=quantity
        ).exclude(pk=self.instance.pk).exists():
            self.add_error("quantity", "This product already has a variation of this size.")
        selling, wholesale = cleaned.get("selling_price"), cleaned.get("wholesale_price")
        if selling and wholesale and wholesale > selling:
            self.add_error("wholesale_price", "Wholesale price cannot be higher than the selling price.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        self._apply_image_removal(obj)
        if commit:
            obj.save()
        return obj

"""
Catalogue data model.

    Category (main)            e.g. LEO TEA
      └─ Category (sub)        e.g. Black Tea
           └─ Product          e.g. Premium Black Tea
                └─ ProductVariation   e.g. 200g, SKU LEO-LT-0001-200G, LKR price
                       └─ Unit        e.g. g (weight), bags (count), pieces (piece)

Nothing here is deleted casually: categories that still hold products or
subcategories are protected, and products/variations are archived
(deactivated) instead of deleted. Future inventory and order tables will
reference ProductVariation with on_delete=PROTECT.
"""
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Upper
from django.urls import reverse

from apps.core.models import TimeStampedModel

from .images import ImageFileCleanupMixin, category_image_path, product_image_path, variation_image_path

POSITIVE_MONEY = MinValueValidator(Decimal("0.01"), "Must be greater than zero.")
POSITIVE_QUANTITY = MinValueValidator(Decimal("0.001"), "Must be greater than zero.")
# Case-insensitive here because field validators run before the SKU is upper-cased.
sku_validator = RegexValidator(
    r"^[A-Z0-9][A-Z0-9-]{1,38}[A-Z0-9]$",
    "Use 3–40 letters, digits and hyphens (no spaces), starting and ending with a letter or digit.",
    flags=re.IGNORECASE,
)


class MeasurementType(models.TextChoices):
    """How a product is measured. Units (below) are created freely within each type."""

    WEIGHT = "WEIGHT", "Weight"
    COUNT = "COUNT", "Count"  # e.g. tea bags
    PIECE = "PIECE", "Pieces"


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class CategoryQuerySet(ActiveQuerySet):
    def main(self):
        return self.filter(parent__isnull=True)

    def sub(self):
        return self.filter(parent__isnull=False)


class Category(ImageFileCleanupMixin, TimeStampedModel):
    """
    A main category (no parent) or a subcategory (parent is a main category).
    Two levels keep products' "main category + subcategory" simple and clear.
    """

    MAX_DEPTH = 2

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
        help_text="Leave empty for a main category.",
    )
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, unique=True, editable=False)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=category_image_path, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower numbers are listed first.")

    objects = CategoryQuerySet.as_manager()
    image_fields = ("image",)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]
        constraints = [
            # No duplicate names (ignoring case) under the same parent...
            models.UniqueConstraint(
                Lower("name"), "parent", name="catalog_category_unique_name_in_parent",
                violation_error_message="A category with this name already exists here.",
            ),
            # ...and among main categories (NULL parents are not compared by the rule above).
            models.UniqueConstraint(
                Lower("name"), condition=Q(parent__isnull=True), name="catalog_category_unique_main_name",
                violation_error_message="A main category with this name already exists.",
            ),
        ]

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    @property
    def is_main(self):
        return self.parent_id is None

    def get_absolute_url(self):
        return reverse("catalog:category_update", args=[self.pk])

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({"parent": "A category cannot be its own parent."})
            if self.parent.parent_id is not None:
                raise ValidationError({"parent": "Choose a main category. Subcategories cannot contain subcategories."})
            if self.pk and self.children.exists():
                raise ValidationError({"parent": "This category has subcategories, so it must stay a main category."})
        if self.pk and self.parent_id != Category.objects.filter(pk=self.pk).values_list("parent_id", flat=True).first():
            if self.main_products.exists() or self.sub_products.exists():
                raise ValidationError({"parent": "Move this category's products first; its level cannot change while it has products."})
        if self.name:
            clash = Category.objects.filter(name__iexact=self.name, parent_id=self.parent_id).exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError({"name": "A category with this name already exists here."})

    def save(self, *args, **kwargs):
        if not self.slug:
            from .services import unique_slug

            base = f"{self.parent.name}-{self.name}" if self.parent_id else self.name
            self.slug = unique_slug(Category, base)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Units of measurement
# ---------------------------------------------------------------------------
class Unit(TimeStampedModel):
    """
    A unit used for variation quantities, e.g. g, kg (weight), bags (count),
    pieces (piece). Owners and Managers can add new units at any time.
    """

    measurement_type = models.CharField(max_length=10, choices=MeasurementType.choices)
    name = models.CharField(max_length=40, help_text='Full name, e.g. "Gram" or "Tea bag".')
    symbol = models.CharField(max_length=15, help_text='Shown after the quantity, e.g. "g", "kg", "bags", "pieces".')
    attach_symbol = models.BooleanField(
        default=False,
        help_text='Write the symbol directly after the number ("200g") instead of with a space ("10 bags").',
    )
    base_quantity = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.000001"))],
        help_text="For converting between units of the same type, e.g. g = 1 and kg = 1000. "
                  "Leave empty if this unit cannot be converted (bags, pieces).",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["measurement_type", "sort_order", "symbol"]
        constraints = [
            models.UniqueConstraint(
                Lower("symbol"), "measurement_type", name="catalog_unit_unique_symbol_per_type",
                violation_error_message="This unit already exists for that measurement type.",
            ),
        ]

    def __str__(self):
        return f"{self.symbol} ({self.get_measurement_type_display()})"

    def factor_to(self, other):
        """Multiplier converting a quantity in this unit into `other`, or None if not convertible."""
        if self.pk == other.pk:
            return Decimal(1)
        if self.measurement_type != other.measurement_type or not (self.base_quantity and other.base_quantity):
            return None
        return self.base_quantity / other.base_quantity

    def format_quantity(self, quantity):
        number = format_decimal(quantity)
        return f"{number}{self.symbol}" if self.attach_symbol else f"{number} {self.symbol}"


def format_decimal(value):
    """1.500 -> "1.5", 200.000 -> "200" (no scientific notation)."""
    text = f"{Decimal(value).normalize():f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class ProductQuerySet(models.QuerySet):
    def with_variation_summary(self):
        return self.annotate(
            variation_count=models.Count("variations", distinct=True),
            active_variation_count=models.Count("variations", filter=Q(variations__is_active=True), distinct=True),
            min_price=models.Min("variations__selling_price", filter=Q(variations__is_active=True)),
            max_price=models.Max("variations__selling_price", filter=Q(variations__is_active=True)),
        )


class Product(ImageFileCleanupMixin, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True,
                            help_text="Used in web addresses. Leave empty to create it from the name.")
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="main_products",
        limit_choices_to={"parent__isnull": True}, verbose_name="main category",
    )
    subcategory = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="sub_products", null=True, blank=True,
        limit_choices_to={"parent__isnull": False},
    )
    image = models.ImageField(upload_to=product_image_path, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    objects = ProductQuerySet.as_manager()
    image_fields = ("image",)

    class Meta(TimeStampedModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        if self.category_id and not self.category.is_main:
            raise ValidationError({"category": "Choose a main category."})
        if self.subcategory_id and self.subcategory.parent_id != self.category_id:
            raise ValidationError({"subcategory": "This subcategory does not belong to the selected main category."})
        if self.status == self.Status.ACTIVE and self.pk and not self.variations.filter(is_active=True).exists():
            raise ValidationError({"status": "Add at least one active variation before making the product active."})
        if self.status == self.Status.ACTIVE and not self.pk:
            raise ValidationError({"status": "Save the product as Draft first, add its variations, then activate it."})

    def save(self, *args, **kwargs):
        from .services import unique_slug

        if not self.slug:
            self.slug = unique_slug(Product, self.name, exclude_pk=self.pk)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Variations (sizes / pack sizes) with their own SKU and prices
# ---------------------------------------------------------------------------
class ProductVariation(ImageFileCleanupMixin, TimeStampedModel):
    """
    One sellable form of a product, e.g. "200g" or "25 bags".

    Inventory (Phase 04) will attach stock records to this model; no stock
    values are stored here.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variations")
    name = models.CharField(max_length=60, blank=True,
                            help_text='Leave empty to use the size, e.g. "200g" or "25 bags".')
    measurement_type = models.CharField(max_length=10, choices=MeasurementType.choices)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, validators=[POSITIVE_QUANTITY])
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="variations")
    sku = models.CharField("SKU", max_length=40, unique=True, blank=True, validators=[sku_validator],
                           help_text="Unique stock-keeping code. Leave empty to generate one.")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[POSITIVE_MONEY],
                                        help_text="Price in LKR.")
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                          validators=[POSITIVE_MONEY], help_text="Optional, in LKR.")
    is_active = models.BooleanField(default=True)
    image = models.ImageField(upload_to=variation_image_path, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    objects = ActiveQuerySet.as_manager()
    image_fields = ("image",)

    class Meta(TimeStampedModel.Meta):
        ordering = ["product__name", "sort_order", "quantity"]
        constraints = [
            models.UniqueConstraint(Upper("sku"), name="catalog_variation_unique_sku_ci",
                                    violation_error_message="This SKU is already used."),
            models.UniqueConstraint(fields=["product", "unit", "quantity"], name="catalog_variation_unique_size",
                                    violation_error_message="This product already has a variation of that size."),
            models.CheckConstraint(condition=Q(selling_price__gt=0), name="catalog_variation_price_positive"),
            models.CheckConstraint(condition=Q(wholesale_price__isnull=True) | Q(wholesale_price__gt=0),
                                   name="catalog_variation_wholesale_positive"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="catalog_variation_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.product.name} – {self.display_name} ({self.sku})"

    @property
    def size_label(self):
        return self.unit.format_quantity(self.quantity) if self.unit_id and self.quantity else ""

    @property
    def display_name(self):
        return self.name or self.size_label

    def clean(self):
        super().clean()
        self.sku = (self.sku or "").strip().upper()
        if self.unit_id and self.measurement_type and self.unit.measurement_type != self.measurement_type:
            raise ValidationError({"unit": f"Choose a {self.get_measurement_type_display().lower()} unit."})
        # An Active product must keep at least one active variation.
        if (self.pk and not self.is_active and self.product_id
                and self.product.status == Product.Status.ACTIVE
                and not self.product.variations.filter(is_active=True).exclude(pk=self.pk).exists()):
            raise ValidationError({"is_active": "This is the product's last active variation. "
                                                "Deactivate the product first, or add another variation."})

    def save(self, *args, **kwargs):
        from .services import generate_sku

        self.sku = (self.sku or "").strip().upper()
        if not self.sku:
            with transaction.atomic():
                self.sku = generate_sku(self)
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

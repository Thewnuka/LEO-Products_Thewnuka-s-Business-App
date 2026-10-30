"""
Inventory data model.

    InventoryItem            one stock record
      ├─ kind = RAW_MATERIAL     e.g. "Unpacked Black Tea", counted in a unit (kg, g, ...)
      └─ kind = FINISHED_GOOD    one Phase 03 ProductVariation (e.g. Black Tea 200g),
                                 counted in whole packets
    StockMovement            the ledger: every change to InventoryItem.quantity,
                             append-only (never edited or deleted)
    Supplier                 who goods are bought from
    Purchase / PurchaseLine  goods bought; stock rises only when a purchase is RECEIVED

IMPORTANT: InventoryItem.quantity is never written directly. All changes go
through apps.inventory.services.record_movement(), which locks the row,
updates it atomically and writes the matching StockMovement.

Purchases record what goods cost. Operating expenses (transport, electricity,
rent...) are NOT purchases; they belong to the expenses module (Phase 08).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.urls import reverse

from apps.accounts.models import phone_validator
from apps.catalog.models import Category, ProductVariation, Unit, format_decimal
from apps.core.models import TimeStampedModel

QTY = {"max_digits": 14, "decimal_places": 3}
MONEY = {"max_digits": 14, "decimal_places": 2}
NON_NEGATIVE = MinValueValidator(Decimal("0"), "Cannot be negative.")
POSITIVE = MinValueValidator(Decimal("0.001"), "Must be greater than zero.")


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------
class InventoryItemQuerySet(models.QuerySet):
    def with_stock_status(self):
        """Adds `stock_state`: OUT, BELOW_MIN, LOW, OK or OVER (used for filters and badges)."""
        return self.annotate(
            stock_state=models.Case(
                models.When(quantity__lte=0, then=models.Value(InventoryItem.State.OUT)),
                models.When(minimum_level__gt=0, quantity__lt=F("minimum_level"), then=models.Value(InventoryItem.State.BELOW_MIN)),
                models.When(quantity__lte=F("reorder_level"), then=models.Value(InventoryItem.State.LOW)),
                models.When(maximum_level__isnull=False, quantity__gt=F("maximum_level"), then=models.Value(InventoryItem.State.OVER)),
                default=models.Value(InventoryItem.State.OK),
                output_field=models.CharField(),
            )
        )

    def needs_attention(self):
        """Active items at or below their reorder level (includes out of stock)."""
        return self.filter(is_active=True, quantity__lte=F("reorder_level"))


class InventoryItem(TimeStampedModel):
    class Kind(models.TextChoices):
        RAW_MATERIAL = "RAW", "Raw material (unpacked)"
        FINISHED_GOOD = "FINISHED", "Finished product (sellable variation)"

    class State(models.TextChoices):
        OUT = "OUT", "Out of stock"
        BELOW_MIN = "BELOW_MIN", "Below minimum"
        LOW = "LOW", "Low stock"
        OK = "OK", "In stock"
        OVER = "OVER", "Above maximum"

    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    # Finished goods: exactly one sellable variation. Raw materials: no variation.
    variation = models.OneToOneField(ProductVariation, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="inventory_item")
    name = models.CharField(max_length=150, blank=True,
                            help_text="Raw materials only, e.g. “Unpacked Black Tea”. Finished products use the product name.")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                 help_text="Raw materials only (optional). Finished products use their product's category.")
    stock_unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                   help_text="Raw materials: the unit stock is kept in, e.g. kg.")
    count_label = models.CharField(max_length=20, default="packets",
                                   help_text="Finished products: what one counted unit is called, e.g. packets, boxes.")

    quantity = models.DecimalField(**QTY, default=Decimal("0"), editable=False)
    reorder_level = models.DecimalField(**QTY, default=Decimal("0"), validators=[NON_NEGATIVE],
                                        help_text="Show a low-stock warning at or below this quantity.")
    minimum_level = models.DecimalField(**QTY, default=Decimal("0"), validators=[NON_NEGATIVE],
                                        help_text="The least stock you should ever hold.")
    maximum_level = models.DecimalField(**QTY, null=True, blank=True, validators=[NON_NEGATIVE],
                                        help_text="Optional. Warn when stock goes above this.")
    allow_negative = models.BooleanField(
        default=False, help_text="Exceptional: let stock go below zero. Only the Owner can change this.")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    last_movement_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    objects = InventoryItemQuerySet.as_manager()

    class Meta(TimeStampedModel.Meta):
        ordering = ["kind", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=0) | Q(allow_negative=True),
                                   name="inventory_item_no_negative_stock"),
            models.CheckConstraint(
                condition=(Q(kind="FINISHED", variation__isnull=False, stock_unit__isnull=True)
                           | Q(kind="RAW", variation__isnull=True, stock_unit__isnull=False)),
                name="inventory_item_kind_consistent"),
            models.UniqueConstraint(Lower("name"), condition=Q(kind="RAW"), name="inventory_item_unique_raw_name",
                                    violation_error_message="A raw material with this name already exists."),
        ]

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("inventory:item_detail", args=[self.pk])

    # ----- presentation ----------------------------------------------------
    @property
    def is_finished(self):
        return self.kind == self.Kind.FINISHED_GOOD

    @property
    def display_name(self):
        if self.is_finished and self.variation_id:
            return f"{self.variation.product.name} – {self.variation.display_name}"
        return self.name

    @property
    def unit_label(self):
        return self.count_label if self.is_finished else (self.stock_unit.symbol if self.stock_unit_id else "")

    def format_qty(self, value):
        if value is None:
            return "—"
        if self.is_finished:
            return f"{format_decimal(value)} {self.count_label}"
        return self.stock_unit.format_quantity(value) if self.stock_unit_id else format_decimal(value)

    @property
    def quantity_display(self):
        return self.format_qty(self.quantity)

    @property
    def effective_category(self):
        if self.is_finished and self.variation_id:
            return self.variation.product.subcategory or self.variation.product.category
        return self.category

    @property
    def state(self):
        q = self.quantity
        if q <= 0:
            return self.State.OUT
        if self.minimum_level > 0 and q < self.minimum_level:
            return self.State.BELOW_MIN
        if q <= self.reorder_level:
            return self.State.LOW
        if self.maximum_level is not None and q > self.maximum_level:
            return self.State.OVER
        return self.State.OK

    STOCK_FIELDS = ("quantity", "last_movement_at")

    def save(self, *args, **kwargs):
        """
        Saving an existing item never writes the stock quantity: a settings
        form loaded a minute ago must not overwrite stock that moved since.
        Quantity changes only through services.record_movement().
        """
        if not self._state.adding and kwargs.get("update_fields") is None:
            kwargs["update_fields"] = [f.name for f in self._meta.concrete_fields
                                       if not f.primary_key and f.name not in self.STOCK_FIELDS + ("created_at",)]
        super().save(*args, **kwargs)

    # ----- validation ------------------------------------------------------
    def clean(self):
        super().clean()
        errors = {}
        if self.kind == self.Kind.FINISHED_GOOD:
            if not self.variation_id:
                errors["variation"] = "Choose the product variation this stock is for."
            self.stock_unit = None
            self.name = ""
            self.category = None
        elif self.kind == self.Kind.RAW_MATERIAL:
            self.variation = None
            self.name = " ".join((self.name or "").split())
            if not self.name:
                errors["name"] = "Enter a name for the raw material."
            if not self.stock_unit_id:
                errors["stock_unit"] = "Choose the unit this stock is kept in."
            elif self.pk:
                original = InventoryItem.objects.filter(pk=self.pk).values_list("stock_unit_id", flat=True).first()
                if original and original != self.stock_unit_id and self.movements.exists():
                    errors["stock_unit"] = "The stock unit cannot change once stock has been recorded."
            if self.name and InventoryItem.objects.filter(kind=self.Kind.RAW_MATERIAL, name__iexact=self.name).exclude(pk=self.pk).exists():
                errors["name"] = "A raw material with this name already exists."
        if self.minimum_level is not None and self.reorder_level is not None and self.minimum_level > self.reorder_level:
            errors["minimum_level"] = "Minimum level cannot be higher than the reorder level."
        if self.maximum_level is not None and self.reorder_level is not None and self.maximum_level < self.reorder_level:
            errors["maximum_level"] = "Maximum level cannot be lower than the reorder level."
        if self.is_finished:
            for field in ("reorder_level", "minimum_level", "maximum_level"):
                value = getattr(self, field)
                if value is not None and value != value.to_integral_value():
                    errors[field] = f"Use whole {self.count_label}."
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Stock movement ledger (append-only)
# ---------------------------------------------------------------------------
class StockMovement(models.Model):
    class Type(models.TextChoices):
        OPENING = "OPENING", "Opening stock"
        PURCHASE = "PURCHASE", "Purchase received"
        INCREASE = "INCREASE", "Stock increase"
        DECREASE = "DECREASE", "Stock decrease"
        DAMAGE = "DAMAGE", "Damage"
        EXPIRED = "EXPIRED", "Expired stock"
        CORRECTION = "CORRECTION", "Correction (count)"
        OTHER = "OTHER", "Other adjustment"
        SALE = "SALE", "Sale (order)"                          # Phase 06: stock leaves when an order is placed
        ORDER_CANCEL = "ORDER_CANCEL", "Order cancelled (restock)"

    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    quantity_change = models.DecimalField(**QTY, help_text="Positive adds stock, negative removes it (in the item's unit).")
    quantity_before = models.DecimalField(**QTY)
    quantity_after = models.DecimalField(**QTY)
    entered_quantity = models.DecimalField(**QTY, null=True, blank=True,
                                           help_text="What the user typed, before unit conversion.")
    entered_unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True)
    purchase = models.ForeignKey("Purchase", null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    purchase_line = models.OneToOneField("PurchaseLine", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="movement")
    order_item = models.ForeignKey("orders.OrderItem", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="stock_movements")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="stock_movements")

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            # (quantity_after = quantity_before + quantity_change is guaranteed by the service using
            #  exact Decimal arithmetic; a DB check is avoided because SQLite compares decimals as floats.)
            # A purchase line can be received into stock only once.
            models.UniqueConstraint(fields=["purchase_line"], condition=Q(purchase_line__isnull=False),
                                    name="inventory_movement_one_per_purchase_line"),
            # An order line takes stock out once, and puts it back at most once.
            models.UniqueConstraint(fields=["order_item"], condition=Q(movement_type="SALE"),
                                    name="inventory_movement_one_sale_per_order_item"),
            models.UniqueConstraint(fields=["order_item"], condition=Q(movement_type="ORDER_CANCEL"),
                                    name="inventory_movement_one_restock_per_order_item"),
            # Opening stock is recorded at most once per item.
            models.UniqueConstraint(fields=["item"], condition=Q(movement_type="OPENING"),
                                    name="inventory_movement_one_opening_per_item"),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()}: {self.item} {self.quantity_change:+}"

    @property
    def is_increase(self):
        return self.quantity_change > 0

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Stock movements are permanent and cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock movements are permanent and cannot be deleted.")


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
class Supplier(TimeStampedModel):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    registration_number = models.CharField("business registration number", max_length=60, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="inventory_supplier_unique_name",
                                    violation_error_message="A supplier with this name already exists."),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("inventory:supplier_detail", args=[self.pk])

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        self.email = (self.email or "").strip().lower()
        if self.name and Supplier.objects.filter(name__iexact=self.name).exclude(pk=self.pk).exists():
            raise ValidationError({"name": "A supplier with this name already exists."})


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------
class Purchase(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    purchase_date = models.DateField()
    invoice_number = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(**MONEY, default=Decimal("0.00"), editable=False)
    total = models.DecimalField(**MONEY, default=Decimal("0.00"), editable=False,
                                help_text="Goods only. Transport and other operating costs are expenses, not purchases.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)
    received_at = models.DateTimeField(null=True, blank=True, editable=False)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", editable=False)
    cancel_reason = models.TextField(blank=True, editable=False)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-purchase_date", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(subtotal__gte=0) & Q(total__gte=0), name="inventory_purchase_totals_positive"),
        ]

    def __str__(self):
        return self.reference

    def get_absolute_url(self):
        return reverse("inventory:purchase_detail", args=[self.pk])

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    def recalculate_totals(self):
        subtotal = sum((line.line_total for line in self.lines.all()), Decimal("0.00"))
        self.subtotal = self.total = subtotal
        Purchase.objects.filter(pk=self.pk).update(subtotal=subtotal, total=subtotal)


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="purchase_lines")
    quantity = models.DecimalField(**QTY, validators=[POSITIVE])
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                             help_text="Raw materials: the unit on the invoice (converted to the stock unit). Empty for finished products.")
    unit_cost = models.DecimalField(**MONEY, validators=[NON_NEGATIVE], help_text="Cost per unit, in LKR.")
    line_total = models.DecimalField(**MONEY, editable=False)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inventory_purchase_line_qty_positive"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="inventory_purchase_line_cost_non_negative"),
        ]

    def __str__(self):
        return f"{self.item} × {self.quantity}"

    @property
    def unit_label(self):
        return self.unit.symbol if self.unit_id else self.item.count_label

    def stock_quantity(self):
        """This line's quantity expressed in the item's stock unit (raises ValidationError if impossible)."""
        from .services import to_stock_quantity

        return to_stock_quantity(self.item, self.quantity, self.unit)

    def clean(self):
        super().clean()
        if self.item_id and self.quantity:
            self.stock_quantity()  # validates unit compatibility and whole packets

    def save(self, *args, **kwargs):
        from .services import money

        self.line_total = money((self.quantity or 0) * (self.unit_cost or 0))
        super().save(*args, **kwargs)

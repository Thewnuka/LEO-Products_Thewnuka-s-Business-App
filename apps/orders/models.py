"""
Orders.

  CheckoutSettings   one row: which delivery/pickup and payment options are offered,
                     pickup details and the business bank account shown to customers
  DeliveryZone       delivery areas with their fee (and optional free-delivery amount)
  Order              one sale: an online order (number LEO-YYYY-NNNNN, channel ONLINE) or
                     an in-store POS sale (POS-YYYY-NNNNN, channel POS), with details,
                     discount and totals fixed at the time of ordering
  OrderItem          what was ordered: product/variation names, SKU and unit price are
                     COPIED so later catalogue changes never alter past orders
  OrderStatusEvent   history of every status change (who, when, why)

Stock policy: stock is deducted when the order is placed and restored if it is
cancelled (see services.py). Orders are never deleted; they are cancelled.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from apps.catalog.models import ProductVariation
from apps.core.models import TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
NON_NEGATIVE = MinValueValidator(Decimal("0"), "Cannot be negative.")


class CheckoutSettings(TimeStampedModel):
    """Single row (pk=1) edited by the Owner: Staff portal → Orders → Delivery & payment settings."""

    delivery_enabled = models.BooleanField("offer home delivery", default=True)
    pickup_enabled = models.BooleanField("offer store pickup", default=True)
    pickup_address = models.TextField(blank=True, help_text="Shown to customers who choose store pickup.")
    pickup_hours = models.CharField(max_length=200, blank=True, help_text="e.g. Mon–Sat, 9 am – 6 pm")

    cash_on_delivery_enabled = models.BooleanField("accept cash on delivery", default=True)
    cash_on_pickup_enabled = models.BooleanField("accept cash at pickup", default=True)
    bank_transfer_enabled = models.BooleanField("accept bank transfer", default=False,
                                                help_text="Only offered when the bank details below are filled in.")
    bank_name = models.CharField(max_length=120, blank=True)
    bank_branch = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    bank_instructions = models.TextField(blank=True, help_text="Extra instructions shown with the bank details.")

    class Meta:
        verbose_name = verbose_name_plural = "checkout settings"

    def __str__(self):
        return "Checkout settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1  # always the same single row
        super().save(*args, **kwargs)

    @property
    def bank_details_complete(self):
        return all([self.bank_name, self.bank_account_name, self.bank_account_number])

    @property
    def bank_transfer_available(self):
        return self.bank_transfer_enabled and self.bank_details_complete


class DeliveryZone(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True, help_text="e.g. Colombo city, Kandy district, Rest of island")
    areas = models.TextField(blank=True, help_text="Towns or areas covered, shown to customers.")
    fee = models.DecimalField(**MONEY, validators=[NON_NEGATIVE], help_text="Delivery fee in LKR.")
    free_delivery_over = models.DecimalField(
        **MONEY, null=True, blank=True, validators=[NON_NEGATIVE],
        help_text="Optional: no delivery fee when the order subtotal is at least this amount (LKR).")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [models.CheckConstraint(condition=Q(fee__gte=0), name="orders_zone_fee_non_negative")]

    def __str__(self):
        return self.name

    def fee_for(self, subtotal):
        if self.free_delivery_over is not None and subtotal >= self.free_delivery_over:
            return Decimal("0.00")
        return self.fee


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PROCESSING = "PROCESSING", "Processing"
        READY_FOR_PICKUP = "READY_FOR_PICKUP", "Ready for pickup"
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for delivery"
        DELIVERED = "DELIVERED", "Delivered"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Fulfilment(models.TextChoices):
        DELIVERY = "DELIVERY", "Home delivery"
        PICKUP = "PICKUP", "Store pickup"
        IN_STORE = "IN_STORE", "In-store sale"

    class Channel(models.TextChoices):
        ONLINE = "ONLINE", "Online shop"
        POS = "POS", "Point of sale"

    class DiscountType(models.TextChoices):
        FIXED = "FIXED", "Fixed amount (LKR)"
        PERCENT = "PERCENT", "Percentage"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        ONLINE = "ONLINE", "Online payment"

    class PaymentStatus(models.TextChoices):
        """Summary of the order's payments (the details live in payments.Payment)."""
        PENDING = "PENDING", "Awaiting payment"
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending verification"
        PAID = "PAID", "Paid"
        REFUND_DUE = "REFUND_DUE", "Refund due"
        REFUNDED = "REFUNDED", "Refunded"

    number = models.CharField(max_length=20, unique=True, editable=False)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.ONLINE, db_index=True)
    # Online orders always have a customer account; walk-in POS sales usually don't.
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="orders")
    # POS sales: who sold it, in which cashier shift
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="pos_sales")
    shift = models.ForeignKey("pos.CashierShift", null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    checkout_token = models.UUIDField(unique=True, editable=False,
                                      help_text="One per checkout; stops a double-clicked order being placed twice.")

    # Contact and fulfilment (copied at checkout)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    fulfilment = models.CharField(max_length=10, choices=Fulfilment.choices)
    delivery_zone = models.ForeignKey(DeliveryZone, null=True, blank=True, on_delete=models.PROTECT, related_name="orders")
    delivery_zone_name = models.CharField(max_length=80, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    delivery_instructions = models.TextField(blank=True)

    # Money (calculated on the server; never taken from the browser)
    subtotal = models.DecimalField(**MONEY, validators=[NON_NEGATIVE])
    # Discount (POS): total = subtotal - discount_amount + delivery_fee
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, blank=True)
    discount_value = models.DecimalField(**MONEY, default=Decimal("0.00"), validators=[NON_NEGATIVE],
                                         help_text="LKR amount or percentage, as entered.")
    discount_amount = models.DecimalField(**MONEY, default=Decimal("0.00"), validators=[NON_NEGATIVE])
    discount_reason = models.CharField(max_length=200, blank=True)
    discount_applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                            related_name="+")
    discount_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                             related_name="+")
    delivery_fee = models.DecimalField(**MONEY, default=Decimal("0.00"), validators=[NON_NEGATIVE])
    total = models.DecimalField(**MONEY, validators=[NON_NEGATIVE])

    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=22, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
                                      db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    cancel_reason = models.TextField(blank=True)
    stock_restored = models.BooleanField(default=False, editable=False)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0) & Q(subtotal__gte=0) & Q(delivery_fee__gte=0),
                                   name="orders_order_amounts_non_negative"),
            models.CheckConstraint(condition=Q(fulfilment__in=["PICKUP", "IN_STORE"], delivery_fee=0) | Q(fulfilment="DELIVERY"),
                                   name="orders_pickup_has_no_delivery_fee"),
            models.CheckConstraint(condition=Q(discount_amount__gte=0) & Q(discount_amount__lte=models.F("subtotal")),
                                   name="orders_discount_within_subtotal"),
            models.CheckConstraint(condition=Q(channel="POS") | Q(customer__isnull=False),
                                   name="orders_online_order_has_customer"),
        ]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.number])

    def get_staff_url(self):
        if self.channel == self.Channel.POS:
            return reverse("pos:sale_detail", args=[self.number])
        return reverse("orders:staff_detail", args=[self.number])

    @property
    def is_pos(self):
        return self.channel == self.Channel.POS

    @property
    def is_delivery(self):
        return self.fulfilment == self.Fulfilment.DELIVERY

    @property
    def is_open(self):
        return self.status not in (self.Status.COMPLETED, self.Status.CANCELLED)

    @property
    def is_paid(self):
        return self.payment_status == self.PaymentStatus.PAID

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    variation = models.ForeignKey(ProductVariation, on_delete=models.PROTECT, related_name="order_items")
    # Snapshot at the time of ordering
    product_name = models.CharField(max_length=120)
    variation_name = models.CharField(max_length=60)
    sku = models.CharField(max_length=40)
    unit_price = models.DecimalField(**MONEY, validators=[NON_NEGATIVE])
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    line_total = models.DecimalField(**MONEY, validators=[NON_NEGATIVE])

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="orders_item_quantity_positive"),
            models.UniqueConstraint(fields=["order", "variation"], name="orders_item_one_line_per_variation"),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.product_name} ({self.variation_name})"


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.order}: {self.from_status or '—'} → {self.to_status}"

    @property
    def to_label(self):
        return Order.Status(self.to_status).label

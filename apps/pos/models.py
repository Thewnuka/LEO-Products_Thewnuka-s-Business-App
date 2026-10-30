"""
Point of sale.

POS sales themselves are orders.Order rows with channel=POS: they reuse the
order lines (prices copied), the stock ledger (one SALE movement per line) and
payments.Payment. This app only adds what the online shop doesn't have:

  PosSettings    one row: receipt details and discount limits per role
  CashierShift   a cashier's working session at the till: opening float, closing
                 count, expected cash and the difference
  CashMovement   cash put into or taken out of the drawer (with a reason), and cash
                 refunds paid from the drawer
  ReceiptPrint   log of receipt reprints (who, when)

Shifts, cash movements and reprints are never deleted or edited after closing.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
NON_NEGATIVE = MinValueValidator(Decimal("0"), "Cannot be negative.")
PERCENT = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


class PosSettings(TimeStampedModel):
    """Single row (pk=1) edited by the Owner: Staff portal → Point of sale → POS settings."""

    business_address = models.TextField(blank=True, help_text="Printed on receipts. Leave empty to leave it off.")
    business_phone = models.CharField(max_length=40, blank=True, help_text="Printed on receipts.")
    receipt_footer = models.CharField(max_length=200, blank=True, default="Thank you for shopping with us!",
                                      help_text="Short message at the bottom of every receipt.")
    cashier_discount_limit = models.DecimalField(
        "cashier discount limit (%)", max_digits=5, decimal_places=2, default=Decimal("5.00"), validators=PERCENT,
        help_text="Largest discount a cashier may give without approval, as a % of the sale.")
    manager_discount_limit = models.DecimalField(
        "manager discount limit (%)", max_digits=5, decimal_places=2, default=Decimal("20.00"), validators=PERCENT,
        help_text="Largest discount a Manager may give or approve. The Owner has no limit.")

    class Meta:
        verbose_name = verbose_name_plural = "POS settings"

    def __str__(self):
        return "POS settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class CashierShift(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shifts")
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN, db_index=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    opening_cash = models.DecimalField(**MONEY, validators=[NON_NEGATIVE], help_text="Cash in the drawer at the start.")
    opening_note = models.CharField(max_length=200, blank=True)

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    # Fixed when the shift is closed
    expected_cash = models.DecimalField(**MONEY, null=True, blank=True)
    counted_cash = models.DecimalField(**MONEY, null=True, blank=True, validators=[NON_NEGATIVE])
    difference = models.DecimalField(**MONEY, null=True, blank=True, help_text="Counted minus expected.")
    closing_note = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-opened_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["cashier"], condition=Q(status="OPEN"), name="pos_one_open_shift_per_cashier"),
            models.CheckConstraint(condition=Q(opening_cash__gte=0), name="pos_shift_opening_cash_non_negative"),
            models.CheckConstraint(
                condition=Q(status="OPEN") | (Q(closed_at__isnull=False) & Q(counted_cash__isnull=False)
                                              & Q(expected_cash__isnull=False)),
                name="pos_closed_shift_has_count"),
        ]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"SH-{self.pk:05d}" if self.pk else "SH-new"

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


class CashMovement(models.Model):
    class Kind(models.TextChoices):
        CASH_IN = "CASH_IN", "Cash added"
        CASH_OUT = "CASH_OUT", "Cash taken out"
        REFUND = "REFUND", "Cash refund"

    shift = models.ForeignKey(CashierShift, on_delete=models.PROTECT, related_name="cash_movements")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.CharField(max_length=200)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT,
                              related_name="cash_movements", help_text="The refunded sale (refunds only).")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="pos_cash_movement_amount_positive"),
            models.UniqueConstraint(fields=["order"], condition=Q(kind="REFUND"), name="pos_one_cash_refund_per_order"),
            models.CheckConstraint(condition=Q(kind="REFUND", order__isnull=False) | ~Q(kind="REFUND"),
                                   name="pos_refund_has_order"),
        ]

    def __str__(self):
        return f"{self.shift}: {self.get_kind_display()} {self.amount}"

    @property
    def signed_amount(self):
        return self.amount if self.kind == self.Kind.CASH_IN else -self.amount


class ReceiptPrint(models.Model):
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="receipt_prints")
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    printed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["printed_at", "pk"]

    def __str__(self):
        return f"Reprint of {self.order} by {self.printed_by}"

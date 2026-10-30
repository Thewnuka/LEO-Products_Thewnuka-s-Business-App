"""
Payments.

One Payment row per payment attempt for an order. Rules (database + services):
  - at most ONE paid payment per order;
  - at most ONE open attempt (pending / pending verification) per order;
  - a status only moves forward through services.py using conditional
    updates, so double clicks and repeated gateway callbacks are harmless;
  - nothing becomes PAID by itself: cash is recorded by staff, bank transfers
    are verified by staff, online payments need a verified gateway notification.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.orders.models import Order

from .storage import evidence_upload_path, private_storage


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending verification"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REJECTED = "REJECTED", "Rejected"
        REFUNDED = "REFUNDED", "Refunded"

    OPEN_STATUSES = (Status.PENDING, Status.PENDING_VERIFICATION)

    reference = models.CharField(max_length=24, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=15, choices=Order.PaymentMethod.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, default="LKR", editable=False)
    status = models.CharField(max_length=22, choices=Status.choices, default=Status.PENDING, db_index=True)

    # Bank transfer (entered by the customer)
    bank_reference = models.CharField("transfer reference", max_length=100, blank=True)
    evidence = models.FileField(upload_to=evidence_upload_path, storage=private_storage, blank=True)
    evidence_content_type = models.CharField(max_length=40, blank=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Cash at the POS: what the customer handed over and the change given back
    cash_tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    change_given = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Online gateway
    gateway = models.CharField(max_length=30, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, help_text="Gateway or bank transaction ID.")
    gateway_status = models.CharField(max_length=40, blank=True)

    # Verification / receipt / refund (staff)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_note = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_note = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["order"], condition=Q(status="PAID"),
                                    name="payments_one_paid_payment_per_order"),
            models.UniqueConstraint(fields=["order"], condition=Q(status__in=["PENDING", "PENDING_VERIFICATION"]),
                                    name="payments_one_open_payment_per_order"),
            models.UniqueConstraint(fields=["gateway", "transaction_id"], condition=~Q(transaction_id=""),
                                    name="payments_unique_gateway_transaction"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="payments_amount_non_negative"),
            models.CheckConstraint(condition=Q(change_given__isnull=True) | Q(change_given__gte=0),
                                   name="payments_change_non_negative"),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class PaymentEvent(models.Model):
    """Append-only log of everything that happened to a payment (incl. gateway notifications)."""

    LABELS = {
        "bank_transfer_submitted": "Transfer details submitted",
        "bank_transfer_approved": "Transfer approved",
        "bank_transfer_rejected": "Transfer rejected",
        "cash_received": "Cash received",
        "refunded": "Refund recorded",
        "closed_order_cancelled": "Closed (order cancelled)",
        "online_checkout_started": "Online payment started",
        "notification_amount_mismatch": "Gateway notice ignored (wrong amount)",
        "gateway_paid": "Gateway: paid",
        "gateway_pending": "Gateway: pending",
        "gateway_failed": "Gateway: failed",
        "gateway_cancelled": "Gateway: cancelled by customer",
        "gateway_chargeback": "Gateway: chargeback",
    }

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="events")
    event = models.CharField(max_length=40)
    detail = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.payment.reference}: {self.event}"

    @property
    def label(self):
        return self.LABELS.get(self.event, self.event.replace("_", " ").capitalize())

"""
Finance.

What already exists elsewhere (and is only READ here):
  sales            orders.Order / OrderItem (online and POS), with discounts and the cost
                   of goods sold copied onto each line at the moment of sale
  money received   payments.Payment (paid_at), refunds (refunded_at)
  purchases        inventory.Purchase (goods bought; stock and average cost updated on receipt)
  stock value      inventory.InventoryItem.average_cost

What this app adds:
  ExpenseCategory  e.g. Transport, Utilities, Rent (operating costs, never stock purchases)
  Expense          one operating cost paid, with an optional receipt file (private storage)
  SupplierPayment  money paid to a supplier against received purchases (supplier balances)
  FinanceEvent     audit trail: who recorded, voided, changed or exported what

Records are never edited or deleted: a mistake is VOIDED (with a reason) and entered again.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.payments.storage import private_storage

MONEY = {"max_digits": 14, "decimal_places": 2}
POSITIVE = MinValueValidator(Decimal("0.01"), "Must be greater than zero.")


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Cash"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
    CARD = "CARD", "Card"
    CHEQUE = "CHEQUE", "Cheque"
    OTHER = "OTHER", "Other"


def receipt_upload_path(instance, filename):
    import uuid

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"expense-receipts/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["name"]
        verbose_name_plural = "expense categories"

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        raise ValidationError("Expense categories can't be deleted; make them inactive instead.")


class VoidableRecord(TimeStampedModel):
    class Status(models.TextChoices):
        RECORDED = "RECORDED", "Recorded"
        VOID = "VOID", "Void"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.RECORDED, db_index=True, editable=False)
    # One per form: a double-clicked or resubmitted form can't record the same money twice.
    submission_token = models.UUIDField(unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", editable=False)
    voided_at = models.DateTimeField(null=True, blank=True, editable=False)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+", editable=False)
    void_reason = models.CharField(max_length=300, blank=True, editable=False)

    class Meta(TimeStampedModel.Meta):
        abstract = True

    def __str__(self):
        return self.reference

    @property
    def is_void(self):
        return self.status == self.Status.VOID

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial records can't be deleted; void them instead.")


class Expense(VoidableRecord):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    expense_date = models.DateField()
    amount = models.DecimalField(**MONEY, validators=[POSITIVE])
    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    paid_to = models.CharField(max_length=150, blank=True)
    description = models.CharField(max_length=300)
    payment_reference = models.CharField(max_length=100, blank=True, help_text="Bill, invoice or transfer number.")
    receipt = models.FileField(upload_to=receipt_upload_path, storage=private_storage, blank=True)
    receipt_content_type = models.CharField(max_length=40, blank=True, editable=False)

    class Meta(VoidableRecord.Meta):
        ordering = ["-expense_date", "-pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="finance_expense_amount_positive")]


class SupplierPayment(VoidableRecord):
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.PROTECT, related_name="payments")
    purchase = models.ForeignKey("inventory.Purchase", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="supplier_payments", help_text="Optional: the purchase this pays for.")
    payment_date = models.DateField()
    amount = models.DecimalField(**MONEY, validators=[POSITIVE])
    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    payment_reference = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta(VoidableRecord.Meta):
        ordering = ["-payment_date", "-pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="finance_supplier_payment_positive")]


class FinanceEvent(models.Model):
    """Append-only audit trail of financial actions."""

    action = models.CharField(max_length=40, db_index=True)
    object_ref = models.CharField(max_length=60, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    LABELS = {
        "expense_recorded": "Expense recorded", "expense_voided": "Expense voided",
        "supplier_payment_recorded": "Supplier payment recorded", "supplier_payment_voided": "Supplier payment voided",
        "item_cost_set": "Stock cost set", "report_exported": "Report exported",
        "category_saved": "Expense category saved",
    }

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.label} {self.object_ref}"

    @property
    def label(self):
        return self.LABELS.get(self.action, self.action.replace("_", " ").capitalize())

    def delete(self, *args, **kwargs):
        raise ValidationError("The finance audit trail can't be deleted.")

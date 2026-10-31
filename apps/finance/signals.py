from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.inventory.models import ItemCostChange

from .models import Expense, ExpenseCategory, FinanceEvent, SupplierPayment


@receiver(pre_delete, sender=Expense)
@receiver(pre_delete, sender=SupplierPayment)
@receiver(pre_delete, sender=ExpenseCategory)
@receiver(pre_delete, sender=FinanceEvent)
@receiver(pre_delete, sender=ItemCostChange)
def protect_financial_records(sender, instance, **kwargs):
    """Financial records are voided, never deleted (also blocks bulk deletes)."""
    raise ValidationError("Financial records can't be deleted; void them instead.")

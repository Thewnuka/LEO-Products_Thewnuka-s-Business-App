from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import StockMovement


@receiver(pre_delete, sender=StockMovement)
def block_movement_delete(sender, instance, **kwargs):
    """The ledger is permanent, including for bulk deletes (which skip Model.delete)."""
    raise ValidationError("Stock movements are permanent and cannot be deleted.")

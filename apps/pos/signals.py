from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import CashierShift, CashMovement, ReceiptPrint


@receiver(pre_delete, sender=CashierShift)
@receiver(pre_delete, sender=CashMovement)
@receiver(pre_delete, sender=ReceiptPrint)
def protect_pos_history(sender, instance, **kwargs):
    """Shifts, drawer movements and reprint logs are audit records: never deleted."""
    raise ValidationError("Point-of-sale records cannot be deleted.")

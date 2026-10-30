from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Order, OrderItem, OrderStatusEvent


@receiver(pre_delete, sender=Order)
@receiver(pre_delete, sender=OrderItem)
@receiver(pre_delete, sender=OrderStatusEvent)
def protect_order_history(sender, instance, **kwargs):
    """Orders are business records: cancel them, never delete them (also blocks bulk deletes)."""
    raise ValidationError("Orders and their history cannot be deleted. Cancel the order instead.")

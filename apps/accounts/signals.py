from django.db.models import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import User


@receiver(pre_delete, sender=User)
def protect_primary_owner(sender, instance, **kwargs):
    """Block deleting the primary owner from anywhere (admin, shell, bulk delete)."""
    if instance.is_primary_owner:
        raise ProtectedError("The primary owner account cannot be deleted.", {instance})

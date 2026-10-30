from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Stock items, the stock movement ledger, suppliers and purchases."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Inventory"

    def ready(self):
        from . import signals  # noqa: F401

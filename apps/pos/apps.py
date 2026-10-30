from django.apps import AppConfig


class PosConfig(AppConfig):
    """In-store point of sale: cashier shifts, cash drawer movements, receipts and POS settings."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pos"
    label = "pos"
    verbose_name = "Point of sale"

    def ready(self):
        from . import signals  # noqa: F401

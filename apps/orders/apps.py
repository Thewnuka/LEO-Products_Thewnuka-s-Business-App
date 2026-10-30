from django.apps import AppConfig


class OrdersConfig(AppConfig):
    """Checkout, customer orders, order status workflow, delivery zones and checkout settings."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    label = "orders"
    verbose_name = "Orders"

    def ready(self):
        from . import signals  # noqa: F401

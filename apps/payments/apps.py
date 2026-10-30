from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Payments for orders: cash, bank transfer (with verified evidence) and online gateways."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    label = "payments"
    verbose_name = "Payments"

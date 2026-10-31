from django.apps import AppConfig


class FinanceConfig(AppConfig):
    """Expenses, supplier payments, financial reports, profit & loss and the finance audit log."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    label = "finance"
    verbose_name = "Finance"

    def ready(self):
        from . import signals  # noqa: F401

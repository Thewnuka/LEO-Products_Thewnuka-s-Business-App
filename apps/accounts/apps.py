from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """User accounts, authentication, roles and staff management."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        from . import signals  # noqa: F401

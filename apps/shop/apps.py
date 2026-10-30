from django.apps import AppConfig


class ShopConfig(AppConfig):
    """Customer storefront (browse, search, product pages) and the shopping cart."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shop"
    label = "shop"
    verbose_name = "Shop"

    def ready(self):
        from . import signals  # noqa: F401

from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """Categories, products, product variations and measurement units."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalogue"

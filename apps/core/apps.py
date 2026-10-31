from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Shared building blocks: base models, brand context, public pages, error pages."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Core"

    def ready(self):
        from . import checks  # noqa: F401  (registers the `check --deploy` rules)

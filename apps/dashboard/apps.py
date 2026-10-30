from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """Role-based staff dashboards."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    label = "dashboard"
    verbose_name = "Dashboard"

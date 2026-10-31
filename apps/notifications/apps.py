from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """In-app notifications, notification preferences, business alerts and alert settings."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications"

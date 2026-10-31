"""
Notifications.

  Notification             one message for one user (in-app), read/unread, with a link.
                           `dedupe_key` is unique per recipient, so the same event can never
                           notify the same person twice (retries, double clicks, re-runs).
  NotificationPreference   which categories a user wants in-app, and (customers) order emails.
  AlertSettings            one row: thresholds for business alerts and review moderation (Owner).

Who receives what is decided in services.py from the user's role capabilities;
customers only ever receive notifications about their own orders and reviews.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Category(models.TextChoices):
    ORDERS = "ORDERS", "Orders"
    PAYMENTS = "PAYMENTS", "Payments"
    STOCK = "STOCK", "Stock alerts"
    PURCHASES = "PURCHASES", "Purchases"
    POS = "POS", "Point of sale"
    FINANCE = "FINANCE", "Finance"
    REVIEWS = "REVIEWS", "Reviews"
    ALERTS = "ALERTS", "Business alerts"


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Information"
        SUCCESS = "success", "Good news"
        WARNING = "warning", "Needs attention"
        DANGER = "danger", "Urgent"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=10, choices=Category.choices, db_index=True)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True, help_text="Page inside this site to open.")
    dedupe_key = models.CharField(max_length=120, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["recipient", "dedupe_key"], condition=~Q(dedupe_key=""),
                                    name="notifications_one_per_event_per_user"),
        ]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"], name="notif_inbox_idx")]

    def __str__(self):
        return f"{self.recipient}: {self.title}"

    @property
    def icon(self):
        return {"ORDERS": "bag-check", "PAYMENTS": "credit-card", "STOCK": "boxes", "PURCHASES": "truck",
                "POS": "shop-window", "FINANCE": "graph-up-arrow", "REVIEWS": "star", "ALERTS": "exclamation-triangle"
                }.get(self.category, "bell")


class NotificationPreference(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference")
    muted_categories = models.JSONField(default=list, blank=True, help_text="Categories the user doesn't want in-app.")
    email_order_updates = models.BooleanField("email me about my orders and payments", default=True)

    def __str__(self):
        return f"Notification preferences of {self.user}"

    def wants(self, category):
        return category not in (self.muted_categories or [])


class AlertSettings(TimeStampedModel):
    """Single row (pk=1) edited by the Owner: Staff portal → Notifications → Alert settings."""

    pending_order_hours = models.PositiveIntegerField(
        "flag online orders still pending after (hours)", default=24, validators=[MinValueValidator(1), MaxValueValidator(720)])
    unpaid_order_days = models.PositiveIntegerField(
        "flag orders still unpaid after (days)", default=3, validators=[MinValueValidator(1), MaxValueValidator(90)])
    open_shift_hours = models.PositiveIntegerField(
        "flag POS shifts still open after (hours)", default=14, validators=[MinValueValidator(1), MaxValueValidator(96)])
    reviews_need_approval = models.BooleanField(
        "new reviews need approval before they are shown", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "alert settings"

    def __str__(self):
        return "Alert settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

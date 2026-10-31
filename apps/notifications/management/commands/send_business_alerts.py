"""
Turn today's business alerts into notifications (once per alert, user and day).

Run it once or twice a day, e.g. with Windows Task Scheduler:
    python manage.py send_business_alerts
Running it again on the same day sends nothing new (the dedupe key includes the date).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import STAFF_ROLES
from apps.notifications.alerts import business_alerts
from apps.notifications.models import AlertSettings, Category, Notification
from apps.notifications.services import notify

LEVELS = {"danger": Notification.Level.DANGER, "warning": Notification.Level.WARNING, "info": Notification.Level.INFO}


class Command(BaseCommand):
    help = "Send today's business alerts (low stock, transfers to verify, pending orders...) as notifications."

    def handle(self, *args, **options):
        today = timezone.localdate()
        config = AlertSettings.load()
        sent = 0
        with transaction.atomic():
            for user in get_user_model().objects.filter(is_active=True, role__in=STAFF_ROLES):
                for alert in business_alerts(user, config):
                    notify([user], Category.ALERTS, f"{alert.title}: {alert.count}", message=alert.detail, url=alert.url,
                           level=LEVELS[alert.level], key=f"alert:{alert.code}:{today:%Y%m%d}")
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f"Checked business alerts: {sent} alert notification(s) queued (duplicates skipped)."))

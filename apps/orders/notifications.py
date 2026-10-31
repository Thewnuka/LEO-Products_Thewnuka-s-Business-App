"""
Customer notifications for orders and payments.

There is no separate notifications module yet (planned for a later phase), so
this uses what the project already has: Django email (printed in the terminal
in development; set EMAIL_* in .env for real sending). The order page itself
always shows the current status and full history.

Emails are sent only after the database change is committed, and a failure to
send never breaks the order.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

SUBJECTS = {
    "placed": "We received your order {number}",
    "status": "Your order {number} is now: {status}",
    "cancelled": "Your order {number} was cancelled",
    "payment_approved": "Payment received for order {number}",
    "payment_rejected": "Please check the payment for order {number}",
}


def notify_customer(order, kind, **context):
    """In-app notification (Phase 09) plus email, unless the customer turned order emails off."""
    from apps.notifications.events import customer_order_event

    customer_order_event(order, kind, payment=context.get("payment"))
    if not order.email or kind not in SUBJECTS or not _wants_email(order):
        return

    def send():
        try:
            subject = SUBJECTS[kind].format(number=order.number, status=order.get_status_display())
            body = render_to_string(f"orders/email/{kind}.txt", {"order": order, "brand": settings.BRAND, **context})
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [order.email], fail_silently=False)
        except Exception:  # never let an email problem affect the order
            logger.exception("Could not send %s notification for order %s", kind, order.number)

    transaction.on_commit(send)


def _wants_email(order):
    from apps.notifications.models import NotificationPreference

    if order.customer_id is None:
        return True
    pref = NotificationPreference.objects.filter(user_id=order.customer_id).first()
    return pref is None or pref.email_order_updates

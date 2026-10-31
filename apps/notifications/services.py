"""
Sending and reading notifications.

notify() is the only way notifications are created. It:
  * runs after the current database transaction commits (nothing is sent for work that
    was rolled back);
  * skips users who muted that category;
  * relies on the (recipient, dedupe_key) unique constraint so a repeated event never
    creates a second notification (bulk insert with ignore_conflicts).
Staff recipients are chosen by capability (apps.accounts.roles), never by name.
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.roles import ROLE_CAPABILITIES, Capability, Role, has_capability

from .models import Category, Notification, NotificationPreference

logger = logging.getLogger(__name__)
C = Capability

# Which categories a user can receive (and so can switch on/off), by capability.
STAFF_CATEGORY_CAPABILITIES = {
    Category.ORDERS: (C.MANAGE_ORDERS,),
    Category.PAYMENTS: (C.VERIFY_PAYMENTS,),
    Category.STOCK: (C.MANAGE_INVENTORY,),
    Category.PURCHASES: (C.VIEW_FINANCE,),
    Category.POS: (C.MANAGE_SHIFTS, C.VIEW_FINANCE),
    Category.FINANCE: (C.VIEW_FINANCE,),
    Category.REVIEWS: (C.MODERATE_REVIEWS,),
    Category.ALERTS: (C.MANAGE_ORDERS, C.MANAGE_INVENTORY, C.VERIFY_PAYMENTS, C.MANAGE_SHIFTS, C.PROCESS_SALES),
}
CUSTOMER_CATEGORIES = (Category.ORDERS, Category.PAYMENTS, Category.REVIEWS)


def categories_for(user):
    if user.role == Role.CUSTOMER:
        return list(CUSTOMER_CATEGORIES)
    return [cat for cat, caps in STAFF_CATEGORY_CAPABILITIES.items() if any(has_capability(user, c) for c in caps)]


def preference_for(user):
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    return pref


def users_with(capability, exclude=None):
    roles = [role for role, caps in ROLE_CAPABILITIES.items() if capability in caps]
    users = get_user_model().objects.filter(is_active=True, role__in=roles)
    if exclude is not None and getattr(exclude, "pk", None):
        users = users.exclude(pk=exclude.pk)
    return users


def safe_url(url):
    return url if url and url_has_allowed_host_and_scheme(url, allowed_hosts=None) and url.startswith("/") else ""


def notify(users, category, title, *, message="", url="", level=Notification.Level.INFO, key=""):
    """Queue an in-app notification for each user (after commit). `key` makes it once-only per user."""
    users = list(users)
    if not users:
        return

    def create():
        try:
            ids = [u.pk for u in users]
            muted = {p.user_id for p in NotificationPreference.objects.filter(user_id__in=ids)
                     if not p.wants(category)}
            Notification.objects.bulk_create(
                [Notification(recipient_id=uid, category=category, level=level, title=title[:150], message=message[:500],
                              url=safe_url(url), dedupe_key=key[:120]) for uid in ids if uid not in muted],
                ignore_conflicts=True)
        except Exception:  # a notification problem must never break the business action
            logger.exception("Could not create notification %s", key or title)

    transaction.on_commit(create)


def notify_capability(capability, category, title, *, exclude=None, **kwargs):
    notify(users_with(capability, exclude=exclude), category, title, **kwargs)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def inbox(user):
    return Notification.objects.filter(recipient=user)


def unread_count(user):
    return inbox(user).filter(is_read=False).count()


def mark_read(user, notification_ids=None):
    qs = inbox(user).filter(is_read=False)
    if notification_ids is not None:
        qs = qs.filter(pk__in=notification_ids)
    return qs.update(is_read=True, read_at=timezone.now())


def mark_unread(user, notification_id):
    return inbox(user).filter(pk=notification_id).update(is_read=False, read_at=None)

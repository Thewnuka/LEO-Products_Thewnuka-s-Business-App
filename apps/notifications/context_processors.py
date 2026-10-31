from django.utils.functional import SimpleLazyObject

from . import services


def notifications(request):
    """Bell badge and the five newest notifications for the dropdown (only queried if a page shows them)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {
        "notification_unread": SimpleLazyObject(lambda: services.unread_count(user)),
        "notification_latest": SimpleLazyObject(lambda: list(services.inbox(user)[:5])),
    }

"""
Business alerts: live counts of things that need someone's attention, worked out when a
page is shown (never stored, so they can't go stale). Each alert is only built for users
whose role can act on it.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import Capability as C
from apps.accounts.roles import has_capability

from .models import AlertSettings


@dataclass
class Alert:
    code: str
    level: str      # danger | warning | info
    title: str
    detail: str
    count: int
    url: str


def business_alerts(user, config=None):
    from apps.inventory.models import InventoryItem
    from apps.orders.models import Order
    from apps.pos.models import CashierShift

    config = config or AlertSettings.load()
    now = timezone.now()
    alerts = []
    can = lambda cap: has_capability(user, cap)  # noqa: E731
    P, S = Order.PaymentStatus, Order.Status

    if can(C.MANAGE_INVENTORY):
        items = InventoryItem.objects.filter(is_active=True)
        out = items.filter(quantity__lte=0).count()
        low = items.filter(quantity__gt=0, quantity__lte=F("reorder_level")).count()
        url = reverse("inventory:item_list")
        if out:
            alerts.append(Alert("out_of_stock", "danger", "Out of stock", "Items with no stock left.", out, url + "?state=OUT"))
        if low:
            alerts.append(Alert("low_stock", "warning", "Low stock", "Items at or below their reorder level.", low, url + "?state=ATTENTION"))

    if can(C.VERIFY_PAYMENTS):
        transfers = Order.objects.filter(payment_status=P.PENDING_VERIFICATION).exclude(status=S.CANCELLED).count()
        if transfers:
            alerts.append(Alert("transfers", "warning", "Bank transfers to verify",
                                "Online and till payments waiting for a check of the bank account.", transfers,
                                reverse("orders:staff_list") + "?payment_status=PENDING_VERIFICATION"))

    if can(C.MANAGE_ORDERS):
        online = Order.objects.filter(channel=Order.Channel.ONLINE)
        pending = online.filter(status=S.PENDING)
        old = pending.filter(created_at__lte=now - timedelta(hours=config.pending_order_hours)).count()
        if pending.exists():
            alerts.append(Alert("pending_orders", "danger" if old else "info", "Orders waiting to be confirmed",
                                f"{old} waiting more than {config.pending_order_hours} h." if old else "New orders to process.",
                                pending.count(), reverse("orders:staff_list") + "?status=PENDING"))
        unpaid = online.filter(payment_status=P.PENDING, created_at__lte=now - timedelta(days=config.unpaid_order_days)
                               ).exclude(status=S.CANCELLED).count()
        if unpaid:
            alerts.append(Alert("unpaid_orders", "warning", "Orders unpaid for a while",
                                f"Still awaiting payment after {config.unpaid_order_days} days.", unpaid,
                                reverse("orders:staff_list") + "?payment_status=PENDING"))

    if can(C.MANAGE_PAYMENTS):
        refunds = Order.objects.filter(payment_status=P.REFUND_DUE).count()
        if refunds:
            alerts.append(Alert("refunds_due", "warning", "Refunds owed to customers",
                                "Cancelled after payment; refund and record it.", refunds,
                                reverse("orders:staff_list") + "?payment_status=REFUND_DUE"))

    limit = now - timedelta(hours=config.open_shift_hours)
    if can(C.MANAGE_SHIFTS):
        stale = CashierShift.objects.filter(status=CashierShift.Status.OPEN, opened_at__lte=limit).count()
        if stale:
            alerts.append(Alert("open_shifts", "warning", "POS shifts left open",
                                f"Open for more than {config.open_shift_hours} h; count and close them.", stale,
                                reverse("pos:shifts") + "?status=OPEN"))
    elif can(C.PROCESS_SALES):
        own = CashierShift.objects.filter(cashier=user, status=CashierShift.Status.OPEN, opened_at__lte=limit).first()
        if own:
            alerts.append(Alert("own_shift", "warning", "Your shift is still open",
                                f"Opened {timezone.localtime(own.opened_at):%d %b %H:%M}. Close it at the end of the day.", 1,
                                reverse("pos:shift_detail", args=[own.pk])))

    if can(C.MANAGE_FINANCE):
        missing = InventoryItem.objects.filter(is_active=True, average_cost__isnull=True,
                                               kind=InventoryItem.Kind.FINISHED_GOOD).count()
        if missing:
            alerts.append(Alert("missing_costs", "info", "Products without a cost",
                                "Profit can't be worked out for their sales until a cost is set.", missing,
                                reverse("finance:stock_costs") + "?missing=1"))

    if can(C.MODERATE_REVIEWS):
        from apps.shop.models import ProductReview

        reviews = ProductReview.objects.filter(status=ProductReview.Status.PENDING).count()
        if reviews:
            alerts.append(Alert("reviews", "info", "Reviews to check", "Customer reviews waiting for approval.", reviews,
                                reverse("shop:review_moderation") + "?status=PENDING"))

    order = {"danger": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a.level])

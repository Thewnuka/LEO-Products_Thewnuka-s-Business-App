"""
Business events -> notifications. Called from the existing services (orders, payments,
inventory, POS, finance, shop) at the point where the action happens.

Every call has a dedupe key built from the event (e.g. the order's status event id), so
re-running an action, a retried request or a repeated gateway callback can't notify twice.
Messages never contain costs, profit or other people's personal details.
"""
from django.urls import reverse

from apps.accounts.roles import Capability as C

from .models import Category, Notification
from .services import notify, notify_capability

L = Notification.Level


# ---------------------------------------------------------------------------
# Customers (their own orders only)
# ---------------------------------------------------------------------------
CUSTOMER_MESSAGES = {
    "placed": (Category.ORDERS, L.SUCCESS, "Order {number} placed", "Thank you! We'll let you know as it progresses."),
    "status": (Category.ORDERS, L.INFO, "Order {number}: {status}", "Your order status changed to {status}."),
    "cancelled": (Category.ORDERS, L.WARNING, "Order {number} was cancelled", "{reason}"),
    "payment_approved": (Category.PAYMENTS, L.SUCCESS, "Payment received for order {number}",
                         "We received LKR {amount}. Thank you!"),
    "payment_rejected": (Category.PAYMENTS, L.WARNING, "Please check the payment for order {number}",
                         "We couldn't confirm your transfer: {note}"),
    "cash_received": (Category.PAYMENTS, L.SUCCESS, "Payment received for order {number}", "Cash of LKR {amount} received."),
}


def customer_order_event(order, kind, payment=None):
    """In-app notification for the order's own customer (online orders only)."""
    if order.customer_id is None or kind not in CUSTOMER_MESSAGES:
        return
    category, level, title, message = CUSTOMER_MESSAGES[kind]
    values = {"number": order.number, "status": order.get_status_display().lower(), "reason": order.cancel_reason,
              "amount": f"{payment.amount:,.2f}" if payment else "", "note": payment.verification_note if payment else ""}
    if kind == "status":
        last = order.events.order_by("-pk").values_list("pk", flat=True).first()
        key = f"order:{order.pk}:status-event:{last}"
    elif payment is not None:
        key = f"payment:{payment.pk}:{kind}"
    else:
        key = f"order:{order.pk}:{kind}"
    notify([order.customer], category, title.format(**values), message=message.format(**values),
           url=reverse("orders:detail", args=[order.number]), level=level, key=key)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
def new_online_order(order):
    notify_capability(C.MANAGE_ORDERS, Category.ORDERS, f"New order {order.number}",
                      message=f"{order.get_fulfilment_display()} · {order.get_payment_method_display()} · LKR {order.total:,.2f}",
                      url=reverse("orders:staff_detail", args=[order.number]), key=f"order:{order.pk}:new")


def order_cancelled_by_customer(order):
    notify_capability(C.MANAGE_ORDERS, Category.ORDERS, f"Order {order.number} cancelled by the customer",
                      message=order.cancel_reason, url=reverse("orders:staff_detail", args=[order.number]),
                      level=L.WARNING, key=f"order:{order.pk}:customer-cancelled")


def transfer_to_verify(payment):
    order = payment.order
    where = "At the till" if order.is_pos else "Online order"
    notify_capability(C.VERIFY_PAYMENTS, Category.PAYMENTS, f"Bank transfer to verify: {order.number}",
                      message=f"{where} · LKR {payment.amount:,.2f} · ref. {payment.bank_reference}",
                      url=order.get_staff_url(), level=L.WARNING, key=f"payment:{payment.pk}:to-verify")


def online_payment_received(payment):
    order = payment.order
    notify_capability(C.MANAGE_ORDERS, Category.PAYMENTS, f"Online payment received: {order.number}",
                      message=f"LKR {payment.amount:,.2f} confirmed by the payment provider.",
                      url=order.get_staff_url(), level=L.SUCCESS, key=f"payment:{payment.pk}:online-paid")


def stock_crossed(item, movement):
    """Stock just fell to the reorder level, or ran out (only on the movement that crossed the line)."""
    before, after = movement.quantity_before, movement.quantity_after
    if after <= 0 < before:
        title, level = f"Out of stock: {item.display_name}", L.DANGER
    elif after <= item.reorder_level < before:
        title, level = f"Low stock: {item.display_name}", L.WARNING
    else:
        return
    notify_capability(C.MANAGE_INVENTORY, Category.STOCK, title,
                      message=f"{item.format_qty(after)} left (reorder level {item.format_qty(item.reorder_level)}).",
                      url=reverse("inventory:item_detail", args=[item.pk]), level=level, key=f"stock:{movement.pk}")


def purchase_received(purchase, user):
    notify_capability(C.VIEW_FINANCE, Category.PURCHASES, f"Purchase {purchase.reference} received",
                      message=f"{purchase.supplier.name} · LKR {purchase.total:,.2f} added to the supplier balance.",
                      url=reverse("inventory:purchase_detail", args=[purchase.pk]), exclude=user,
                      key=f"purchase:{purchase.pk}:received")


def pos_sale_refunded(order, user):
    notify_capability(C.VIEW_FINANCE, Category.POS, f"Till sale {order.number} voided",
                      message=f"LKR {order.total:,.2f} · {order.cancel_reason}",
                      url=reverse("pos:sale_detail", args=[order.number]), exclude=user, level=L.WARNING,
                      key=f"order:{order.pk}:pos-refund")


def shift_closed_with_difference(shift, user):
    if not shift.difference:
        return
    kind = "short" if shift.difference < 0 else "over"
    notify_capability(C.MANAGE_SHIFTS, Category.POS, f"Shift {shift.code} closed {kind} by LKR {abs(shift.difference):,.2f}",
                      message=f"{shift.cashier.get_full_name() or shift.cashier.username}: {shift.closing_note}",
                      url=reverse("pos:shift_detail", args=[shift.pk]), exclude=user, level=L.WARNING,
                      key=f"shift:{shift.pk}:closed")


def expense_recorded(expense, user):
    notify_capability(C.VIEW_FINANCE, Category.FINANCE, f"Expense {expense.reference} recorded",
                      message=f"{expense.category} · LKR {expense.amount:,.2f} · by {user.get_full_name() or user.username}",
                      url=reverse("finance:expense_detail", args=[expense.pk]), exclude=user,
                      key=f"expense:{expense.pk}:recorded")


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
def review_submitted(review):
    notify_capability(C.MODERATE_REVIEWS, Category.REVIEWS, f"New review to check: {review.product.name}",
                      message=f"{review.rating}★ · {review.title}", url=reverse("shop:review_moderation") + "?status=PENDING",
                      key=f"review:{review.pk}:submitted:{review.submitted_at:%Y%m%d%H%M%S%f}")


def review_moderated(review):
    approved = review.status == review.Status.APPROVED
    notify([review.customer], Category.REVIEWS,
           f"Your review of {review.product.name} is {'published' if approved else 'not published'}",
           message="" if approved else review.moderation_note, url=reverse("shop:product", args=[review.product.slug]),
           level=L.SUCCESS if approved else L.WARNING,
           key=f"review:{review.pk}:{review.status}:{review.submitted_at:%Y%m%d%H%M%S%f}")

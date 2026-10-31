"""
Business activity history: one timeline read from the audit records each module already
keeps (nothing is copied or duplicated):

  orders     OrderStatusEvent          payments  PaymentEvent
  stock      StockMovement             pos       CashierShift, CashMovement, ReceiptPrint
  reviews    ProductReview moderation  finance   FinanceEvent, ItemCostChange (Owner)
  accounts   AccountAuditLog (Owner)

Managers see operational sources only; account and finance entries need the Owner's
capabilities.
"""
from dataclasses import dataclass
from datetime import datetime, time

from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import Capability as C
from apps.accounts.roles import has_capability

PER_SOURCE = 300


@dataclass
class Entry:
    at: object
    source: str
    title: str
    detail: str
    actor: object
    url: str = ""


SOURCES = [("orders", "Orders"), ("payments", "Payments"), ("stock", "Stock"), ("pos", "Point of sale"),
           ("reviews", "Reviews"), ("finance", "Finance"), ("accounts", "Accounts")]


def allowed_sources(user):
    if not has_capability(user, C.VIEW_ACTIVITY):
        return []
    sources = ["orders", "payments", "stock", "pos", "reviews"]
    if has_capability(user, C.VIEW_FINANCE):
        sources.append("finance")
    if has_capability(user, C.MANAGE_PERMISSIONS):
        sources.append("accounts")
    return sources


def _range(qs, field, period, actor_field=None, actor=None):
    start = timezone.make_aware(datetime.combine(period.start, time.min))
    end = timezone.make_aware(datetime.combine(period.end, time.max))
    qs = qs.filter(**{f"{field}__gte": start, f"{field}__lte": end})
    if actor and actor_field:
        qs = qs.filter(**{actor_field: actor})
    return qs.order_by(f"-{field}")[:PER_SOURCE]


def _orders(period, actor):
    from apps.orders.models import OrderStatusEvent

    for e in _range(OrderStatusEvent.objects.select_related("order", "created_by"), "created_at", period, "created_by", actor):
        yield Entry(e.created_at, "orders", f"{e.order.number}: {e.to_label}", e.note, e.created_by, e.order.get_staff_url())


def _payments(period, actor):
    from apps.payments.models import PaymentEvent

    for e in _range(PaymentEvent.objects.select_related("payment__order", "created_by"), "created_at", period, "created_by", actor):
        yield Entry(e.created_at, "payments", f"{e.payment.reference}: {e.label}", e.payment.order.number, e.created_by,
                    e.payment.order.get_staff_url())


def _stock(period, actor):
    from apps.inventory.models import StockMovement

    qs = StockMovement.objects.select_related("item__stock_unit", "item__variation__product", "item__variation__unit", "created_by")
    for m in _range(qs, "created_at", period, "created_by", actor):
        yield Entry(m.created_at, "stock", f"{m.item.display_name}: {m.get_movement_type_display()} "
                    f"{'+' if m.quantity_change > 0 else ''}{m.item.format_qty(m.quantity_change)}", m.reason, m.created_by,
                    reverse("inventory:item_detail", args=[m.item_id]))


def _pos(period, actor):
    from apps.pos.models import CashierShift, CashMovement, ReceiptPrint

    for s in _range(CashierShift.objects.select_related("cashier"), "opened_at", period, "cashier", actor):
        yield Entry(s.opened_at, "pos", f"Shift {s.code} opened", f"Opening cash LKR {s.opening_cash:,.2f}", s.cashier,
                    reverse("pos:shift_detail", args=[s.pk]))
    for s in _range(CashierShift.objects.select_related("closed_by").filter(closed_at__isnull=False), "closed_at", period,
                    "closed_by", actor):
        yield Entry(s.closed_at, "pos", f"Shift {s.code} closed", f"Difference LKR {s.difference:,.2f}", s.closed_by,
                    reverse("pos:shift_detail", args=[s.pk]))
    for m in _range(CashMovement.objects.select_related("shift", "created_by"), "created_at", period, "created_by", actor):
        yield Entry(m.created_at, "pos", f"{m.get_kind_display()} LKR {m.amount:,.2f} ({m.shift.code})", m.reason, m.created_by,
                    reverse("pos:shift_detail", args=[m.shift_id]))
    for r in _range(ReceiptPrint.objects.select_related("order", "printed_by"), "printed_at", period, "printed_by", actor):
        yield Entry(r.printed_at, "pos", f"Receipt {r.order.number} reprinted", "", r.printed_by,
                    reverse("pos:sale_detail", args=[r.order.number]))


def _reviews(period, actor):
    from apps.shop.models import ProductReview

    qs = ProductReview.objects.select_related("product", "moderated_by").filter(moderated_at__isnull=False)
    for r in _range(qs, "moderated_at", period, "moderated_by", actor):
        yield Entry(r.moderated_at, "reviews", f"Review of {r.product.name} {r.get_status_display().lower()}",
                    r.moderation_note, r.moderated_by, reverse("shop:review_moderation") + "?status=ALL")


def _finance(period, actor):
    from apps.finance.models import FinanceEvent
    from apps.inventory.models import ItemCostChange

    for e in _range(FinanceEvent.objects.select_related("user"), "created_at", period, "user", actor):
        yield Entry(e.created_at, "finance", f"{e.label} {e.object_ref}",
                    " · ".join(f"{k}: {v}" for k, v in e.detail.items()), e.user, reverse("finance:audit_log"))
    for c in _range(ItemCostChange.objects.select_related("item__variation__product", "item__variation__unit",
                                                          "item__stock_unit", "changed_by"),
                    "changed_at", period, "changed_by", actor):
        yield Entry(c.changed_at, "finance", f"Cost of {c.item.display_name}: {c.old_cost or '—'} → {c.new_cost}",
                    c.get_source_display(), c.changed_by, reverse("finance:stock_cost", args=[c.item_id]))


def _accounts(period, actor):
    from apps.accounts.models import AccountAuditLog

    for e in _range(AccountAuditLog.objects.select_related("actor", "target"), "created_at", period, "actor", actor):
        yield Entry(e.created_at, "accounts", e.get_action_display(), str(e.target or ""), e.actor)


BUILDERS = {"orders": _orders, "payments": _payments, "stock": _stock, "pos": _pos, "reviews": _reviews,
            "finance": _finance, "accounts": _accounts}


def activity(user, period, source="", actor=None, q=""):
    sources = allowed_sources(user)
    if source:
        sources = [s for s in sources if s == source]
    entries = [entry for s in sources for entry in BUILDERS[s](period, actor)]
    q = (q or "").strip().lower()
    if q:
        entries = [e for e in entries if q in e.title.lower() or q in (e.detail or "").lower()]
    entries.sort(key=lambda e: e.at, reverse=True)
    return entries

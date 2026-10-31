"""
Finance logic and the single definitions of every figure the reports use.

No double counting (one source per figure):
  Revenue    orders that are PAID and not cancelled, dated by the order date:
             product sales (subtotal) - discounts + delivery fees = order total.
             Unpaid orders are not revenue yet; cancelled/refunded orders never are.
  COGS       OrderItem.cost_total of those orders (copied at the moment of sale).
             Lines sold before a cost was known have no cost and are reported separately.
  Expenses   Expense rows (RECORDED). Stock purchases are NOT expenses: they become
             cost of goods sold when the goods are sold.
  Purchases  received inventory.Purchase totals (for the purchases report and supplier balances).
  Cash flow  money actually moving: payments received (paid_at), refunds paid (refunded_at),
             supplier payments and expenses (their dates). Revenue is never added to it.
"""
import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import Purchase, Supplier
from apps.inventory.services import set_item_cost
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.payments.services import validate_evidence

from .models import Expense, FinanceEvent, PaymentMethod, SupplierPayment

ZERO = Decimal("0.00")


class FinanceError(ValidationError):
    """A finance action that is not allowed (shown to the user)."""


def log(action, user, object_ref="", **detail):
    return FinanceEvent.objects.create(action=action, user=user if getattr(user, "is_authenticated", False) else None,
                                       object_ref=object_ref, detail={k: str(v) for k, v in detail.items()})


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
@dataclass
class Period:
    start: date
    end: date
    label: str
    preset: str = ""

    @property
    def days(self):
        return (self.end - self.start).days + 1


PRESETS = [("today", "Today"), ("week", "This week"), ("month", "This month"), ("last_month", "Last month"),
           ("year", "This year"), ("last_year", "Last year"), ("custom", "Custom dates")]


def period_from(params, default="month"):
    """Read ?period=...&start=YYYY-MM-DD&end=YYYY-MM-DD (invalid input falls back to the default)."""
    today = timezone.localdate()
    preset = params.get("period") or default
    if preset == "custom":
        try:
            start, end = date.fromisoformat(params.get("start", "")), date.fromisoformat(params.get("end", ""))
            if start <= end and (end - start).days <= 3660:
                return Period(start, end, f"{start:%d %b %Y} – {end:%d %b %Y}", "custom")
        except ValueError:
            pass
        preset = default
    if preset == "today":
        return Period(today, today, f"{today:%d %b %Y}", preset)
    if preset == "week":
        start = today - timedelta(days=today.weekday())
        return Period(start, today, f"Week from {start:%d %b %Y}", preset)
    if preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return Period(end.replace(day=1), end, f"{end:%B %Y}", preset)
    if preset == "year":
        return Period(date(today.year, 1, 1), today, f"{today.year} (to date)", preset)
    if preset == "last_year":
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1), preset)
    start = today.replace(day=1)
    return Period(start, today.replace(day=monthrange(today.year, today.month)[1]), f"{today:%B %Y}", "month")


# ---------------------------------------------------------------------------
# Figures (used by the dashboard and every report)
# ---------------------------------------------------------------------------
def recognised_orders(period=None):
    """Sales that count as revenue: paid and not cancelled."""
    qs = Order.objects.filter(payment_status=Order.PaymentStatus.PAID).exclude(status=Order.Status.CANCELLED)
    if period:
        qs = qs.filter(created_at__date__gte=period.start, created_at__date__lte=period.end)
    return qs


def sold_lines(period=None):
    return OrderItem.objects.filter(order__in=recognised_orders(period))


def active_expenses(period=None):
    qs = Expense.objects.filter(status=Expense.Status.RECORDED)
    if period:
        qs = qs.filter(expense_date__gte=period.start, expense_date__lte=period.end)
    return qs


def received_purchases(period=None, until=None):
    qs = Purchase.objects.filter(status=Purchase.Status.RECEIVED)
    if period:
        qs = qs.filter(purchase_date__gte=period.start, purchase_date__lte=period.end)
    if until:
        qs = qs.filter(purchase_date__lte=until)
    return qs


def active_supplier_payments(period=None, until=None):
    qs = SupplierPayment.objects.filter(status=SupplierPayment.Status.RECORDED)
    if period:
        qs = qs.filter(payment_date__gte=period.start, payment_date__lte=period.end)
    if until:
        qs = qs.filter(payment_date__lte=until)
    return qs


def _sum(qs, field, **filters):
    return qs.filter(**filters).aggregate(s=Sum(field))["s"] or ZERO


@dataclass
class Summary:
    sales_count: int
    gross_sales: Decimal        # product prices before discounts
    discounts: Decimal
    delivery_income: Decimal
    revenue: Decimal            # = gross_sales - discounts + delivery_income
    cogs: Decimal               # known costs only
    uncosted_revenue: Decimal   # line revenue of items sold without a known cost
    uncosted_lines: int
    expenses: Decimal
    purchases: Decimal
    cash_in: Decimal
    bank_in: Decimal
    unpaid_orders: Decimal      # placed in the period, not paid yet (not revenue)

    @property
    def gross_profit(self):
        return self.revenue - self.cogs

    @property
    def net_operating_profit(self):
        return self.gross_profit - self.expenses

    @property
    def collections(self):
        return self.cash_in + self.bank_in


def summary(period):
    orders = recognised_orders(period)
    totals = orders.aggregate(gross=Sum("subtotal"), disc=Sum("discount_amount"), fee=Sum("delivery_fee"),
                              total=Sum("total"))
    lines = sold_lines(period)
    received = received_payments(period)
    unpaid = Order.objects.filter(created_at__date__gte=period.start, created_at__date__lte=period.end,
                                  payment_status__in=[Order.PaymentStatus.PENDING, Order.PaymentStatus.PENDING_VERIFICATION]
                                  ).exclude(status=Order.Status.CANCELLED)
    return Summary(
        sales_count=orders.count(), gross_sales=totals["gross"] or ZERO, discounts=totals["disc"] or ZERO,
        delivery_income=totals["fee"] or ZERO, revenue=totals["total"] or ZERO,
        cogs=_sum(lines, "cost_total"), uncosted_revenue=_sum(lines, "line_total", cost_total__isnull=True),
        uncosted_lines=lines.filter(cost_total__isnull=True).count(),
        expenses=_sum(active_expenses(period), "amount"), purchases=_sum(received_purchases(period), "total"),
        cash_in=_sum(received, "amount", method=Order.PaymentMethod.CASH),
        bank_in=_sum(received, "amount", method__in=[Order.PaymentMethod.BANK_TRANSFER, Order.PaymentMethod.ONLINE]),
        unpaid_orders=_sum(unpaid, "total"),
    )


def received_payments(period):
    """Money received in the period (by the date it was confirmed). A later refund is a separate outflow."""
    return Payment.objects.filter(status__in=[Payment.Status.PAID, Payment.Status.REFUNDED], paid_at__isnull=False,
                                  paid_at__date__gte=period.start, paid_at__date__lte=period.end)


def refunds_paid(period):
    return Payment.objects.filter(status=Payment.Status.REFUNDED, refunded_at__date__gte=period.start,
                                  refunded_at__date__lte=period.end)


def supplier_balance(supplier, until=None):
    purchased = _sum(received_purchases(until=until).filter(supplier=supplier), "total")
    paid = _sum(active_supplier_payments(until=until).filter(supplier=supplier), "amount")
    return purchased, paid, purchased - paid


def purchase_paid(purchase):
    return _sum(active_supplier_payments().filter(purchase=purchase), "amount")


# ---------------------------------------------------------------------------
# Recording (each create is idempotent on the form's submission token)
# ---------------------------------------------------------------------------
def _next_reference(model, prefix, on_date):
    start = f"{prefix}-{on_date.year}-"
    last = model.objects.filter(reference__startswith=start).order_by("-reference").values_list("reference", flat=True).first()
    return f"{start}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):05d}"


def _create_once(model, token, build):
    """Create a record for this form submission, or return the one already created for it."""
    for attempt in range(3):
        existing = model.objects.filter(submission_token=token).first()
        if existing:
            return existing, False
        try:
            with transaction.atomic():
                return build(), True
        except IntegrityError:
            if attempt == 2:
                raise
    raise FinanceError("Could not save. Please try again.")


def record_expense(user, token, *, category, expense_date, amount, payment_method, description,
                   paid_to="", payment_reference="", receipt=None):
    if not category.is_active:
        raise FinanceError("That expense category is inactive.")
    if amount is None or Decimal(amount) <= 0:
        raise FinanceError("The amount must be greater than zero.")
    if expense_date > timezone.localdate():
        raise FinanceError("The expense date can't be in the future.")
    if payment_method not in PaymentMethod.values:
        raise FinanceError("Choose a payment method.")
    content_type = validate_evidence(receipt) if receipt else ""

    def build():
        expense = Expense(category=category, expense_date=expense_date, amount=Decimal(amount), payment_method=payment_method,
                          description=description.strip(), paid_to=paid_to.strip(), payment_reference=payment_reference.strip(),
                          receipt_content_type=content_type, submission_token=token, created_by=user,
                          reference=_next_reference(Expense, "EXP", expense_date))
        if receipt:
            expense.receipt = receipt
        expense.save()
        log("expense_recorded", user, expense.reference, amount=expense.amount, category=category.name)
        return expense

    return _create_once(Expense, token, build)


def record_supplier_payment(user, token, *, supplier, payment_date, amount, payment_method,
                            purchase=None, payment_reference="", notes=""):
    amount = Decimal(amount or 0)
    if amount <= 0:
        raise FinanceError("The amount must be greater than zero.")
    if payment_date > timezone.localdate():
        raise FinanceError("The payment date can't be in the future.")
    if payment_method not in PaymentMethod.values:
        raise FinanceError("Choose a payment method.")

    def build():
        # Lock the supplier so two payments at once can't both pass the balance check.
        locked = Supplier.objects.select_for_update().get(pk=supplier.pk)
        if purchase is not None:
            if purchase.supplier_id != locked.pk or purchase.status != Purchase.Status.RECEIVED:
                raise FinanceError("Choose a received purchase from this supplier.")
            remaining = purchase.total - purchase_paid(purchase)
            if amount > remaining:
                raise FinanceError(f"{purchase.reference} has only LKR {remaining:,.2f} left to pay.")
        _, _, balance = supplier_balance(locked)
        if amount > balance:
            raise FinanceError(f"{locked.name} is owed only LKR {balance:,.2f} for received purchases. "
                               "Payments in advance are not recorded here.")
        payment = SupplierPayment.objects.create(
            supplier=locked, purchase=purchase, payment_date=payment_date, amount=amount, payment_method=payment_method,
            payment_reference=payment_reference.strip(), notes=notes.strip(), submission_token=token, created_by=user,
            reference=_next_reference(SupplierPayment, "SP", payment_date))
        log("supplier_payment_recorded", user, payment.reference, amount=amount, supplier=locked.name)
        return payment

    return _create_once(SupplierPayment, token, build)


@transaction.atomic
def void_record(record, user, reason):
    """Void an expense or supplier payment once (conditional update), keeping it in the history."""
    if not (reason or "").strip():
        raise FinanceError("Please give a reason for voiding.")
    model = type(record)
    done = model.objects.filter(pk=record.pk, status=model.Status.RECORDED).update(
        status=model.Status.VOID, voided_at=timezone.now(), voided_by=user, void_reason=reason.strip()[:300],
        updated_at=timezone.now())
    if not done:
        raise FinanceError(f"{record.reference} is already void.")
    record.refresh_from_db()
    action = "expense_voided" if model is Expense else "supplier_payment_voided"
    log(action, user, record.reference, amount=record.amount, reason=reason.strip())
    return record


def set_cost(item, cost, user, reason):
    change = set_item_cost(item, cost, user, reason)
    log("item_cost_set", user, str(item), old=change.old_cost if change.old_cost is not None else "none",
        new=change.new_cost, reason=reason.strip())
    return change


def new_token():
    return uuid.uuid4()


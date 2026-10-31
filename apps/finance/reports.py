"""
Financial and operational reports.

Every report is built once here as a Report (columns + rows + totals + notes + chart)
and then shown as a page, exported to CSV/Excel or printed on A4 by the same view.
Figures come from finance.services so each one has a single definition.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

from apps.accounts.roles import Capability
from apps.inventory.models import InventoryItem, Supplier
from apps.orders.models import Order

from . import services
from .charts import bar_chart
from .models import PaymentMethod

ZERO = Decimal("0.00")
PS = Order.PaymentStatus
CANCELLED = Q(status=Order.Status.CANCELLED)


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"          # text | money | int | number
    financial: bool = False     # cost / profit figures: only for users with full finance access


@dataclass
class Report:
    slug: str
    title: str
    columns: list
    rows: list
    period: object = None
    totals: dict = None
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    chart: dict = None
    options: dict = field(default_factory=dict)
    finance_notes: list = field(default_factory=list)   # about costs/profit: only for full finance access

    def visible_columns(self, show_financial):
        return [c for c in self.columns if show_financial or not c.financial]


def _v(value):
    return value if value is not None else ZERO


def _person(first, last, username):
    return f"{first or ''} {last or ''}".strip() or username or "—"


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
GROUPINGS = {"day": (TruncDay, "%d %b %Y"), "month": (TruncMonth, "%b %Y"), "year": (TruncYear, "%Y")}


def sales_report(period, params):
    group = params.get("group")
    if group not in GROUPINGS:
        group = "day" if period.days <= 62 else ("month" if period.days <= 800 else "year")
    trunc, fmt = GROUPINGS[group]
    online, pos = Q(channel=Order.Channel.ONLINE), Q(channel=Order.Channel.POS)
    data = (services.recognised_orders(period).annotate(bucket=trunc("created_at")).values("bucket")
            .annotate(count=Count("pk"), gross=Sum("subtotal"), discounts=Sum("discount_amount"), delivery=Sum("delivery_fee"),
                      revenue=Sum("total"), online=Sum("total", filter=online), pos=Sum("total", filter=pos))
            .order_by("bucket"))
    rows = [{"period": row["bucket"].strftime(fmt), "count": row["count"], "gross": _v(row["gross"]),
             "discounts": _v(row["discounts"]), "delivery": _v(row["delivery"]), "online": _v(row["online"]),
             "pos": _v(row["pos"]), "revenue": _v(row["revenue"])} for row in data]
    keys = ["count", "gross", "discounts", "delivery", "online", "pos", "revenue"]
    totals = {"period": "Total", **{k: sum((r[k] for r in rows), 0 if k == "count" else ZERO) for k in keys}}
    s = services.summary(period)
    notes = ["Sales are counted when paid and dated by the order date. Cancelled and refunded orders are excluded."]
    if s.unpaid_orders:
        notes.append(f"Orders placed in this period but not paid yet (not included): LKR {s.unpaid_orders:,.2f}.")
    return Report("sales", "Sales", [
        Column("period", "Period"), Column("count", "Sales", "int"), Column("gross", "Product sales", "money"),
        Column("discounts", "Discounts", "money"), Column("delivery", "Delivery fees", "money"),
        Column("online", "Online shop", "money"), Column("pos", "In store (POS)", "money"),
        Column("revenue", "Revenue", "money")],
        rows, period, totals, notes,
        chart=bar_chart([r["period"] for r in rows], [("Online shop", [r["online"] for r in rows], "online"),
                                                      ("In store", [r["pos"] for r in rows], "pos")], stacked=True),
        options={"group": group, "hidden": [("group", group)],
                 "groups": [("day", "By day"), ("month", "By month"), ("year", "By year")]})


def _line_rows(qs, label_fields, **labels):
    data = (qs.values(*label_fields)
            .annotate(**labels, qty=Sum("quantity"), revenue=Sum("line_total"), cost=Sum("cost_total"),
                      uncosted=Sum("line_total", filter=Q(cost_total__isnull=True)))
            .order_by("-revenue"))
    rows = []
    for row in data:
        revenue, uncosted, cost = _v(row["revenue"]), _v(row["uncosted"]), _v(row["cost"])
        rows.append({**row, "revenue": revenue, "cost": cost, "uncosted": uncosted,
                     "profit": revenue - uncosted - cost})
    return rows


def _line_totals(rows, label_key):
    return {label_key: "Total", "qty": sum((r["qty"] for r in rows), 0), **{k: sum((r[k] for r in rows), ZERO)
                                                                            for k in ("revenue", "cost", "uncosted", "profit")}}


LINE_NOTES = ["Line amounts are before order discounts (shown in the Sales report)."]
LINE_FINANCE_NOTES = ["Gross profit uses the cost recorded when each item was sold; items sold before a cost was known "
                      "are listed under \"Sales without cost\" and left out of the profit."]
LINE_COLUMNS = [Column("qty", "Qty sold", "int"), Column("revenue", "Sales", "money"),
                Column("cost", "Cost of goods", "money", True), Column("profit", "Gross profit", "money", True),
                Column("uncosted", "Sales without cost", "money", True)]


def products_report(period, params):
    # Names come from the copies on the order lines (the catalogue may have changed since).
    data = _line_rows(services.sold_lines(period), ["variation_id"],
                      product=Max("product_name"), size=Max("variation_name"), sku=Max("sku"))
    return Report("products", "Product sales", [Column("product", "Product"), Column("size", "Size"), Column("sku", "SKU"),
                                                *LINE_COLUMNS], data, period, _line_totals(data, "product"), list(LINE_NOTES),
                  finance_notes=list(LINE_FINANCE_NOTES),
                  chart=bar_chart([f"{r['product']} {r['size']}" for r in data[:12]], [("Sales", [r["revenue"] for r in data[:12]], "pos")]))


def categories_report(period, params):
    data = _line_rows(services.sold_lines(period), ["variation__product__category__name"])
    for row in data:
        row["category"] = row.pop("variation__product__category__name") or "—"
    return Report("categories", "Category sales", [Column("category", "Category"), *LINE_COLUMNS], data, period,
                  _line_totals(data, "category"), list(LINE_NOTES) + ["Grouped by each product's current category."],
                  finance_notes=list(LINE_FINANCE_NOTES),
                  chart=bar_chart([r["category"] for r in data], [("Sales", [r["revenue"] for r in data], "online")]))


def cashiers_report(period, params):
    paid = Q(payment_status=PS.PAID) & ~CANCELLED
    data = (Order.objects.filter(channel=Order.Channel.POS, created_at__date__gte=period.start, created_at__date__lte=period.end)
            .values("cashier__username", "cashier__first_name", "cashier__last_name")
            .annotate(sales=Count("pk", filter=~CANCELLED), revenue=Sum("total", filter=paid),
                      cash=Sum("total", filter=paid & Q(payment_method=Order.PaymentMethod.CASH)),
                      bank=Sum("total", filter=paid & Q(payment_method=Order.PaymentMethod.BANK_TRANSFER)),
                      pending=Sum("total", filter=Q(payment_status=PS.PENDING_VERIFICATION) & ~CANCELLED),
                      discounts=Sum("discount_amount", filter=paid), voided=Count("pk", filter=CANCELLED))
            .order_by("-revenue"))
    rows = [{"cashier": _person(r["cashier__first_name"], r["cashier__last_name"], r["cashier__username"]),
             "sales": r["sales"], "cash": _v(r["cash"]), "bank": _v(r["bank"]), "revenue": _v(r["revenue"]),
             "pending": _v(r["pending"]), "discounts": _v(r["discounts"]), "voided": r["voided"]} for r in data]
    totals = {"cashier": "Total", **{k: sum((r[k] for r in rows), 0 if k in ("sales", "voided") else ZERO)
                                     for k in ("sales", "cash", "bank", "revenue", "pending", "discounts", "voided")}}
    return Report("cashiers", "Cashier sales (POS)", [
        Column("cashier", "Cashier"), Column("sales", "Sales", "int"), Column("cash", "Cash", "money"),
        Column("bank", "Bank transfer", "money"), Column("revenue", "Paid sales", "money"),
        Column("pending", "Transfers to check", "money"), Column("discounts", "Discounts given", "money"),
        Column("voided", "Voided", "int")], rows, period, totals,
        ["In-store sales by the cashier who made them. Shift cash counts are on the POS shift pages."],
        chart=bar_chart([r["cashier"] for r in rows], [("Cash", [r["cash"] for r in rows], "pos"),
                                                       ("Bank transfer", [r["bank"] for r in rows], "online")], stacked=True))


# ---------------------------------------------------------------------------
# Purchases, expenses, stock
# ---------------------------------------------------------------------------
def purchases_report(period, params):
    purchases = services.received_purchases(period).select_related("supplier").annotate(
        paid=Sum("supplier_payments__amount", filter=Q(supplier_payments__status="RECORDED"))).order_by("purchase_date", "pk")
    rows = [{"reference": p.reference, "date": p.purchase_date.strftime("%d %b %Y"), "supplier": p.supplier.name,
             "invoice": p.invoice_number or "—", "total": p.total, "paid": _v(p.paid), "outstanding": p.total - _v(p.paid)}
            for p in purchases]
    totals = {"reference": "Total", **{k: sum((r[k] for r in rows), ZERO) for k in ("total", "paid", "outstanding")}}
    by_supplier = {}
    for r in rows:
        by_supplier[r["supplier"]] = by_supplier.get(r["supplier"], ZERO) + r["total"]
    return Report("purchases", "Purchases", [
        Column("reference", "Purchase"), Column("date", "Date"), Column("supplier", "Supplier"), Column("invoice", "Invoice"),
        Column("total", "Goods value", "money"), Column("paid", "Paid against it", "money", True),
        Column("outstanding", "Still to pay", "money", True)], rows, period, totals,
        ["Received purchases only (stock was added). Purchases are stock, not expenses: they reach the profit & loss "
         "as cost of goods when the goods are sold.",
         "\"Paid against it\" counts supplier payments linked to the purchase; payments recorded without a purchase "
         "appear in Supplier balances."],
        chart=bar_chart(list(by_supplier), [("Purchases", list(by_supplier.values()), "online")]))


def expenses_report(period, params):
    data = (services.active_expenses(period).values("category__name").annotate(count=Count("pk"), total=Sum("amount"))
            .order_by("-total"))
    rows = [{"category": r["category__name"], "count": r["count"], "total": r["total"]} for r in data]
    method_rows = services.active_expenses(period).values("payment_method").annotate(total=Sum("amount"))
    labels = dict(PaymentMethod.choices)
    notes = ["Operating expenses only (voided entries excluded). By payment method: " +
             (", ".join(f"{labels[m['payment_method']]} LKR {m['total']:,.2f}" for m in method_rows) or "none") + "."]
    return Report("expenses", "Expenses", [Column("category", "Category"), Column("count", "Entries", "int"),
                                           Column("total", "Amount", "money")], rows, period,
                  {"category": "Total", "count": sum(r["count"] for r in rows), "total": sum((r["total"] for r in rows), ZERO)},
                  notes, chart=bar_chart([r["category"] for r in rows], [("Expenses", [r["total"] for r in rows], "expense")]))


def stock_report(period, params):
    items = (InventoryItem.objects.exclude(quantity=0, is_active=False)
             .select_related("stock_unit", "variation__product", "variation__unit").order_by("kind", "name", "pk"))
    rows, unknown = [], 0
    for item in items:
        value = (item.quantity * item.average_cost).quantize(Decimal("0.01")) if item.average_cost is not None else None
        unknown += value is None and item.quantity != 0
        rows.append({"item": item.display_name, "kind": item.get_kind_display(), "quantity": item.format_qty(item.quantity),
                     "cost": item.average_cost, "value": value})
    total = sum((r["value"] for r in rows if r["value"] is not None), ZERO)
    warnings = [f"{unknown} item(s) in stock have no known cost and are not included in the total value. "
                "Receive a purchase for them or set their cost (Finance → Stock costs)."] if unknown else []
    return Report("stock", "Stock valuation", [
        Column("item", "Item"), Column("kind", "Type"), Column("quantity", "In stock"),
        Column("cost", "Average cost per unit", "number"), Column("value", "Stock value", "money")], rows, None,
        {"item": "Total", "value": total}, ["Current stock at weighted average cost (today's values; past dates aren't stored)."],
        warnings)


# ---------------------------------------------------------------------------
# Money: cash flow, balances, profit & loss (Owner)
# ---------------------------------------------------------------------------
def _split(qs, method_field="payment_method"):
    rows = qs.values(method_field).annotate(total=Sum("amount"))
    cash = sum((r["total"] for r in rows if r[method_field] == "CASH"), ZERO)
    return cash, sum((r["total"] for r in rows if r[method_field] != "CASH"), ZERO)


def cash_flow_report(period, params):
    received = services.received_payments(period)
    labels = {"CASH": "Customer payments: cash", "BANK_TRANSFER": "Customer payments: bank transfer",
              "ONLINE": "Customer payments: online"}
    rows = []
    for method, label in labels.items():
        amount = received.filter(method=method).aggregate(s=Sum("amount"))["s"] or ZERO
        rows.append({"item": label, "cash": amount if method == "CASH" else ZERO, "bank": ZERO if method == "CASH" else amount,
                     "total": amount, "_style": ""})
    inflow = {"cash": sum((r["cash"] for r in rows), ZERO), "bank": sum((r["bank"] for r in rows), ZERO)}
    rows.append({"item": "Money in", "cash": inflow["cash"], "bank": inflow["bank"], "total": inflow["cash"] + inflow["bank"],
                 "_style": "subtotal"})
    outs = [("Refunds to customers", _split(services.refunds_paid(period), "method")),
            ("Payments to suppliers", _split(services.active_supplier_payments(period))),
            ("Operating expenses", _split(services.active_expenses(period)))]
    out_cash = out_bank = ZERO
    for label, (cash, bank) in outs:
        rows.append({"item": label, "cash": -cash, "bank": -bank, "total": -(cash + bank), "_style": ""})
        out_cash, out_bank = out_cash + cash, out_bank + bank
    rows.append({"item": "Money out", "cash": -out_cash, "bank": -out_bank, "total": -(out_cash + out_bank), "_style": "subtotal"})
    net = {"cash": inflow["cash"] - out_cash, "bank": inflow["bank"] - out_bank}
    return Report("cash-flow", "Cash flow", [Column("item", ""), Column("cash", "Cash", "money"),
                                             Column("bank", "Bank, online & other", "money"), Column("total", "Total", "money")],
                  rows, period, {"item": "Net cash flow", "cash": net["cash"], "bank": net["bank"], "total": net["cash"] + net["bank"]},
                  ["Money actually received and paid in the period, by date. Sales not yet paid and purchases not yet paid "
                   "are not cash flow.", "Cash moved into or out of POS drawers (float, bank deposits) is a transfer inside "
                   "the business, so it is not shown here; see the POS shift pages."])


def supplier_balances_report(period, params):
    until = period.end
    rows = []
    for supplier in Supplier.objects.order_by("name"):
        purchased, paid, balance = services.supplier_balance(supplier, until=until)
        if purchased or paid:
            rows.append({"supplier": supplier.name, "purchased": purchased, "paid": paid, "balance": balance,
                         "_url_key": supplier.pk})
    totals = {"supplier": "Total", **{k: sum((r[k] for r in rows), ZERO) for k in ("purchased", "paid", "balance")}}
    return Report("supplier-balances", "Supplier balances", [
        Column("supplier", "Supplier"), Column("purchased", "Received purchases", "money"), Column("paid", "Paid", "money"),
        Column("balance", "Balance owed", "money")], rows, period, totals,
        [f"All purchases received and payments made up to {until:%d %b %Y}."],
        chart=bar_chart([r["supplier"] for r in rows], [("Owed", [r["balance"] for r in rows], "expense")]))


def customer_balances_report(period, params):
    open_orders = Order.objects.filter(created_at__date__lte=period.end).exclude(CANCELLED & ~Q(payment_status=PS.REFUND_DUE))
    data = (open_orders.filter(payment_status__in=[PS.PENDING, PS.PENDING_VERIFICATION, PS.REFUND_DUE])
            .values("customer__email", "customer__first_name", "customer__last_name", "channel")
            .annotate(unpaid_count=Count("pk", filter=Q(payment_status__in=[PS.PENDING, PS.PENDING_VERIFICATION])),
                      unpaid=Sum("total", filter=Q(payment_status__in=[PS.PENDING, PS.PENDING_VERIFICATION])),
                      verifying=Sum("total", filter=Q(payment_status=PS.PENDING_VERIFICATION)),
                      refund_due=Sum("total", filter=Q(payment_status=PS.REFUND_DUE)))
            .order_by("-unpaid"))
    rows = []
    for r in data:
        name = (_person(r["customer__first_name"], r["customer__last_name"], r["customer__email"])
                if r["customer__email"] else "Walk-in customers (POS)")
        rows.append({"customer": name, "email": r["customer__email"] or "—", "unpaid_count": r["unpaid_count"],
                     "unpaid": _v(r["unpaid"]), "verifying": _v(r["verifying"]), "refund_due": _v(r["refund_due"])})
    totals = {"customer": "Total", "unpaid_count": sum(r["unpaid_count"] for r in rows),
              **{k: sum((r[k] for r in rows), ZERO) for k in ("unpaid", "verifying", "refund_due")}}
    return Report("customer-balances", "Customer balances", [
        Column("customer", "Customer"), Column("email", "Email"), Column("unpaid_count", "Unpaid orders", "int"),
        Column("unpaid", "Awaiting payment", "money"), Column("verifying", "of which transfers to check", "money"),
        Column("refund_due", "Refunds owed to customer", "money")], rows, period, totals,
        [f"Orders placed up to {period.end:%d %b %Y} that are still unpaid, and cancelled paid orders not yet refunded."])


def profit_loss_report(period, params):
    s = services.summary(period)
    by_category = (services.active_expenses(period).values("category__name").annotate(total=Sum("amount"))
                   .order_by("category__name"))
    rows = [
        {"item": "Revenue", "amount": None, "_style": "heading"},
        {"item": "Product sales", "amount": s.gross_sales, "_style": ""},
        {"item": "Less: discounts", "amount": -s.discounts, "_style": ""},
        {"item": "Delivery fees", "amount": s.delivery_income, "_style": ""},
        {"item": "Total revenue", "amount": s.revenue, "_style": "subtotal"},
        {"item": "Cost of goods sold", "amount": -s.cogs, "_style": ""},
        {"item": "Gross profit", "amount": s.gross_profit, "_style": "subtotal"},
        {"item": "Operating expenses", "amount": None, "_style": "heading"},
        *[{"item": r["category__name"], "amount": -r["total"], "_style": "indent"} for r in by_category],
        {"item": "Total operating expenses", "amount": -s.expenses, "_style": "subtotal"},
    ]
    warnings = []
    if s.uncosted_lines:
        warnings.append(f"{s.uncosted_lines} sold line(s) worth LKR {s.uncosted_revenue:,.2f} have no recorded cost (sold "
                        "before a cost was known). Their revenue is included but their cost is not, so gross profit is "
                        "overstated by that cost.")
    notes = ["Revenue = paid sales in the period, by order date (cancelled and refunded sales excluded; each counted once).",
             f"Stock purchases (LKR {s.purchases:,.2f} received in this period) are not expenses; they reach this report "
             "as cost of goods sold when the goods are sold.",
             "Net operating profit is before tax and any owner drawings; tax is not calculated by this system."]
    if s.unpaid_orders:
        notes.append(f"Orders placed but not yet paid (LKR {s.unpaid_orders:,.2f}) are not included.")
    return Report("profit-loss", "Profit & loss", [Column("item", ""), Column("amount", "LKR", "money")], rows, period,
                  {"item": "Net operating profit", "amount": s.net_operating_profit}, notes, warnings)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass
class ReportType:
    slug: str
    title: str
    description: str
    capability: str
    build: object
    uses_period: bool = True
    group: str = "Sales"


OPS, FIN = Capability.VIEW_OPERATIONAL_REPORTS, Capability.VIEW_FINANCE
REPORT_TYPES = [
    ReportType("sales", "Sales (daily / monthly / yearly)", "Revenue by day, month or year, online and in store.", OPS, sales_report),
    ReportType("products", "Product sales", "Quantities and sales per product size.", OPS, products_report),
    ReportType("categories", "Category sales", "Sales per product category.", OPS, categories_report),
    ReportType("cashiers", "Cashier sales", "In-store sales, cash and transfers per cashier.", OPS, cashiers_report),
    ReportType("purchases", "Purchases", "Goods received from suppliers.", OPS, purchases_report, group="Purchases & stock"),
    ReportType("stock", "Stock valuation", "Current stock at average cost.", OPS, stock_report, False, "Purchases & stock"),
    ReportType("expenses", "Expenses", "Operating expenses by category.", OPS, expenses_report, group="Money"),
    ReportType("profit-loss", "Profit & loss", "Revenue, cost of goods sold, expenses and profit.", FIN, profit_loss_report, group="Money"),
    ReportType("cash-flow", "Cash flow", "Money received and paid, cash and bank.", FIN, cash_flow_report, group="Money"),
    ReportType("supplier-balances", "Supplier balances", "What the business owes each supplier.", FIN,
               supplier_balances_report, group="Money"),
    ReportType("customer-balances", "Customer balances", "Unpaid orders and refunds owed.", FIN, customer_balances_report,
               group="Money"),
]
REPORTS = {r.slug: r for r in REPORT_TYPES}

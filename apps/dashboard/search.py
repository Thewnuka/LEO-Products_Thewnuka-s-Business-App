"""
Staff-wide search: one box that looks through the areas the user is allowed to see.
Each group is only searched when the user's role has the matching capability, and every
result links to a page that checks permissions again.
"""
from dataclasses import dataclass, field

from django.db.models import Q
from django.urls import reverse

from apps.accounts.roles import Capability as C
from apps.accounts.roles import Role, has_capability

LIMIT = 8


@dataclass
class Group:
    title: str
    icon: str
    results: list = field(default_factory=list)   # (title, detail, url)
    more_url: str = ""


def search_everything(user, q):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    groups = []
    can = lambda cap: has_capability(user, cap)  # noqa: E731

    if can(C.VIEW_ORDERS):
        from apps.orders.models import Order

        orders = (Order.objects.filter(channel=Order.Channel.ONLINE)
                  .filter(Q(number__icontains=q) | Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
                  .order_by("-created_at")[:LIMIT])
        groups.append(Group("Online orders", "bag-check", [
            (o.number, f"{o.full_name} · {o.get_status_display()} · LKR {o.total:,.2f}", o.get_staff_url()) for o in orders],
            reverse("orders:staff_list") + f"?q={q}"))
        from apps.payments.models import Payment

        payments = (Payment.objects.filter(Q(reference__icontains=q) | Q(bank_reference__icontains=q)
                                           | Q(transaction_id__icontains=q)).select_related("order")
                    .order_by("-created_at")[:LIMIT])
        if not can(C.VIEW_POS_SALES):
            payments = [p for p in payments if not p.order.is_pos or p.order.cashier_id == user.pk]
        groups.append(Group("Payments", "credit-card", [
            (p.reference, f"{p.get_method_display()} · {p.get_status_display()} · {p.order.number}", p.order.get_staff_url())
            for p in payments]))

    if can(C.VIEW_POS_SALES) or can(C.VIEW_OWN_TRANSACTIONS):
        from apps.pos.services import visible_sales

        sales = visible_sales(user).filter(Q(number__icontains=q) | Q(full_name__icontains=q)).order_by("-created_at")[:LIMIT]
        groups.append(Group("Till sales", "receipt", [
            (s.number, f"{s.created_at:%d %b %Y} · LKR {s.total:,.2f}", reverse("pos:sale_detail", args=[s.number]))
            for s in sales], reverse("pos:sales") + f"?q={q}"))

    if can(C.MANAGE_CATALOG):
        from apps.catalog.models import Product

        products = (Product.objects.filter(Q(name__icontains=q) | Q(variations__sku__icontains=q)).distinct()
                    .select_related("category").order_by("name")[:LIMIT])
        groups.append(Group("Products", "box-seam", [
            (p.name, f"{p.category} · {p.get_status_display()}", reverse("catalog:product_detail", args=[p.pk]))
            for p in products], reverse("catalog:product_list") + f"?q={q}"))

    if can(C.MANAGE_INVENTORY):
        from apps.inventory.models import InventoryItem

        items = (InventoryItem.objects.filter(Q(name__icontains=q) | Q(variation__product__name__icontains=q)
                                              | Q(variation__sku__icontains=q))
                 .select_related("stock_unit", "variation__product", "variation__unit")[:LIMIT])
        groups.append(Group("Stock items", "boxes", [
            (i.display_name, f"{i.quantity_display} in stock", reverse("inventory:item_detail", args=[i.pk])) for i in items],
            reverse("inventory:item_list") + f"?q={q}"))

    if can(C.MANAGE_SUPPLIERS):
        from apps.inventory.models import Supplier

        suppliers = Supplier.objects.filter(Q(name__icontains=q) | Q(contact_person__icontains=q) | Q(phone__icontains=q))[:LIMIT]
        groups.append(Group("Suppliers", "truck", [
            (s.name, s.contact_person or s.phone or "", reverse("inventory:supplier_detail", args=[s.pk])) for s in suppliers]))

    if can(C.MANAGE_PURCHASES):
        from apps.inventory.models import Purchase

        purchases = (Purchase.objects.filter(Q(reference__icontains=q) | Q(invoice_number__icontains=q)
                                             | Q(supplier__name__icontains=q)).select_related("supplier")[:LIMIT])
        groups.append(Group("Purchases", "receipt-cutoff", [
            (p.reference, f"{p.supplier.name} · {p.get_status_display()} · LKR {p.total:,.2f}",
             reverse("inventory:purchase_detail", args=[p.pk])) for p in purchases]))

    if can(C.RECORD_EXPENSES):
        from apps.finance.models import Expense

        expenses = (Expense.objects.filter(Q(reference__icontains=q) | Q(description__icontains=q) | Q(paid_to__icontains=q)
                                           | Q(payment_reference__icontains=q)).select_related("category")[:LIMIT])
        groups.append(Group("Expenses", "receipt-cutoff", [
            (e.reference, f"{e.category} · {e.description} · LKR {e.amount:,.2f}{' · void' if e.is_void else ''}",
             reverse("finance:expense_detail", args=[e.pk])) for e in expenses]))

    if can(C.MANAGE_CUSTOMERS) and can(C.VIEW_ORDERS):
        from apps.accounts.models import User

        customers = (User.objects.filter(role=Role.CUSTOMER).filter(
            Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone_number__icontains=q))
            .order_by("first_name")[:LIMIT])
        groups.append(Group("Customers", "person", [
            (c.get_full_name() or c.email, c.email, reverse("orders:staff_list") + f"?q={c.email}") for c in customers]))

    if can(C.VIEW_STAFF):
        from apps.accounts.models import User

        staff = (User.objects.exclude(role=Role.CUSTOMER).filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))[:LIMIT])
        groups.append(Group("Staff accounts", "people", [
            (s.get_full_name() or s.username, s.get_role_display(), reverse("accounts:staff_detail", args=[s.pk])) for s in staff]))

    return [g for g in groups if g.results]

"""
Finance pages (staff portal, /staff/finance/).

Owner:    everything (dashboard, profit & loss, cash flow, balances, supplier payments, stock costs, audit log).
Manager:  operational reports (sales, products, categories, cashiers, purchases, stock, expenses) without
          cost/profit columns, and recording expenses.
Others:   no access. Every rule is checked here; the sidebar only hides links.
"""
import mimetypes
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin
from apps.accounts.roles import Capability, has_capability
from apps.inventory.models import InventoryItem, Purchase, Supplier

from . import exports, services
from .charts import bar_chart
from .forms import (ExpenseCategoryForm, ExpenseFilterForm, ExpenseForm, ItemCostForm, PeriodForm, SupplierPaymentForm,
                    VoidForm)
from .models import Expense, ExpenseCategory, FinanceEvent, SupplierPayment
from .reports import REPORT_TYPES, REPORTS

PAGE_SIZE = 25


def _errors(error):
    return " ".join(error.messages)


def _can_see_reports(user):
    return has_capability(user, Capability.VIEW_FINANCE) or has_capability(user, Capability.VIEW_OPERATIONAL_REPORTS)


def _query(request, drop=("page",)):
    query = request.GET.copy()
    for key in drop:
        query.pop(key, None)
    return query.urlencode()


# ---------------------------------------------------------------------------
# Dashboard and reports
# ---------------------------------------------------------------------------
def monthly_chart(months=12):
    """Revenue, cost of goods and expenses for the last `months` months (3 queries)."""
    today = timezone.localdate()
    first = today.replace(day=1)
    for _ in range(months - 1):
        first = (first.replace(day=1) - timedelta(days=1)).replace(day=1)
    period = services.Period(first, today, "")
    keys, labels = [], []
    month = first
    while month <= today:
        keys.append((month.year, month.month))
        labels.append(month.strftime("%b %y"))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)

    def by_month(qs, date_field, value_field):
        rows = qs.annotate(m=TruncMonth(date_field)).values("m").annotate(s=Sum(value_field))
        found = {(r["m"].year, r["m"].month): r["s"] or 0 for r in rows}
        return [found.get(k, 0) for k in keys]

    revenue = by_month(services.recognised_orders(period), "created_at", "total")
    cogs = by_month(services.sold_lines(period), "order__created_at", "cost_total")
    expenses = by_month(services.active_expenses(period), "expense_date", "amount")
    return bar_chart(labels, [("Revenue", revenue, "online"), ("Cost of goods", cogs, "pos"), ("Expenses", expenses, "expense")])


class FinanceDashboardView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_FINANCE
    template_name = "finance/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        period = services.period_from(self.request.GET)
        ctx.update(period=period, period_form=PeriodForm(self.request.GET or {"period": period.preset}),
                   s=services.summary(period), chart=monthly_chart(), report_types=REPORT_TYPES)
        return ctx


class ReportsIndexView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_STAFF_PORTAL
    template_name = "finance/reports_index.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _can_see_reports(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        groups = {}
        for report in REPORT_TYPES:
            if has_capability(self.request.user, report.capability):
                groups.setdefault(report.group, []).append(report)
        ctx["groups"] = groups
        return ctx


class ReportView(CapabilityRequiredMixin, View):
    """One view for every report: page, ?export=csv|xlsx, ?print=1 (A4)."""

    required_capability = Capability.VIEW_STAFF_PORTAL

    def get(self, request, slug):
        report_type = REPORTS.get(slug)
        if report_type is None:
            raise Http404
        if not has_capability(request.user, report_type.capability):
            raise PermissionDenied
        period = services.period_from(request.GET)
        report = report_type.build(period, request.GET)
        show_financial = has_capability(request.user, Capability.VIEW_FINANCE)
        columns = report.visible_columns(show_financial)
        if show_financial:
            report.notes += report.finance_notes
        export = request.GET.get("export")
        if export in ("csv", "xlsx"):
            services.log("report_exported", request.user, report.title, format=export,
                         period=report.period.label if report.period else "current")
            return (exports.csv_response if export == "csv" else exports.xlsx_response)(report, columns)
        template = "finance/report_print.html" if request.GET.get("print") == "1" else "finance/report.html"
        return render(request, template, {
            "report": report, "report_type": report_type, "columns": columns, "rows": exports_rows(report, columns),
            "totals": [(c, report.totals.get(c.key)) for c in columns] if report.totals else None,
            "period_form": PeriodForm(request.GET or {"period": period.preset}) if report_type.uses_period else None,
            "query": _query(request, drop=("export", "print")), "printed_at": timezone.localtime(),
        })


def exports_rows(report, columns):
    """Rows as [(column, value)] lists for the template (keeps column order and visibility)."""
    out = []
    for row in report.rows:
        out.append({"cells": [(c, row.get(c.key)) for c in columns], "style": row.get("_style", "")})
    return out


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
class ExpenseListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.RECORD_EXPENSES
    template_name = "finance/expense_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET
        period = services.period_from(params)
        form = ExpenseFilterForm(params or {"period": period.preset})
        expenses = Expense.objects.select_related("category", "created_by").filter(
            expense_date__gte=period.start, expense_date__lte=period.end)
        status = params.get("status", "")
        if status == "VOID":
            expenses = expenses.filter(status=Expense.Status.VOID)
        elif status != "ALL":
            expenses = expenses.filter(status=Expense.Status.RECORDED)
        if form.is_valid():
            if form.cleaned_data.get("category"):
                expenses = expenses.filter(category=form.cleaned_data["category"])
            if form.cleaned_data.get("payment_method"):
                expenses = expenses.filter(payment_method=form.cleaned_data["payment_method"])
        total = expenses.filter(status=Expense.Status.RECORDED).aggregate(s=Sum("amount"))["s"] or 0
        ctx.update(filter_form=form, period=period, total=total, querystring=_query(self.request),
                   page_obj=Paginator(expenses.order_by("-expense_date", "-pk"), PAGE_SIZE).get_page(params.get("page")))
        return ctx


class ExpenseCreateView(CapabilityRequiredMixin, View):
    required_capability = Capability.RECORD_EXPENSES
    template_name = "finance/expense_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": ExpenseForm()})

    def post(self, request):
        form = ExpenseForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        d = form.cleaned_data
        try:
            expense, created = services.record_expense(
                request.user, d["token"], category=d["category"], expense_date=d["expense_date"], amount=d["amount"],
                payment_method=d["payment_method"], description=d["description"], paid_to=d["paid_to"],
                payment_reference=d["payment_reference"], receipt=d.get("receipt"))
        except ValidationError as error:
            form.add_error(None, _errors(error))
            return render(request, self.template_name, {"form": form})
        if created:
            messages.success(request, f"Expense {expense.reference} recorded: LKR {expense.amount:,.2f}.")
        return redirect("finance:expense_detail", pk=expense.pk)


class ExpenseDetailView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.RECORD_EXPENSES
    template_name = "finance/expense_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        expense = get_object_or_404(Expense.objects.select_related("category", "created_by", "voided_by"), pk=self.kwargs["pk"])
        can_void = has_capability(self.request.user, Capability.MANAGE_FINANCE) and not expense.is_void
        ctx.update(expense=expense, void_form=VoidForm() if can_void else None)
        return ctx


class ExpenseReceiptView(CapabilityRequiredMixin, View):
    required_capability = Capability.RECORD_EXPENSES

    def get(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        if not expense.receipt:
            raise Http404
        content_type = expense.receipt_content_type or mimetypes.guess_type(expense.receipt.name)[0] or "application/octet-stream"
        response = FileResponse(expense.receipt.open("rb"), content_type=content_type)
        disposition = "attachment" if content_type == "application/pdf" else "inline"  # PDFs download
        response["Content-Disposition"] = f'{disposition}; filename="{expense.reference}.{expense.receipt.name.rsplit(".", 1)[-1]}"'
        response["Cache-Control"] = "private, no-store"
        return response


class VoidView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_FINANCE
    http_method_names = ["post"]
    model = None

    def success_url(self, record):
        raise NotImplementedError

    def post(self, request, pk):
        record = get_object_or_404(self.model, pk=pk)
        form = VoidForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please give a reason for voiding.")
        else:
            try:
                services.void_record(record, request.user, form.cleaned_data["reason"])
            except ValidationError as error:
                messages.error(request, _errors(error))
            else:
                messages.success(request, f"{record.reference} voided. It stays in the records, marked void.")
        return redirect(self.success_url(record))


class ExpenseVoidView(VoidView):
    model = Expense

    def success_url(self, record):
        return reverse("finance:expense_detail", args=[record.pk])


# ---------------------------------------------------------------------------
# Expense categories (Owner)
# ---------------------------------------------------------------------------
class CategoryListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.MANAGE_FINANCE
    template_name = "finance/category_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ExpenseCategory.objects.order_by("-is_active", "name")
        return ctx


class CategoryFormMixin(CapabilityRequiredMixin):
    required_capability = Capability.MANAGE_FINANCE
    model = ExpenseCategory
    form_class = ExpenseCategoryForm
    template_name = "finance/category_form.html"

    def form_valid(self, form):
        category = form.save()
        services.log("category_saved", self.request.user, category.name, active=category.is_active)
        messages.success(self.request, f"Category “{category.name}” saved.")
        return redirect("finance:categories")


class CategoryCreateView(CategoryFormMixin, CreateView):
    pass


class CategoryUpdateView(CategoryFormMixin, UpdateView):
    context_object_name = "category"


# ---------------------------------------------------------------------------
# Supplier payments and statements (Owner)
# ---------------------------------------------------------------------------
class SupplierPaymentListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_FINANCE
    template_name = "finance/supplier_payment_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        period = services.period_from(self.request.GET, default="year")
        payments = SupplierPayment.objects.select_related("supplier", "purchase", "created_by").filter(
            payment_date__gte=period.start, payment_date__lte=period.end).order_by("-payment_date", "-pk")
        balances = []
        for supplier in Supplier.objects.order_by("name"):
            purchased, paid, balance = services.supplier_balance(supplier)
            if purchased or paid:
                balances.append((supplier, purchased, paid, balance))
        ctx.update(period=period, period_form=PeriodForm(self.request.GET or {"period": period.preset}), balances=balances,
                   querystring=_query(self.request),
                   page_obj=Paginator(payments, PAGE_SIZE).get_page(self.request.GET.get("page")))
        return ctx


class SupplierPaymentCreateView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_FINANCE
    template_name = "finance/supplier_payment_form.html"

    def get(self, request):
        initial = {}
        if request.GET.get("purchase"):
            purchase = Purchase.objects.filter(pk=request.GET["purchase"], status=Purchase.Status.RECEIVED).first()
            if purchase:
                initial = {"purchase": purchase, "supplier": purchase.supplier,
                           "amount": max(purchase.total - services.purchase_paid(purchase), 0) or None}
        elif request.GET.get("supplier"):
            initial = {"supplier": Supplier.objects.filter(pk=request.GET["supplier"]).first()}
        return render(request, self.template_name, {"form": SupplierPaymentForm(initial=initial)})

    def post(self, request):
        form = SupplierPaymentForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        d = form.cleaned_data
        try:
            payment, created = services.record_supplier_payment(
                request.user, d["token"], supplier=d["supplier"], purchase=d.get("purchase"), payment_date=d["payment_date"],
                amount=d["amount"], payment_method=d["payment_method"], payment_reference=d["payment_reference"],
                notes=d["notes"])
        except ValidationError as error:
            form.add_error(None, _errors(error))
            return render(request, self.template_name, {"form": form})
        if created:
            messages.success(request, f"Payment {payment.reference} of LKR {payment.amount:,.2f} to {payment.supplier} recorded.")
        return redirect("finance:supplier_statement", pk=payment.supplier_id)


class SupplierPaymentVoidView(VoidView):
    model = SupplierPayment

    def success_url(self, record):
        return reverse("finance:supplier_statement", args=[record.supplier_id])


class SupplierStatementView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_FINANCE
    template_name = "finance/supplier_statement.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        supplier = get_object_or_404(Supplier, pk=self.kwargs["pk"])
        entries = [(p.purchase_date, p.created_at, "purchase", p) for p in services.received_purchases().filter(supplier=supplier)]
        entries += [(p.payment_date, p.created_at, "payment", p)
                    for p in SupplierPayment.objects.filter(supplier=supplier).select_related("purchase", "created_by")]
        entries.sort(key=lambda e: (e[0], e[1]))
        balance, lines = 0, []
        for day, _created, kind, obj in entries:
            if kind == "purchase":
                balance += obj.total
            elif not obj.is_void:
                balance -= obj.amount
            lines.append({"date": day, "kind": kind, "obj": obj, "balance": balance})
        purchased, paid, owed = services.supplier_balance(supplier)
        ctx.update(supplier=supplier, lines=list(reversed(lines)), purchased=purchased, paid=paid, owed=owed,
                   can_manage=has_capability(self.request.user, Capability.MANAGE_FINANCE),
                   void_form=VoidForm())
        return ctx


# ---------------------------------------------------------------------------
# Stock costs (Owner)
# ---------------------------------------------------------------------------
class StockCostListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.MANAGE_FINANCE
    template_name = "finance/stock_costs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = InventoryItem.objects.select_related("stock_unit", "variation__product", "variation__unit").order_by("kind", "name", "pk")
        if self.request.GET.get("missing") == "1":
            items = items.filter(average_cost__isnull=True)
        ctx.update(items=items, missing=self.request.GET.get("missing") == "1",
                   missing_count=InventoryItem.objects.filter(average_cost__isnull=True, is_active=True).count())
        return ctx


class StockCostSetView(CapabilityRequiredMixin, View):
    required_capability = Capability.MANAGE_FINANCE
    template_name = "finance/stock_cost_form.html"

    def context(self, item, form):
        return {"item": item, "form": form, "history": item.cost_changes.select_related("changed_by", "purchase_line__purchase")[:50]}

    def get(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk)
        return render(request, self.template_name, self.context(item, ItemCostForm(initial={"cost": item.average_cost})))

    def post(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk)
        form = ItemCostForm(request.POST)
        if form.is_valid():
            try:
                services.set_cost(item, form.cleaned_data["cost"], request.user, form.cleaned_data["reason"])
            except ValidationError as error:
                form.add_error(None, _errors(error))
            else:
                messages.success(request, f"Cost of {item.display_name} set. Sales from now on use it; past sales keep their cost.")
                return redirect("finance:stock_cost", pk=pk)
        return render(request, self.template_name, self.context(item, form))


# ---------------------------------------------------------------------------
# Audit log (Owner)
# ---------------------------------------------------------------------------
class AuditLogView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_FINANCE
    template_name = "finance/audit_log.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        events = FinanceEvent.objects.select_related("user")
        ctx["page_obj"] = Paginator(events, 50).get_page(self.request.GET.get("page"))
        ctx["querystring"] = ""
        return ctx


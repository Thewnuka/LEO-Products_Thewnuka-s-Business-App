import io
import uuid
import zipfile
from types import SimpleNamespace

from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD
from apps.finance import exports
from apps.finance.models import Expense, FinanceEvent, SupplierPayment
from apps.finance.reports import REPORT_TYPES, Column, Report
from apps.inventory.models import InventoryItem
from apps.orders.tests.helpers import slip

from .helpers import D, FinanceTestCase


class FinanceViewTestCase(FinanceTestCase):
    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)


class AccessTests(FinanceViewTestCase):
    def test_role_matrix(self):
        expense = self.expense()
        urls = {
            "dashboard": reverse("finance:dashboard"), "reports": reverse("finance:reports"),
            "sales": reverse("finance:report", args=["sales"]), "products": reverse("finance:report", args=["products"]),
            "stock": reverse("finance:report", args=["stock"]), "pnl": reverse("finance:report", args=["profit-loss"]),
            "cash": reverse("finance:report", args=["cash-flow"]),
            "suppliers": reverse("finance:report", args=["supplier-balances"]),
            "customers": reverse("finance:report", args=["customer-balances"]),
            "expenses": reverse("finance:expenses"), "expense": reverse("finance:expense_detail", args=[expense.pk]),
            "expense_new": reverse("finance:expense_create"), "categories": reverse("finance:categories"),
            "payments": reverse("finance:supplier_payments"), "pay": reverse("finance:supplier_payment_create"),
            "statement": reverse("finance:supplier_statement", args=[self.supplier.pk]),
            "costs": reverse("finance:stock_costs"), "audit": reverse("finance:audit_log"),
        }
        manager_ok = {"reports", "sales", "products", "stock", "expenses", "expense", "expense_new"}
        for user, allowed in ((self.owner, set(urls)), (self.manager, manager_ok), (self.cashier, set()),
                              (self.it_admin, set()), (self.customer, set())):
            self.login(user)
            for name, url in urls.items():
                expected = 200 if name in allowed else 403
                self.assertEqual(self.client.get(url).status_code, expected, f"{user.username} {name}")
        self.client.logout()
        self.assertEqual(self.client.get(urls["dashboard"]).status_code, 302)
        self.assertEqual(self.client.get(reverse("finance:report", args=["nope"])).status_code, 302)

    def test_unknown_report_404(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(reverse("finance:report", args=["nope"])).status_code, 404)

    def test_write_actions_need_permission(self):
        expense = self.expense()
        self.login(self.manager)
        self.assertEqual(self.client.post(reverse("finance:expense_void", args=[expense.pk]), {"reason": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("finance:supplier_payment_create"), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("finance:stock_cost", args=[InventoryItem.objects.first().pk]),
                                          {"cost": "1", "reason": "x"}).status_code, 403)
        self.login(self.cashier)
        self.assertEqual(self.client.post(reverse("finance:expense_create"), {}).status_code, 403)
        expense.refresh_from_db()
        self.assertEqual(expense.status, "RECORDED")

    def test_manager_does_not_see_costs_or_profit(self):
        self.open()
        self.sell()
        self.login(self.manager)
        response = self.client.get(reverse("finance:report", args=["products"]))
        self.assertContains(response, "Black Tea")
        self.assertNotContains(response, "Gross profit")
        self.assertNotContains(response, "Cost of goods")
        csv = self.client.get(reverse("finance:report", args=["products"]) + "?export=csv").content.decode()
        self.assertNotIn("Gross profit", csv)
        self.login(self.owner)
        self.assertContains(self.client.get(reverse("finance:report", args=["products"])), "Gross profit")

    def test_sidebar_and_dashboard_links(self):
        self.login(self.owner)
        response = self.client.get(reverse("finance:dashboard"))
        self.assertContains(response, reverse("finance:audit_log"))
        self.login(self.manager)
        response = self.client.get(reverse("finance:reports"))
        self.assertContains(response, reverse("finance:expenses"))
        self.assertNotContains(response, reverse("finance:dashboard") + '"')
        self.assertNotContains(response, "Profit &amp; loss")


class ReportPageTests(FinanceViewTestCase):
    def setUp(self):
        super().setUp()
        self.purchase([(InventoryItem.objects.get(variation=self.b200), "10", "200")])
        self.open()
        self.sell()
        self.expense("750")
        self.login(self.owner)

    def test_every_report_renders_page_print_and_exports(self):
        for report_type in REPORT_TYPES:
            url = reverse("finance:report", args=[report_type.slug])
            for params in ("", "?period=year", "?period=custom&start=2026-01-01&end=2026-12-31", "?group=month"):
                self.assertEqual(self.client.get(url + params).status_code, 200, report_type.slug + params)
            printed = self.client.get(url + "?print=1")
            self.assertContains(printed, "leo-print-sheet")
            self.assertContains(printed, "images/leo-logo.png")
            csv = self.client.get(url + "?export=csv")
            self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
            self.assertTrue(csv.content.startswith("﻿".encode()))
            xlsx = self.client.get(url + "?export=xlsx")
            with zipfile.ZipFile(io.BytesIO(xlsx.content)) as archive:
                self.assertIn("xl/worksheets/sheet1.xml", archive.namelist())
                self.assertIn("LEO PRODUCTS", archive.read("xl/worksheets/sheet1.xml").decode())
        self.assertEqual(FinanceEvent.objects.filter(action="report_exported").count(), 2 * len(REPORT_TYPES))

    def test_dashboard_figures(self):
        response = self.client.get(reverse("finance:dashboard") + "?period=today")
        s = response.context["s"]
        self.assertEqual((s.revenue, s.cogs, s.expenses), (D("1300"), D("400"), D("750")))
        self.assertContains(response, "1,300.00")
        self.assertContains(response, "<svg")
        self.assertContains(response, "without cost")  # Kokis sold with no cost known

    def test_profit_loss_page(self):
        response = self.client.get(reverse("finance:report", args=["profit-loss"]) + "?period=today")
        self.assertContains(response, "Net operating profit")
        self.assertContains(response, "no recorded cost")


class ExportSafetyTests(FinanceTestCase):
    def test_formula_injection_is_neutralised_and_numbers_stay_numbers(self):
        report = Report("x", "Test", [Column("name", "Name"), Column("amount", "Amount", "money")],
                        [{"name": "=HYPERLINK(\"http://evil\")", "amount": D("12.50")}, {"name": "+1", "amount": D("-3")}],
                        SimpleNamespace(start=self.today(), end=self.today(), label="today"),
                        totals={"name": "Total", "amount": D("9.50")})
        header, body = exports.table(report, report.columns)
        self.assertEqual(body[0][0], "'=HYPERLINK(\"http://evil\")")
        self.assertEqual(body[1][0], "'+1")
        self.assertEqual(body[0][1], D("12.50"))
        sheet = zipfile.ZipFile(io.BytesIO(exports.xlsx_bytes(report, report.columns))).read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<v>12.50</v>", sheet)
        self.assertIn("&apos;=HYPERLINK" if "&apos;" in sheet else "'=HYPERLINK", sheet)


class ExpensePageTests(FinanceViewTestCase):
    def test_manager_records_expense_once_with_receipt(self):
        self.login(self.manager)
        form = self.client.get(reverse("finance:expense_create")).context["form"]
        token = form.initial["token"]
        data = {"token": token, "expense_date": self.today().isoformat(), "category": self.transport.pk, "amount": "1200",
                "payment_method": "CASH", "description": "Delivery van fuel"}
        response = self.client.post(reverse("finance:expense_create"), {**data, "receipt": slip()})
        expense = Expense.objects.get()
        self.assertRedirects(response, reverse("finance:expense_detail", args=[expense.pk]))
        self.client.post(reverse("finance:expense_create"), {**data, "receipt": slip()})   # double submit
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(expense.created_by, self.manager)
        receipt = self.client.get(reverse("finance:expense_receipt", args=[expense.pk]))
        self.assertEqual(receipt["Content-Type"], "image/png")
        self.assertIn("no-store", receipt["Cache-Control"])
        receipt.close()
        self.login(self.cashier)
        self.assertEqual(self.client.get(reverse("finance:expense_receipt", args=[expense.pk])).status_code, 403)

    def test_form_errors(self):
        self.login(self.owner)
        response = self.client.post(reverse("finance:expense_create"), {
            "token": str(uuid.uuid4()), "expense_date": "2999-01-01", "category": self.transport.pk, "amount": "-1",
            "payment_method": "CASH", "description": ""})
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        for field in ("expense_date", "amount", "description"):
            self.assertIn(field, errors)
        self.assertFalse(Expense.objects.exists())

    def test_owner_voids_and_lists(self):
        expense = self.expense("300")
        self.login(self.owner)
        self.client.post(reverse("finance:expense_void", args=[expense.pk]), {"reason": "Duplicate"}, follow=True)
        expense.refresh_from_db()
        self.assertTrue(expense.is_void)
        listing = self.client.get(reverse("finance:expenses"))
        self.assertNotContains(listing, expense.reference)
        self.assertContains(self.client.get(reverse("finance:expenses") + "?status=VOID"), expense.reference)

    def test_categories(self):
        self.login(self.owner)
        self.client.post(reverse("finance:category_create"), {"name": "Insurance", "is_active": "on"})
        self.assertTrue(FinanceEvent.objects.filter(action="category_saved", object_ref="Insurance").exists())


class SupplierPageTests(FinanceViewTestCase):
    def setUp(self):
        super().setUp()
        self.po = self.purchase([(InventoryItem.objects.get(variation=self.k10), "10", "150")])
        self.login(self.owner)

    def test_pay_from_purchase_and_statement(self):
        page = self.client.get(reverse("finance:supplier_payment_create") + f"?purchase={self.po.pk}")
        form = page.context["form"]
        self.assertEqual(form.initial["amount"], D("1500.00"))
        response = self.client.post(reverse("finance:supplier_payment_create"), {
            "token": form.initial["token"], "supplier": self.supplier.pk, "purchase": self.po.pk,
            "payment_date": self.today().isoformat(), "amount": "1500", "payment_method": "BANK_TRANSFER"})
        self.assertRedirects(response, reverse("finance:supplier_statement", args=[self.supplier.pk]))
        statement = self.client.get(response["Location"])
        self.assertEqual(statement.context["owed"], D("0"))
        detail = self.client.get(reverse("inventory:purchase_detail", args=[self.po.pk]))
        self.assertEqual(detail.context["outstanding"], D("0"))
        payment = SupplierPayment.objects.get()
        self.client.post(reverse("finance:supplier_payment_void", args=[payment.pk]), {"reason": "Bounced"})
        payment.refresh_from_db()
        self.assertTrue(payment.is_void)

    def test_overpayment_shows_error(self):
        response = self.client.post(reverse("finance:supplier_payment_create"), {
            "token": str(uuid.uuid4()), "supplier": self.supplier.pk, "payment_date": self.today().isoformat(),
            "amount": "5000", "payment_method": "CASH"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "owed only")
        self.assertFalse(SupplierPayment.objects.exists())

    def test_manager_sees_no_payment_figures_on_purchase(self):
        self.login(self.manager)
        detail = self.client.get(reverse("inventory:purchase_detail", args=[self.po.pk]))
        self.assertNotIn("outstanding", detail.context)
        self.assertNotContains(detail, "Record payment")


class StockCostPageTests(FinanceViewTestCase):
    def test_owner_sets_cost(self):
        item = InventoryItem.objects.get(variation=self.k10)
        self.login(self.owner)
        self.assertContains(self.client.get(reverse("finance:stock_costs") + "?missing=1"), item.display_name)
        response = self.client.post(reverse("finance:stock_cost", args=[item.pk]), {"cost": "95.5", "reason": "Costing sheet"})
        self.assertRedirects(response, reverse("finance:stock_cost", args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.average_cost, D("95.5000"))
        self.assertContains(self.client.get(response["Location"]), "Costing sheet")

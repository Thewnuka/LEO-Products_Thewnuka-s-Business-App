import uuid
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError

from apps.catalog.models import Unit
from apps.finance import services
from apps.finance.models import Expense, ExpenseCategory, FinanceEvent, SupplierPayment
from apps.inventory.models import InventoryItem, ItemCostChange
from apps.inventory.tests.helpers import raw_item
from apps.orders import services as orders
from apps.orders.tests.helpers import PM, slip
from apps.payments import services as payments
from apps.pos import services as pos

from .helpers import D, FinanceTestCase


class AverageCostTests(FinanceTestCase):
    def item(self, variation):
        return InventoryItem.objects.get(variation=variation)

    def test_first_purchase_sets_cost_then_weighted_average(self):
        item = self.item(self.b200)  # opening stock 10, no cost known
        self.assertIsNone(item.average_cost)
        self.purchase([(item, "10", "300")])
        item.refresh_from_db()
        self.assertEqual(item.average_cost, D("300.0000"))
        change = ItemCostChange.objects.get(item=item)
        self.assertEqual((change.source, change.old_cost, change.quantity_before, change.quantity_added),
                         ("PURCHASE", None, D("10"), D("10")))
        self.purchase([(item, "10", "360")])   # 20 @ 300 + 10 @ 360
        item.refresh_from_db()
        self.assertEqual(item.average_cost, D("320.0000"))
        self.assertEqual(item.cost_changes.count(), 2)

    def test_unit_conversion_for_raw_materials(self):
        kg, g = Unit.objects.get(symbol="kg"), Unit.objects.get(symbol="g")
        leaves = raw_item("Tea leaves", kg, self.owner)
        self.purchase([(leaves, "500", "2", g)])   # 500 g at LKR 2/g = LKR 1,000 for 0.5 kg
        leaves.refresh_from_db()
        self.assertEqual(leaves.average_cost, D("2000.0000"))

    def test_sale_copies_cost_and_never_backfills(self):
        self.open()
        before = self.sell(lines=[(self.b200.pk, 1)])      # no cost known yet
        line = before.items.get()
        self.assertIsNone(line.unit_cost)
        self.assertIsNone(line.cost_total)
        self.purchase([(self.item(self.b200), "10", "250")])
        after = self.sell(lines=[(self.b200.pk, 2)])
        line2 = after.items.get()
        self.assertEqual((line2.unit_cost, line2.cost_total), (D("250.0000"), D("500.00")))
        line.refresh_from_db()
        self.assertIsNone(line.cost_total)                  # old sale left as it was
        online = self.place(lines=[(self.b200, 1)])
        self.assertEqual(online.items.get().cost_total, D("250.00"))

    def test_owner_sets_cost_with_audit(self):
        item = self.item(self.k10)
        with self.assertRaises(ValidationError):
            services.set_cost(item, D("50"), self.owner, " ")
        with self.assertRaises(ValidationError):
            services.set_cost(item, D("-1"), self.owner, "x")
        services.set_cost(item, D("120"), self.owner, "Production cost sheet")
        item.refresh_from_db()
        self.assertEqual(item.average_cost, D("120.0000"))
        change = item.cost_changes.get()
        self.assertEqual((change.source, change.changed_by, change.reason), ("MANUAL", self.owner, "Production cost sheet"))
        self.assertTrue(FinanceEvent.objects.filter(action="item_cost_set").exists())
        with self.assertRaises(ValidationError):
            services.set_cost(item, D("120"), self.owner, "same")

    def test_cost_history_cannot_be_deleted(self):
        services.set_cost(self.item(self.k10), D("120"), self.owner, "x")
        with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic():
            ItemCostChange.objects.all().delete()


class ExpenseTests(FinanceTestCase):
    def test_record_and_void_once(self):
        expense = self.expense("2500.50", method="BANK_TRANSFER", paid_to="CEB", payment_reference="BILL-1")
        self.assertTrue(expense.reference.startswith(f"EXP-{self.today().year}-"))
        self.assertEqual((expense.amount, expense.status, expense.created_by), (D("2500.50"), "RECORDED", self.owner))
        with self.assertRaises(ValidationError):
            services.void_record(expense, self.owner, " ")
        services.void_record(expense, self.owner, "Entered twice")
        expense.refresh_from_db()
        self.assertEqual((expense.status, expense.voided_by), ("VOID", self.owner))
        with self.assertRaises(ValidationError):
            services.void_record(expense, self.owner, "again")
        self.assertEqual(list(FinanceEvent.objects.values_list("action", flat=True).order_by("pk")),
                         ["expense_recorded", "expense_voided"])

    def test_same_token_records_once(self):
        token = uuid.uuid4()
        args = dict(category=self.transport, expense_date=self.today(), amount=D("100"), payment_method="CASH", description="x")
        first, created = services.record_expense(self.owner, token, **args)
        again, created_again = services.record_expense(self.owner, token, **args)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Expense.objects.count(), 1)

    def test_validation(self):
        inactive = ExpenseCategory.objects.create(name="Old", is_active=False)
        bad = [dict(category=inactive), dict(amount="0"), dict(amount="-5"), dict(method="BITCOIN"),
               dict(expense_date=self.today() + timedelta(days=1))]
        for overrides in bad:
            with self.assertRaises(ValidationError, msg=overrides):
                self.expense(**{"amount": "100", **overrides})
        self.assertFalse(Expense.objects.exists())

    def test_receipt_is_validated_and_private(self):
        expense = self.expense(receipt=slip())
        self.assertTrue(expense.receipt.name.startswith("expense-receipts/"))
        self.assertEqual(expense.receipt_content_type, "image/png")
        from django.core.files.uploadedfile import SimpleUploadedFile

        with self.assertRaises(ValidationError):
            self.expense(receipt=SimpleUploadedFile("x.png", b"not an image"))

    def test_records_cannot_be_deleted(self):
        expense = self.expense()
        for target in (lambda: expense.delete(), lambda: Expense.objects.all().delete(),
                       lambda: self.transport.delete(), lambda: FinanceEvent.objects.all().delete()):
            with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic():
                target()
        self.assertTrue(Expense.objects.filter(pk=expense.pk).exists())


class SupplierPaymentTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.po = self.purchase([(InventoryItem.objects.get(variation=self.k10), "10", "150")])   # LKR 1,500

    def test_balance_and_payments(self):
        self.assertEqual(services.supplier_balance(self.supplier), (D("1500.00"), D("0"), D("1500.00")))
        payment = self.pay_supplier("1000", purchase=self.po)
        self.assertTrue(payment.reference.startswith("SP-"))
        self.assertEqual(services.supplier_balance(self.supplier)[2], D("500.00"))
        self.assertEqual(services.purchase_paid(self.po), D("1000"))
        with self.assertRaises(ValidationError):   # more than left on the purchase
            self.pay_supplier("600", purchase=self.po)
        with self.assertRaises(ValidationError):   # more than owed overall
            self.pay_supplier("501")
        services.void_record(payment, self.owner, "Bounced cheque")
        self.assertEqual(services.supplier_balance(self.supplier)[2], D("1500.00"))

    def test_rules(self):
        with self.assertRaises(ValidationError):   # nothing owed to supplier2
            self.pay_supplier("1", supplier=self.supplier2)
        with self.assertRaises(ValidationError):   # purchase of another supplier
            self.pay_supplier("1", supplier=self.supplier2, purchase=self.po)
        draft = self.purchase([(InventoryItem.objects.get(variation=self.k10), "1", "100")], receive=False)
        with self.assertRaises(ValidationError):   # not received
            self.pay_supplier("1", purchase=draft)
        token = uuid.uuid4()
        first = self.pay_supplier("100", token=token)
        second = self.pay_supplier("100", token=token)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SupplierPayment.objects.count(), 1)

    def test_draft_purchases_are_not_owed(self):
        self.purchase([(InventoryItem.objects.get(variation=self.k10), "1", "100")], receive=False)
        self.assertEqual(services.supplier_balance(self.supplier)[0], D("1500.00"))


class FiguresTests(FinanceTestCase):
    """One period with every kind of transaction; each figure must be counted exactly once."""

    def setUp(self):
        super().setUp()
        self.purchase([(InventoryItem.objects.get(variation=self.b200), "10", "200"),
                       (InventoryItem.objects.get(variation=self.k10), "10", "100")])     # purchases 3,000
        self.open()
        # POS cash: 2 × 500 + 1 × 300 = 1,300, 10% discount (manager) -> 1,170; COGS 400 + 100 = 500
        self.pos_cash = self.sell(discount_type="PERCENT", discount_value="10", discount_reason="Promo", approver=self.manager)
        # POS bank transfer, approved: 300; COGS 100
        bank = self.sell(method="BANK_TRANSFER", lines=[(self.k10.pk, 1)])
        payments.review_bank_transfer(bank.payments.get(), self.manager, approve=True)
        # POS bank transfer not yet verified: not revenue
        self.sell(method="BANK_TRANSFER", lines=[(self.k10.pk, 2)])
        # POS sale refunded: not revenue; cash in and out
        refunded = self.sell(lines=[(self.k10.pk, 1)])
        pos.refund_sale(refunded, self.owner, "Damaged", drawer_shift=refunded.shift)
        # Online delivery order paid in cash: 500 + 350 fee = 850; COGS 200
        online = self.place(fulfilment="DELIVERY", lines=[(self.b200, 1)])
        payments.record_cash_payment(online, self.cashier)
        # Online order not paid: not revenue
        self.unpaid = self.place(method=PM.BANK_TRANSFER, lines=[(self.k10, 1)])
        # Expenses: 1,000 cash + 400 bank; one voided
        self.expense("1000")
        self.expense("400", category=self.utilities, method="BANK_TRANSFER")
        services.void_record(self.expense("999"), self.owner, "Mistake")
        self.pay_supplier("2000", method="CASH")

    def test_summary(self):
        s = services.summary(self.period())
        self.assertEqual(s.sales_count, 3)
        self.assertEqual((s.gross_sales, s.discounts, s.delivery_income, s.revenue),
                         (D("2100"), D("130"), D("350"), D("2320")))
        self.assertEqual(s.revenue, s.gross_sales - s.discounts + s.delivery_income)
        self.assertEqual((s.cogs, s.uncosted_lines), (D("800"), 0))
        self.assertEqual((s.gross_profit, s.expenses, s.net_operating_profit), (D("1520"), D("1400"), D("120")))
        self.assertEqual(s.purchases, D("3000"))
        # Collections: cash 1,170 + 300 (refunded sale, received then paid back) + 850; bank 300
        self.assertEqual((s.cash_in, s.bank_in), (D("2320"), D("300")))
        self.assertEqual(s.unpaid_orders, D("900"))   # 600 unverified till transfer + 300 unpaid online

    def test_profit_and_loss_report(self):
        from apps.finance.reports import profit_loss_report

        report = profit_loss_report(self.period(), {})
        amounts = {r["item"]: r["amount"] for r in report.rows}
        self.assertEqual(amounts["Total revenue"], D("2320"))
        self.assertEqual(amounts["Cost of goods sold"], D("-800"))
        self.assertEqual(amounts["Gross profit"], D("1520"))
        self.assertEqual(amounts["Transport & delivery"], D("-1000"))
        self.assertEqual(amounts["Utilities"], D("-400"))
        self.assertEqual(report.totals["amount"], D("120"))
        self.assertFalse(report.warnings)

    def test_cash_flow_counts_money_once(self):
        from apps.finance.reports import cash_flow_report

        report = cash_flow_report(self.period(), {})
        rows = {r["item"]: r for r in report.rows}
        self.assertEqual(rows["Money in"]["total"], D("2620"))
        self.assertEqual(rows["Refunds to customers"]["cash"], D("-300"))
        self.assertEqual(rows["Payments to suppliers"]["cash"], D("-2000"))
        self.assertEqual((rows["Operating expenses"]["cash"], rows["Operating expenses"]["bank"]), (D("-1000"), D("-400")))
        self.assertEqual(report.totals["total"], D("2620") - D("300") - D("2000") - D("1400"))

    def test_uncosted_sales_are_flagged_not_invented(self):
        self.sell(lines=[(self.g25.pk, 1)])   # no cost known for tea bags
        s = services.summary(self.period())
        self.assertEqual((s.uncosted_lines, s.uncosted_revenue, s.cogs), (1, D("450"), D("800")))
        from apps.finance.reports import profit_loss_report, products_report

        self.assertTrue(profit_loss_report(self.period(), {}).warnings)
        row = next(r for r in products_report(self.period(), {}).rows if r["sku"] == self.g25.sku)
        self.assertEqual((row["revenue"], row["cost"], row["uncosted"], row["profit"]), (D("450"), D("0"), D("450"), D("0")))

    def test_other_reports(self):
        from apps.finance import reports

        sales = reports.sales_report(self.period(), {"group": "day"})
        self.assertEqual(sales.totals["revenue"], D("2320"))
        self.assertEqual((sales.totals["online"], sales.totals["pos"]), (D("850"), D("1470")))
        cats = {r["category"]: r for r in reports.categories_report(self.period(), {}).rows}
        self.assertEqual(cats["LEO TEA"]["qty"], 3)
        cashiers = reports.cashiers_report(self.period(), {}).rows[0]
        self.assertEqual((cashiers["sales"], cashiers["cash"], cashiers["bank"], cashiers["pending"], cashiers["voided"]),
                         (3, D("1170"), D("300"), D("600"), 1))
        purchases = reports.purchases_report(self.period(), {})
        self.assertEqual((purchases.totals["total"], purchases.totals["outstanding"]), (D("3000"), D("3000")))
        balances = reports.supplier_balances_report(self.period(), {})
        self.assertEqual(balances.rows[0]["balance"], D("1000"))
        customers = reports.customer_balances_report(self.period(), {})
        self.assertEqual(customers.totals["unpaid"], D("900"))
        stock = reports.stock_report(None, {})
        self.assertTrue(stock.warnings)   # tea bags still have no cost
        expenses = reports.expenses_report(self.period(), {})
        self.assertEqual(expenses.totals["total"], D("1400"))

    def test_cancelled_online_order_with_refund_due(self):
        order = self.place(lines=[(self.k10, 1)])
        payments.record_cash_payment(order, self.cashier)
        orders.cancel_order(order, self.manager, "Out of stock")
        s = services.summary(self.period())
        self.assertEqual(s.revenue, D("2320"))     # not revenue
        from apps.finance.reports import customer_balances_report

        self.assertEqual(customer_balances_report(self.period(), {}).totals["refund_due"], D("300"))


class PeriodTests(FinanceTestCase):
    def test_presets_and_custom(self):
        today = self.today()
        self.assertEqual(services.period_from({}).start, today.replace(day=1))
        self.assertEqual(services.period_from({"period": "today"}).start, today)
        self.assertEqual(services.period_from({"period": "year"}).start, date(today.year, 1, 1))
        last_year = services.period_from({"period": "last_year"})
        self.assertEqual((last_year.start, last_year.end), (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)))
        custom = services.period_from({"period": "custom", "start": "2026-01-05", "end": "2026-02-01"})
        self.assertEqual((custom.start, custom.end, custom.preset), (date(2026, 1, 5), date(2026, 2, 1), "custom"))
        for bad in ({"period": "custom", "start": "2026-02-01", "end": "2026-01-01"},
                    {"period": "custom", "start": "nope", "end": "2026-01-01"}, {"period": "bogus"}):
            self.assertEqual(services.period_from(bad).preset, "month")


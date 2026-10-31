import uuid
from decimal import Decimal

from django.utils import timezone

from apps.finance import services
from apps.finance.models import ExpenseCategory
from apps.inventory.models import Purchase, PurchaseLine, Supplier
from apps.inventory.services import receive_purchase, save_new_purchase
from apps.pos.tests.helpers import PosTestCase

D = Decimal


class FinanceTestCase(PosTestCase):
    """POS/online test data plus two suppliers and the seeded expense categories."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.supplier = Supplier.objects.create(name="Hill Estates")
        cls.supplier2 = Supplier.objects.create(name="Sweet Supplies")
        cls.transport = ExpenseCategory.objects.get(name="Transport & delivery")
        cls.utilities = ExpenseCategory.objects.get(name="Utilities")

    def today(self):
        return timezone.localdate()

    def purchase(self, lines, supplier=None, receive=True, user=None):
        """lines: [(inventory item, qty, unit_cost, unit or None)]"""
        user = user or self.owner
        purchase = save_new_purchase(Purchase(supplier=supplier or self.supplier, purchase_date=self.today()), user)
        for item, qty, cost, *unit in lines:
            PurchaseLine.objects.create(purchase=purchase, item=item, quantity=D(qty), unit_cost=D(cost),
                                        unit=unit[0] if unit else None)
        purchase.recalculate_totals()
        return receive_purchase(purchase, user) if receive else purchase

    def expense(self, amount="1000", category=None, method="CASH", **extra):
        expense, _ = services.record_expense(self.owner, uuid.uuid4(), category=category or self.transport,
                                             expense_date=extra.pop("expense_date", self.today()), amount=D(amount),
                                             payment_method=method, description=extra.pop("description", "Lorry hire"), **extra)
        return expense

    def pay_supplier(self, amount, supplier=None, purchase=None, method="BANK_TRANSFER", token=None):
        payment, _ = services.record_supplier_payment(self.owner, token or uuid.uuid4(), supplier=supplier or self.supplier,
                                                      purchase=purchase, payment_date=self.today(), amount=D(amount),
                                                      payment_method=method)
        return payment

    def period(self):
        return services.Period(self.today(), self.today(), "today", "today")

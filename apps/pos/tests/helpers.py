import uuid
from decimal import Decimal

from apps.accounts.roles import Role
from apps.accounts.tests.helpers import make_user
from apps.orders.models import Order
from apps.orders.tests.helpers import OrdersTestCase
from apps.pos import services

D = Decimal
CASH = Order.PaymentMethod.CASH
BANK = Order.PaymentMethod.BANK_TRANSFER


class PosTestCase(OrdersTestCase):
    """
    Products from ShopTestCase: Black Tea 200g LKR 500 (stock 10), Kokis LKR 300 (stock 20),
    Ginger Tea Bags LKR 450 (stock 3); Black Tea 400g (no stock), 1kg (not tracked), Draft Tea (draft).
    Default POS limits: cashier 5 %, manager 20 %, owner unlimited.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cashier2 = make_user(Role.CASHIER, "cashier2")

    def open(self, user=None, cash="1000"):
        return services.open_shift(user or self.cashier, D(cash))

    def sell(self, user=None, lines=None, method=CASH, tendered="5000", token=None, **extra):
        """Default: 2 × Black Tea 200g + 1 × Kokis = LKR 1,300."""
        lines = lines or [(self.b200.pk, 2), (self.k10.pk, 1)]
        if method == BANK:
            extra.setdefault("bank_reference", "BOC-123")
            tendered = None
        order, _ = services.create_sale(cashier=user or self.cashier, lines=lines, payment_method=method,
                                        token=token or uuid.uuid4(), cash_tendered=tendered, **extra)
        return order

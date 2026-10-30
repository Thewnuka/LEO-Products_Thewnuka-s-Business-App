import uuid
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError

from apps.inventory.models import StockMovement
from apps.orders.models import Order
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.pos import services
from apps.pos.models import CashierShift, CashMovement, PosSettings

from .helpers import BANK, CASH, D, PosTestCase

PAY = Payment.Status


class ShiftTests(PosTestCase):
    def test_open_shift_once(self):
        shift = self.open()
        self.assertTrue(shift.is_open)
        self.assertEqual(shift.opening_cash, D("1000"))
        with self.assertRaises(ValidationError):
            self.open()
        self.assertEqual(CashierShift.objects.filter(cashier=self.cashier).count(), 1)
        self.open(self.cashier2)  # another cashier may have their own

    def test_negative_opening_cash_refused(self):
        with self.assertRaises(ValidationError):
            self.open(cash="-1")

    def test_expected_cash_and_close(self):
        shift = self.open()
        self.sell()                                   # cash 1,300
        self.sell(method=BANK)                        # bank, not in the drawer
        services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_IN, D("500"), "Change float")
        services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_OUT, D("200"), "Bought milk")
        summary = services.shift_summary(shift)
        self.assertEqual((summary.cash_sales, summary.bank_pending, summary.expected_cash), (D("1300"), D("1300"), D("2600")))
        self.assertEqual(summary.sales_count, 2)
        with self.assertRaises(ValidationError):  # short and no explanation
            services.close_shift(shift, self.cashier, D("2500"))
        shift = services.close_shift(shift, self.cashier, D("2500"), "Gave wrong change once")
        self.assertEqual((shift.status, shift.expected_cash, shift.counted_cash, shift.difference),
                         (CashierShift.Status.CLOSED, D("2600"), D("2500"), D("-100")))
        self.assertEqual(shift.closed_by, self.cashier)
        self.assertIsNotNone(shift.closed_at)

    def test_closed_shift_is_locked(self):
        shift = services.close_shift(self.open(), self.cashier, D("1000"))
        self.assertEqual(shift.difference, D("0"))
        for action in (lambda: services.close_shift(shift, self.cashier, D("1000")),
                       lambda: services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_IN, D("5"), "x")):
            with self.assertRaises(ValidationError):
                action()
        with self.assertRaises(ValidationError):  # no open shift any more
            self.sell()
        self.open()  # a new shift can be opened

    def test_cash_out_limited_to_drawer(self):
        shift = self.open(cash="100")
        with self.assertRaises(ValidationError):
            services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_OUT, D("150"), "Too much")
        with self.assertRaises(ValidationError):
            services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_IN, D("10"), "  ")
        with self.assertRaises(ValidationError):
            services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_IN, D("0"), "zero")

    def test_only_own_shift_unless_manager(self):
        shift = self.open()
        with self.assertRaises(ValidationError):
            services.add_cash_movement(shift, self.cashier2, CashMovement.Kind.CASH_IN, D("5"), "x")
        with self.assertRaises(ValidationError):
            services.close_shift(shift, self.cashier2, D("1000"))
        closed = services.close_shift(shift, self.manager, D("1000"))
        self.assertEqual(closed.closed_by, self.manager)

    def test_shift_records_cannot_be_deleted(self):
        shift = self.open()
        movement = services.add_cash_movement(shift, self.cashier, CashMovement.Kind.CASH_IN, D("5"), "x")
        for obj in (shift, movement):
            with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic():
                obj.delete()


class CashSaleTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.shift = self.open()

    def test_cash_sale_records_everything(self):
        order = self.sell(tendered="2000", customer_name="Kamal", customer_phone="0711111111")
        self.assertTrue(order.number.startswith("POS-"))
        self.assertEqual((order.channel, order.fulfilment, order.status), (Order.Channel.POS, Order.Fulfilment.IN_STORE,
                                                                           Order.Status.COMPLETED))
        self.assertEqual((order.subtotal, order.discount_amount, order.total), (D("1300"), D("0"), D("1300")))
        self.assertEqual((order.cashier, order.shift, order.customer), (self.cashier, self.shift, None))
        self.assertEqual((order.full_name, order.phone), ("Kamal", "0711111111"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        payment = order.payments.get()
        self.assertEqual((payment.status, payment.amount, payment.cash_tendered, payment.change_given, payment.verified_by),
                         (PAY.PAID, D("1300"), D("2000"), D("700"), self.cashier))
        item = order.items.get(variation=self.b200)
        self.assertEqual((item.unit_price, item.quantity, item.line_total, item.sku), (D("500"), 2, D("1000"), self.b200.sku))
        self.assertEqual(self.stock(self.b200), D("8"))
        self.assertEqual(StockMovement.objects.filter(order_item__order=order, movement_type=StockMovement.Type.SALE).count(), 2)
        self.assertEqual(order.events.get().to_status, Order.Status.COMPLETED)

    def test_walk_in_default_name(self):
        self.assertEqual(self.sell().full_name, "Walk-in customer")

    def test_numbers_are_unique_and_separate_from_online(self):
        online = self.place()
        first, second = self.sell(), self.sell()
        self.assertTrue(online.number.startswith("LEO-"))
        self.assertNotEqual(first.number, second.number)
        self.assertEqual(int(second.number[-5:]), int(first.number[-5:]) + 1)

    def test_insufficient_cash_refused_and_nothing_saved(self):
        for tendered in ("1299.99", None, ""):
            with self.assertRaises(ValidationError):
                self.sell(tendered=tendered)
        self.assertFalse(Order.objects.filter(channel=Order.Channel.POS).exists())
        self.assertEqual(self.stock(self.b200), D("10"))

    def test_exact_cash_gives_zero_change(self):
        payment = self.sell(tendered="1300").payments.get()
        self.assertEqual(payment.change_given, D("0"))

    def test_same_token_sells_once(self):
        token = uuid.uuid4()
        first = self.sell(token=token)
        again, created = services.create_sale(cashier=self.cashier, lines=[(self.b200.pk, 2)], payment_method=CASH,
                                              token=token, cash_tendered="5000")
        self.assertFalse(created)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(self.stock(self.b200), D("8"))
        self.assertEqual(Order.objects.filter(channel=Order.Channel.POS).count(), 1)

    def test_token_of_another_cashier_refused(self):
        token = uuid.uuid4()
        self.sell(token=token)
        self.open(self.cashier2)
        with self.assertRaises(ValidationError):
            self.sell(user=self.cashier2, token=token)

    def test_stock_and_line_validation(self):
        cases = [[(self.g25.pk, 4)],             # only 3 in stock
                 [(self.b400.pk, 1)],            # out of stock
                 [(self.b1kg.pk, 1)],            # not tracked
                 [(self.d200.pk, 1)],            # draft product
                 [(999999, 1)], [(self.k10.pk, 0)], [(self.k10.pk, "x")], []]
        for lines in cases:
            with self.assertRaises(ValidationError, msg=str(lines)):
                services.create_sale(cashier=self.cashier, lines=lines, payment_method=CASH, token=uuid.uuid4(),
                                     cash_tendered="99999")
        self.assertFalse(Order.objects.filter(channel=Order.Channel.POS).exists())

    def test_duplicate_lines_are_merged(self):
        order = self.sell(lines=[(self.k10.pk, 1), (self.k10.pk, 2)])
        self.assertEqual(order.items.get().quantity, 3)

    def test_race_for_last_items_is_stopped_by_the_ledger(self):
        # Both tills saw 3 bags in stock; the stock ledger's conditional update stops the second sale.
        self.sell(lines=[(self.g25.pk, 3)])
        self.open(self.cashier2)
        with mock.patch("apps.pos.services.shop.available_stock", return_value=99):
            with self.assertRaises(ValidationError) as ctx:
                self.sell(user=self.cashier2, lines=[(self.g25.pk, 2)])
        self.assertIn("Sorry, only", str(ctx.exception))  # (the number shown comes from the mock)
        self.assertEqual(self.stock(self.g25), D("0"))
        self.assertEqual(Order.objects.filter(channel=Order.Channel.POS).count(), 1)

    def test_changed_total_refused(self):
        with self.assertRaises(ValidationError) as ctx:
            self.sell(expected_total="1000")
        self.assertEqual(ctx.exception.code, "total_changed")

    def test_staff_without_sales_permission_cannot_sell(self):
        with self.assertRaises(ValidationError):
            self.sell(user=self.manager)

    def test_sale_needs_open_shift(self):
        with self.assertRaises(ValidationError):
            self.sell(user=self.cashier2)


class BankTransferSaleTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.open()

    def test_never_paid_at_the_till(self):
        order = self.sell(method=BANK)
        payment = order.payments.get()
        self.assertEqual((order.status, order.payment_status), (Order.Status.PENDING, Order.PaymentStatus.PENDING_VERIFICATION))
        self.assertEqual((payment.status, payment.bank_reference, payment.cash_tendered), (PAY.PENDING_VERIFICATION, "BOC-123", None))
        self.assertEqual(self.stock(self.b200), D("8"))  # goods leave the shop, so stock is deducted

    def test_reference_required(self):
        with self.assertRaises(ValidationError):
            self.sell(method=BANK, bank_reference="  ")

    def test_approval_completes_the_sale(self):
        order = self.sell(method=BANK)
        payments.review_bank_transfer(order.payments.get(), self.manager, approve=True)
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), (Order.Status.COMPLETED, Order.PaymentStatus.PAID))
        self.assertIsNotNone(order.completed_at)
        self.assertEqual(order.events.last().created_by, self.manager)

    def test_rejection_leaves_sale_unpaid(self):
        order = self.sell(method=BANK)
        payments.review_bank_transfer(order.payments.get(), self.manager, approve=False, note="Not received")
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), (Order.Status.PENDING, Order.PaymentStatus.PENDING))

    def test_unknown_payment_method_refused(self):
        for method in ("ONLINE", "CHEQUE", ""):
            with self.assertRaises(ValidationError):
                self.sell(method=method)


class DiscountTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.open()

    def discounted(self, kind, value, approver=None, reason="Regular customer", user=None):
        return self.sell(user=user, discount_type=kind, discount_value=value, discount_reason=reason, approver=approver)

    def test_amount_calculation(self):
        self.assertEqual(services.discount_amount(D("1300"), "PERCENT", "10"), D("130.00"))
        self.assertEqual(services.discount_amount(D("999"), "PERCENT", "12.5"), D("124.88"))  # half up
        self.assertEqual(services.discount_amount(D("1300"), "FIXED", "50"), D("50.00"))
        self.assertEqual(services.discount_amount(D("1300"), "", None), D("0"))
        for kind, value in (("PERCENT", "101"), ("FIXED", "1300.01"), ("PERCENT", "0"), ("FIXED", "-5"),
                            ("PERCENT", "abc"), ("BOGUS", "5")):
            with self.assertRaises(ValidationError, msg=(kind, value)):
                services.discount_amount(D("1300"), kind, value)

    def test_cashier_within_limit(self):
        order = self.discounted("PERCENT", "5")
        self.assertEqual((order.discount_amount, order.total), (D("65.00"), D("1235.00")))
        self.assertEqual((order.discount_type, order.discount_value), ("PERCENT", D("5")))
        self.assertEqual((order.discount_applied_by, order.discount_approved_by), (self.cashier, None))
        self.assertEqual(order.payments.get().amount, D("1235.00"))

    def test_reason_required(self):
        with self.assertRaises(ValidationError):
            self.discounted("FIXED", "10", reason=" ")

    def test_above_limit_needs_approval(self):
        with self.assertRaises(ValidationError) as ctx:
            self.discounted("PERCENT", "10")
        self.assertEqual(ctx.exception.code, "needs_approval")
        order = self.discounted("PERCENT", "10", approver=self.manager)
        self.assertEqual((order.discount_amount, order.discount_approved_by), (D("130.00"), self.manager))

    def test_approver_limits(self):
        with self.assertRaises(ValidationError):  # manager limit is 20 %
            self.discounted("PERCENT", "30", approver=self.manager)
        with self.assertRaises(ValidationError):  # cashiers can't approve
            self.discounted("PERCENT", "10", approver=self.cashier2)
        with self.assertRaises(ValidationError):  # IT admin can't approve
            self.discounted("FIXED", "500", approver=self.it_admin)
        order = self.discounted("PERCENT", "50", approver=self.owner)
        self.assertEqual(order.discount_approved_by, self.owner)

    def test_limits_follow_settings(self):
        config = PosSettings.load()
        config.cashier_discount_limit = D("0")
        config.save()
        with self.assertRaises(ValidationError):
            self.discounted("FIXED", "1")

    def test_full_discount_never_negative(self):
        order = self.discounted("PERCENT", "100", approver=self.owner)
        self.assertEqual(order.total, D("0"))
        self.assertEqual(order.payments.get().change_given, D("5000"))
        with self.assertRaises(ValidationError):
            self.discounted("FIXED", "1500", approver=self.owner)

    def test_owner_selling_has_no_limit(self):
        services.open_shift(self.owner, D("0"))
        order = self.discounted("PERCENT", "40", user=self.owner)
        self.assertEqual(order.discount_approved_by, None)
        self.assertEqual(order.discount_applied_by, self.owner)


class RefundTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.shift = self.open()

    def test_cash_refund_reverses_once(self):
        order = self.sell()
        order = services.refund_sale(order, self.manager, "Damaged packet", drawer_shift=self.shift)
        self.assertEqual((order.status, order.payment_status), (Order.Status.CANCELLED, Order.PaymentStatus.REFUNDED))
        self.assertEqual(self.stock(self.b200), D("10"))
        payment = order.payments.get()
        self.assertEqual((payment.status, payment.refunded_by), (PAY.REFUNDED, self.manager))
        movement = CashMovement.objects.get(order=order)
        self.assertEqual((movement.kind, movement.amount, movement.shift), (CashMovement.Kind.REFUND, D("1300"), self.shift))
        summary = services.shift_summary(self.shift)
        self.assertEqual((summary.cash_sales, summary.cash_refunds, summary.expected_cash, summary.sales_count),
                         (D("1300"), D("1300"), D("1000"), 0))
        with self.assertRaises(ValidationError):
            services.refund_sale(order, self.manager, "Again", drawer_shift=self.shift)
        self.assertEqual(self.stock(self.b200), D("10"))
        self.assertEqual(StockMovement.objects.filter(order_item__order=order, movement_type=StockMovement.Type.ORDER_CANCEL).count(), 2)

    def test_permission_and_inputs(self):
        order = self.sell()
        with self.assertRaises(ValidationError):  # cashiers can't refund
            services.refund_sale(order, self.cashier, "x", drawer_shift=self.shift)
        with self.assertRaises(ValidationError):  # reason
            services.refund_sale(order, self.manager, " ", drawer_shift=self.shift)
        with self.assertRaises(ValidationError):  # cash needs a drawer
            services.refund_sale(order, self.manager, "x")
        closed = services.close_shift(services.open_shift(self.cashier2, D("5000")), self.cashier2, D("5000"))
        with self.assertRaises(ValidationError):  # closed drawer
            services.refund_sale(order, self.manager, "x", drawer_shift=closed)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)
        self.assertEqual(self.stock(self.b200), D("8"))

    def test_drawer_must_hold_the_refund(self):
        order = self.sell()
        poor = services.open_shift(self.cashier2, D("100"))
        with self.assertRaises(ValidationError):
            services.refund_sale(order, self.manager, "x", drawer_shift=poor)

    def test_void_unverified_bank_sale(self):
        order = self.sell(method=BANK)
        order = services.refund_sale(order, self.owner, "Customer changed mind")
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payments.get().status, PAY.REJECTED)
        self.assertFalse(CashMovement.objects.filter(order=order).exists())
        self.assertEqual(self.stock(self.b200), D("10"))

    def test_online_orders_not_refunded_here(self):
        with self.assertRaises(ValidationError):
            services.refund_sale(self.place(), self.owner, "x")


class SummaryTests(PosTestCase):
    def test_today_summary_scope(self):
        shift = self.open()
        self.sell()
        self.sell(method=BANK)
        self.open(self.cashier2)
        self.sell(user=self.cashier2, lines=[(self.k10.pk, 1)])
        mine = services.today_summary(self.cashier)
        self.assertEqual((mine["sales_count"], mine["sales_total"], mine["cash_sales"], mine["bank_pending"]),
                         (2, D("2600"), D("1300"), 1))
        self.assertEqual(len(mine["open_shifts"]), 1)
        everyone = services.today_summary(self.manager)
        self.assertEqual((everyone["sales_count"], everyone["cash_sales"], len(everyone["open_shifts"])), (3, D("1600"), 2))
        self.assertEqual(everyone["drawer_total"], services.shift_summary(shift).expected_cash + D("1300"))
        self.assertEqual(services.today_summary(self.it_admin)["sales_count"], 0)

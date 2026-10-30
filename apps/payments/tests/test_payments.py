import hashlib
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD, make_user
from apps.orders import services as orders
from apps.orders.models import Order
from apps.orders.tests.helpers import PM, D, OrdersTestCase, pdf_slip, slip
from apps.payments import services
from apps.payments.gateways import get_gateway, online_payment_available
from apps.payments.models import Payment, PaymentEvent

S = Payment.Status
P = Order.PaymentStatus


class CashPaymentTests(OrdersTestCase):
    def test_record_cash_once(self):
        order = self.place()
        payment = services.record_cash_payment(order, self.cashier, "Paid at counter")
        self.assertEqual((payment.status, payment.amount, payment.verified_by), (S.PAID, D("1300"), self.cashier))
        self.assertIsNotNone(payment.paid_at)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, P.PAID)
        with self.assertRaises(ValidationError):
            services.record_cash_payment(order, self.cashier)
        self.assertEqual(Payment.objects.filter(order=order, status=S.PAID).count(), 1)
        self.assertTrue(PaymentEvent.objects.filter(payment=payment, event="cash_received").exists())

    def test_cash_only_for_cash_orders_and_not_cancelled(self):
        bank = self.place(method=PM.BANK_TRANSFER)
        with self.assertRaises(ValidationError):
            services.record_cash_payment(bank, self.cashier)
        cancelled = orders.cancel_order(self.place(), self.manager, "test")
        with self.assertRaises(ValidationError):
            services.record_cash_payment(cancelled, self.cashier)

    def test_cash_view_permissions(self):
        order = self.place()
        url = reverse("payments:record_cash", args=[order.number])
        self.client.login(username="itadmin", password=PASSWORD)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.login(username="cashier", password=PASSWORD)
        self.assertRedirects(self.client.post(url), reverse("orders:staff_detail", args=[order.number]))
        self.client.post(url)  # double click: no second payment
        self.assertEqual(Payment.objects.filter(order=order, status=S.PAID).count(), 1)

    def test_cash_view_get_not_allowed(self):
        order = self.place()
        self.client.login(username="cashier", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("payments:record_cash", args=[order.number])).status_code, 405)


class BankTransferTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place(method=PM.BANK_TRANSFER)

    def test_submit_puts_payment_pending_verification(self):
        payment = services.submit_bank_transfer(self.order, self.customer, " BOC-998 ", slip())
        self.assertEqual((payment.status, payment.bank_reference), (S.PENDING_VERIFICATION, "BOC-998"))
        self.assertEqual(payment.evidence_content_type, "image/png")
        self.assertTrue(payment.evidence.name.startswith("payment-evidence/"))
        self.assertTrue((Path(settings.PRIVATE_MEDIA_ROOT) / payment.evidence.name).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PENDING_VERIFICATION)
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 1)  # the open attempt was reused
        with self.assertRaises(ValidationError):  # already waiting
            services.submit_bank_transfer(self.order, self.customer, "again", slip())

    def test_pdf_evidence_accepted(self):
        payment = services.submit_bank_transfer(self.order, self.customer, "REF", pdf_slip())
        self.assertEqual(payment.evidence_content_type, "application/pdf")

    def test_evidence_validation(self):
        bad = [
            SimpleUploadedFile("slip.exe", b"MZ....", content_type="application/octet-stream"),
            SimpleUploadedFile("slip.png", b"not really an image", content_type="image/png"),
            SimpleUploadedFile("slip.pdf", b"<html>fake</html>", content_type="application/pdf"),
            SimpleUploadedFile("slip.gif", b"GIF89a....", content_type="image/gif"),
        ]
        for upload in bad:
            with self.assertRaises(ValidationError, msg=upload.name):
                services.validate_evidence(upload)
        with override_settings(PAYMENT_EVIDENCE_MAX_BYTES=100):
            with self.assertRaises(ValidationError):
                services.validate_evidence(slip())
        # A PNG renamed to .jpg is still accepted, but recorded as what it really is.
        self.assertEqual(services.validate_evidence(slip("photo.jpg")), "image/png")

    def test_approve(self):
        payment = services.submit_bank_transfer(self.order, self.customer, "REF", slip())
        with self.captureOnCommitCallbacks(execute=True):
            services.review_bank_transfer(payment, self.manager, approve=True)
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.verified_by), (S.PAID, self.manager))
        self.assertIsNotNone(payment.verified_at)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PAID)
        self.assertIn("Payment received", mail.outbox[-1].subject)
        with self.assertRaises(ValidationError):  # second click
            services.review_bank_transfer(payment, self.owner, approve=True)
        payment.refresh_from_db()
        self.assertEqual(payment.verified_by, self.manager)

    def test_reject_then_resubmit(self):
        payment = services.submit_bank_transfer(self.order, self.customer, "REF", slip())
        with self.assertRaises(ValidationError):  # reason required
            services.review_bank_transfer(payment, self.manager, approve=False)
        with self.captureOnCommitCallbacks(execute=True):
            services.review_bank_transfer(payment, self.manager, approve=False, note="Amount not received")
        payment.refresh_from_db()
        self.assertEqual(payment.status, S.REJECTED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PENDING)
        self.assertIn("check the payment", mail.outbox[-1].subject)
        second = services.submit_bank_transfer(self.order, self.customer, "REF-2", slip())
        self.assertNotEqual(second.pk, payment.pk)
        self.assertEqual(second.status, S.PENDING_VERIFICATION)

    def test_rejection_note_shown_to_customer(self):
        payment = services.submit_bank_transfer(self.order, self.customer, "REF", slip())
        services.review_bank_transfer(payment, self.manager, approve=False, note="Wrong amount")
        self.client.login(username="customer@example.com", password=PASSWORD)
        response = self.client.get(self.order.get_absolute_url())
        self.assertContains(response, "Wrong amount")
        self.assertContains(response, reverse("payments:bank_submit", args=[self.order.number]))

    def test_customer_submits_through_page(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        page = self.client.get(self.order.get_absolute_url())
        self.assertContains(page, "123-456-789")  # bank details from settings
        url = reverse("payments:bank_submit", args=[self.order.number])
        response = self.client.post(url, {"reference": "BOC-1", "evidence": slip()})
        self.assertRedirects(response, self.order.get_absolute_url())
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PENDING_VERIFICATION)

    def test_invalid_upload_through_page_changes_nothing(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        url = reverse("payments:bank_submit", args=[self.order.number])
        self.client.post(url, {"reference": "BOC-1", "evidence": SimpleUploadedFile("x.png", b"nope")})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PENDING)

    def test_other_customer_cannot_submit(self):
        make_user(username="other@example.com")
        self.client.login(username="other@example.com", password=PASSWORD)
        url = reverse("payments:bank_submit", args=[self.order.number])
        self.assertEqual(self.client.post(url, {"reference": "x", "evidence": slip()}).status_code, 404)

    def test_review_view_permissions(self):
        payment = services.submit_bank_transfer(self.order, self.customer, "REF", slip())
        url = reverse("payments:review", args=[payment.reference])
        for user in ("cashier", "itadmin", "customer@example.com"):
            self.client.login(username=user, password=PASSWORD)
            self.assertEqual(self.client.post(url, {"decision": "approve"}).status_code, 403, user)
        payment.refresh_from_db()
        self.assertEqual(payment.status, S.PENDING_VERIFICATION)
        self.client.login(username="manager", password=PASSWORD)
        self.client.post(url, {"decision": "approve"})
        payment.refresh_from_db()
        self.assertEqual(payment.status, S.PAID)


class EvidencePrivacyTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place(method=PM.BANK_TRANSFER)
        self.payment = services.submit_bank_transfer(self.order, self.customer, "REF", slip())
        self.url = reverse("payments:evidence", args=[self.payment.reference])

    def test_owner_customer_and_order_staff_can_view(self):
        for user in ("customer@example.com", "owner", "manager", "cashier"):
            self.client.login(username=user, password=PASSWORD)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200, user)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertIn("no-store", response["Cache-Control"])
            response.close()

    def test_others_get_404(self):
        make_user(username="other@example.com")
        for user in ("other@example.com", "itadmin"):
            self.client.login(username=user, password=PASSWORD)
            self.assertEqual(self.client.get(self.url).status_code, 404, user)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_evidence_not_under_public_media(self):
        self.assertFalse(str(Path(settings.PRIVATE_MEDIA_ROOT).resolve()).startswith(str(Path(settings.MEDIA_ROOT).resolve())))
        self.assertNotIn(settings.MEDIA_URL, self.payment.evidence.name)


class RefundTests(OrdersTestCase):
    def test_owner_records_refund_for_cancelled_paid_order(self):
        order = self.place()
        payment = services.record_cash_payment(order, self.cashier)
        with self.assertRaises(ValidationError):  # order still open
            services.record_refund(payment, self.owner, "Cash returned")
        orders.cancel_order(order, self.manager, "Customer request")
        url = reverse("payments:refund", args=[payment.reference])
        self.client.login(username="manager", password=PASSWORD)
        self.assertEqual(self.client.post(url, {"note": "x"}).status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        self.client.post(url, {"note": "Cash returned at counter"})
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.refunded_by), (S.REFUNDED, self.owner))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, P.REFUNDED)
        with self.assertRaises(ValidationError):
            services.record_refund(payment, self.owner, "again")


PAYHERE = {"PAYMENT_GATEWAY": "payhere", "PAYHERE_MERCHANT_ID": "1211149", "PAYHERE_MERCHANT_SECRET": "test-secret",
           "PAYHERE_SANDBOX": True}


def md5u(text):
    return hashlib.md5(text.encode()).hexdigest().upper()


def notification(payment, status_code="2", amount=None, secret="test-secret", merchant="1211149"):
    amount = amount or f"{payment.amount:.2f}"
    sig = md5u(merchant + payment.reference + amount + "LKR" + status_code + md5u(secret))
    return {"merchant_id": merchant, "order_id": payment.reference, "payment_id": "320027150501",
            "payhere_amount": amount, "payhere_currency": "LKR", "status_code": status_code, "md5sig": sig,
            "method": "VISA", "status_message": "Successfully completed the payment."}


class OnlinePaymentNotConfiguredTests(OrdersTestCase):
    def test_off_without_credentials(self):
        self.assertFalse(online_payment_available())
        self.assertIsNone(get_gateway("payhere"))
        with override_settings(PAYMENT_GATEWAY="payhere", PAYHERE_MERCHANT_ID="123", PAYHERE_MERCHANT_SECRET=""):
            self.assertFalse(online_payment_available())

    def test_checkout_does_not_offer_online(self):
        self.fill_cart()
        self.client.login(username="customer@example.com", password=PASSWORD)
        response = self.client.get(reverse("orders:checkout"))
        self.assertNotIn("ONLINE", dict(response.context["form"].fields["payment_method"].choices))
        self.assertContains(response, "Online card payment is not available yet")

    def test_settings_page_says_not_configured(self):
        self.client.login(username="owner", password=PASSWORD)
        self.assertContains(self.client.get(reverse("orders:settings")), "Not configured")

    def test_webhook_ignored_when_not_configured(self):
        response = self.client.post(reverse("payments:webhook", args=["payhere"]), {"order_id": "PAY-1"})
        self.assertEqual(response.content, b"ignored: gateway not configured")


@override_settings(**PAYHERE)
class OnlinePaymentTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place(method=PM.ONLINE)
        self.payment = self.order.payments.get()

    def post_webhook(self, data):
        return self.client.post(reverse("payments:webhook", args=["payhere"]), data)

    def test_checkout_request_is_signed(self):
        request = RequestFactory().post("/")
        request.user = self.customer
        payment, checkout = services.start_online_payment(self.order, request)
        self.assertEqual(checkout.action_url, "https://sandbox.payhere.lk/pay/checkout")
        f = checkout.fields
        self.assertEqual((f["order_id"], f["amount"], f["currency"]), (payment.reference, "1300.00", "LKR"))
        self.assertEqual(f["hash"], md5u("1211149" + payment.reference + "1300.00" + "LKR" + md5u("test-secret")))
        self.assertNotIn("test-secret", str(f))
        self.assertTrue(f["notify_url"].endswith(reverse("payments:webhook", args=["payhere"])))

    def test_pay_now_page_and_return_never_mark_paid(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        response = self.client.post(reverse("payments:online_start", args=[self.order.number]))
        self.assertContains(response, "sandbox.payhere.lk")
        self.client.get(reverse("payments:online_return", args=[self.payment.reference]) + "?status_code=2")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, S.PENDING)

    def test_verified_notification_marks_paid_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_webhook(notification(self.payment))
        self.assertEqual(response.content, b"paid")
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.transaction_id), (S.PAID, "320027150501"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PAID)
        self.assertEqual(self.post_webhook(notification(self.payment)).content, b"duplicate: already processed")
        self.assertEqual(Payment.objects.filter(order=self.order, status=S.PAID).count(), 1)
        self.assertEqual(len([m for m in mail.outbox if "Payment received" in m.subject]), 1)

    def test_bad_signature_is_ignored(self):
        data = notification(self.payment)
        data["md5sig"] = "0" * 32
        self.assertEqual(self.post_webhook(data).content, b"ignored: invalid notification")
        data = notification(self.payment, secret="wrong")
        self.assertEqual(self.post_webhook(data).content, b"ignored: invalid notification")
        data = notification(self.payment, merchant="999")
        self.assertEqual(self.post_webhook(data).content, b"ignored: invalid notification")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, S.PENDING)

    def test_amount_mismatch_is_ignored(self):
        self.assertEqual(self.post_webhook(notification(self.payment, amount="1.00")).content, b"ignored: amount mismatch")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, S.PENDING)

    def test_failed_notification(self):
        self.assertEqual(self.post_webhook(notification(self.payment, status_code="-2")).content, b"failed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, S.FAILED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, P.PENDING)

    def test_unknown_payment_ignored(self):
        other = Payment(reference="PAY-000000-ABCDEF", amount=D("1300"))
        self.assertEqual(self.post_webhook(notification(other)).content, b"ignored: unknown payment")

    def test_webhook_is_csrf_exempt_but_post_only(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        url = reverse("payments:webhook", args=["payhere"])
        self.assertEqual(client.post(url, notification(self.payment)).status_code, 200)
        self.assertEqual(client.get(url).status_code, 405)

    def test_checkout_offers_online_when_configured(self):
        self.fill_cart()
        self.client.login(username="customer@example.com", password=PASSWORD)
        response = self.client.get(reverse("orders:checkout"))
        self.assertIn("ONLINE", dict(response.context["form"].fields["payment_method"].choices))

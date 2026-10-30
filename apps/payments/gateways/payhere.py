"""
PayHere (Sri Lanka, LKR) hosted-checkout adapter.

Environment: PAYMENT_GATEWAY=payhere, PAYHERE_MERCHANT_ID, PAYHERE_MERCHANT_SECRET,
PAYHERE_SANDBOX (True while testing).

Implements PayHere's documented checkout hash and notify (md5sig) check:
  hash   = MD5(merchant_id + order_id + amount + currency + MD5(secret).upper()).upper()
  md5sig = MD5(merchant_id + order_id + payhere_amount + payhere_currency
               + status_code + MD5(secret).upper()).upper()
  status_code: 2 success, 0 pending, -1 cancelled, -2 failed, -3 chargedback

IMPORTANT before going live: confirm these details against PayHere's current
documentation, and run end-to-end tests in their sandbox. The notify_url must be
reachable from the internet (a local development server is not).
"""
import hashlib
import hmac
from decimal import Decimal, InvalidOperation

from django.conf import settings

from .base import CheckoutRequest, GatewayNotConfigured, InvalidNotification, PaymentGateway, VerifiedNotification

SANDBOX_URL = "https://sandbox.payhere.lk/pay/checkout"
LIVE_URL = "https://www.payhere.lk/pay/checkout"
OUTCOMES = {"2": "paid", "0": "pending", "-1": "cancelled", "-2": "failed", "-3": "chargeback"}


def _md5_upper(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()  # noqa: S324 (required by PayHere's protocol)


class PayHereGateway(PaymentGateway):
    name = "payhere"
    display_name = "PayHere (card / online banking)"

    def __init__(self):
        self.merchant_id = settings.PAYHERE_MERCHANT_ID.strip()
        self.secret = settings.PAYHERE_MERCHANT_SECRET.strip()
        self.sandbox = settings.PAYHERE_SANDBOX

    def is_configured(self):
        return bool(self.merchant_id and self.secret)

    def _amount(self, value):
        return f"{Decimal(value):.2f}"

    def build_checkout(self, payment, *, return_url, cancel_url, notify_url, customer):
        if not self.is_configured():
            raise GatewayNotConfigured("PayHere credentials are missing.")
        amount = self._amount(payment.amount)
        digest = _md5_upper(self.merchant_id + payment.reference + amount + payment.currency + _md5_upper(self.secret))
        order = payment.order
        first, _, last = (order.full_name or customer.get_full_name()).partition(" ")
        return CheckoutRequest(
            action_url=SANDBOX_URL if self.sandbox else LIVE_URL,
            fields={
                "merchant_id": self.merchant_id,
                "return_url": return_url,
                "cancel_url": cancel_url,
                "notify_url": notify_url,
                "order_id": payment.reference,
                "items": f"LEO PRODUCTS order {order.number}",
                "currency": payment.currency,
                "amount": amount,
                "first_name": first or "Customer",
                "last_name": last or "-",
                "email": order.email or customer.email,
                "phone": order.phone,
                "address": " ".join(filter(None, [order.address_line1, order.address_line2])) or "Store pickup",
                "city": order.city or "-",
                "country": "Sri Lanka",
                "hash": digest,
            },
        )

    def parse_notification(self, data):
        if not self.is_configured():
            raise InvalidNotification("Gateway not configured.")
        required = ("merchant_id", "order_id", "payhere_amount", "payhere_currency", "status_code", "md5sig")
        if any(not data.get(k) for k in required):
            raise InvalidNotification("Missing fields.")
        if data["merchant_id"] != self.merchant_id:
            raise InvalidNotification("Unknown merchant.")
        expected = _md5_upper(data["merchant_id"] + data["order_id"] + data["payhere_amount"] + data["payhere_currency"]
                              + data["status_code"] + _md5_upper(self.secret))
        if not hmac.compare_digest(expected, data["md5sig"].upper()):
            raise InvalidNotification("Bad signature.")
        try:
            amount = Decimal(data["payhere_amount"])
        except InvalidOperation:
            raise InvalidNotification("Bad amount.")
        return VerifiedNotification(
            payment_reference=data["order_id"],
            outcome=OUTCOMES.get(data["status_code"], "failed"),
            amount=amount,
            currency=data["payhere_currency"],
            transaction_id=data.get("payment_id", ""),
            gateway_status=data["status_code"],
            safe_payload={k: data.get(k, "") for k in ("order_id", "payment_id", "payhere_amount", "payhere_currency",
                                                         "status_code", "method", "status_message")},
        )

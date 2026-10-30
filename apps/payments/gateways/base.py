"""
Payment gateway adapter interface.

A gateway adapter turns a Payment into a hosted-checkout request and turns the
gateway's server-to-server notification (webhook) into a *verified* result.
Only a verified notification can mark a payment as paid (see
services.apply_gateway_notification). Redirects back from the gateway are
never trusted.

To add a gateway: subclass PaymentGateway, implement the methods, register it
in gateways/__init__.py and document its environment variables.
"""
from dataclasses import dataclass, field
from decimal import Decimal


class GatewayNotConfigured(Exception):
    """Raised when online payment is used without credentials."""


class InvalidNotification(Exception):
    """Raised when a webhook fails signature or data checks; it is ignored."""


@dataclass
class CheckoutRequest:
    """What the browser needs to start a hosted checkout: an auto-submitted form."""
    action_url: str
    fields: dict = field(default_factory=dict)
    method: str = "post"


@dataclass
class VerifiedNotification:
    """A webhook whose signature has been verified."""
    payment_reference: str
    outcome: str            # "paid" | "pending" | "failed" | "cancelled" | "chargeback"
    amount: Decimal
    currency: str
    transaction_id: str
    gateway_status: str
    safe_payload: dict = field(default_factory=dict)  # no secrets; stored in PaymentEvent


class PaymentGateway:
    name = ""
    display_name = ""

    def is_configured(self):
        raise NotImplementedError

    def build_checkout(self, payment, *, return_url, cancel_url, notify_url, customer):
        """Return a CheckoutRequest for the payment. Must not mark anything as paid."""
        raise NotImplementedError

    def parse_notification(self, data):
        """Verify a webhook (signature, merchant) and return a VerifiedNotification, or raise InvalidNotification."""
        raise NotImplementedError

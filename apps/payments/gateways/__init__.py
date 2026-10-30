"""Gateway registry. settings.PAYMENT_GATEWAY chooses the adapter; empty = online payment off."""
from django.conf import settings

from .base import GatewayNotConfigured, InvalidNotification  # noqa: F401
from .payhere import PayHereGateway

GATEWAYS = {PayHereGateway.name: PayHereGateway}


def get_gateway(name=None):
    """The configured gateway adapter, or None when online payment is not set up."""
    name = name or settings.PAYMENT_GATEWAY
    cls = GATEWAYS.get(name)
    if cls is None:
        return None
    gateway = cls()
    return gateway if gateway.is_configured() else None


def online_payment_available():
    return get_gateway() is not None

import io
import shutil
import tempfile
import uuid
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from apps.orders import services
from apps.orders.models import CheckoutSettings, DeliveryZone, Order
from apps.shop import services as shop
from apps.shop.tests.helpers import ShopTestCase

D = Decimal
F = Order.Fulfilment
PM = Order.PaymentMethod
St = Order.Status


def slip(name="slip.png", fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (240, 240, 240)).save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


def pdf_slip(name="slip.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n", content_type="application/pdf")


@override_settings(PAYMENT_GATEWAY="", PAYHERE_MERCHANT_ID="", PAYHERE_MERCHANT_SECRET="",
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OrdersTestCase(ShopTestCase):
    """
    Shop products from ShopTestCase, plus:
      settings: delivery + pickup, cash for both, bank transfer with complete details
      zones:    Colombo LKR 350 (free over LKR 5,000); Kandy LKR 600 (inactive)
    Payment evidence goes to a temporary private folder.
    """

    @classmethod
    def setUpClass(cls):
        cls._private = tempfile.mkdtemp(prefix="leo-test-private-")
        cls._private_override = override_settings(PRIVATE_MEDIA_ROOT=cls._private)
        cls._private_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._private_override.disable()
        shutil.rmtree(cls._private, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        config = CheckoutSettings.load()
        config.bank_transfer_enabled = True
        config.bank_name, config.bank_account_name, config.bank_account_number = "People's Bank", "LEO PRODUCTS", "123-456-789"
        config.pickup_address = "No. 1, Main Street, Kandy"
        config.save()
        cls.colombo = DeliveryZone.objects.create(name="Colombo", fee=D("350"), free_delivery_over=D("5000"))
        cls.kandy = DeliveryZone.objects.create(name="Kandy", fee=D("600"), is_active=False)

    # ---- helpers ------------------------------------------------------------
    def fill_cart(self, user=None, lines=None):
        """Put items in the customer's cart (default: 2 × Black Tea 200g, 1 × Kokis)."""
        cart = shop.get_cart_for_user(user or self.customer)
        for variation, qty in (lines or [(self.b200, 2), (self.k10, 1)]):
            shop.add_to_cart(cart, variation, qty)
        return cart

    def details(self, fulfilment=F.PICKUP, method=PM.CASH, **extra):
        data = {"full_name": "Nimal Perera", "phone": "077 123 4567", "fulfilment": fulfilment,
                "payment_method": method, "delivery_zone": None, "address_line1": "", "address_line2": "",
                "city": "", "delivery_instructions": ""}
        if fulfilment == F.DELIVERY:
            data.update(delivery_zone=self.colombo, address_line1="12 Galle Road", city="Colombo 3")
        data.update(extra)
        return data

    def place(self, user=None, fulfilment=F.PICKUP, method=PM.CASH, lines=None, **extra):
        user = user or self.customer
        self.fill_cart(user, lines)
        order, _ = services.place_order(user, self.details(fulfilment, method, **extra), uuid.uuid4())
        return order

    def stock(self, variation):
        variation.inventory_item.refresh_from_db()
        return variation.inventory_item.quantity

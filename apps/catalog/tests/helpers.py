import io
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from apps.accounts.tests.helpers import AccountsTestCase
from apps.catalog.models import Category, MeasurementType, Product, ProductVariation, Unit


def image_file(name="photo.png", fmt="PNG", size=(800, 600), color=(18, 61, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[fmt]
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


class CatalogTestCase(AccountsTestCase):
    """One user per role (from AccountsTestCase), the seeded categories/units and a temporary MEDIA_ROOT."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="leo-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Rows created by the data migration (seed) are available in tests.
        cls.leo_tea = Category.objects.get(name="LEO TEA", parent=None)
        cls.black_tea = Category.objects.get(name="Black Tea", parent=cls.leo_tea)
        cls.tea_bags = Category.objects.get(name="TEA BAGS", parent=None)
        cls.sweets = Category.objects.get(name="LEO SWEETS", parent=None)
        cls.kokis = Category.objects.get(name="Kokis", parent=cls.sweets)
        cls.gram = Unit.objects.get(symbol="g")
        cls.bags = Unit.objects.get(symbol="bags")
        cls.pieces = Unit.objects.get(symbol="pieces")


def make_product(name="Pure Black Tea", category=None, subcategory=None, status=Product.Status.DRAFT, **extra):
    category = category or Category.objects.get(name="LEO TEA", parent=None)
    return Product.objects.create(name=name, category=category, subcategory=subcategory, status=status, **extra)


def make_variation(product, quantity="200", unit=None, price="1000.00", measurement=MeasurementType.WEIGHT, **extra):
    unit = unit or Unit.objects.get(symbol="g")
    return ProductVariation.objects.create(
        product=product, quantity=Decimal(quantity), unit=unit, measurement_type=measurement,
        selling_price=Decimal(price), **extra,
    )

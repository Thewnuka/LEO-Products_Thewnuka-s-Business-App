from decimal import Decimal

from django.core.cache import cache

from apps.accounts.tests.helpers import AccountsTestCase
from apps.catalog.models import Category, MeasurementType, Product, ProductVariation, Unit
from apps.inventory.models import InventoryItem
from apps.inventory.services import create_item_with_opening_stock

D = Decimal


def add_variation(product, qty, unit, measurement, price, stock=None, user=None, **extra):
    """A variation plus (optionally) a finished-goods stock record with `stock` packets."""
    v = ProductVariation.objects.create(product=product, quantity=D(qty), unit=unit, measurement_type=measurement,
                                        selling_price=D(price), **extra)
    if stock is not None:
        create_item_with_opening_stock(InventoryItem(kind=InventoryItem.Kind.FINISHED_GOOD, variation=v), D(stock), user)
    return v


def activate(product):
    product.status = Product.Status.ACTIVE
    product.save()
    return product


class ShopTestCase(AccountsTestCase):
    """
    Black Tea (LEO TEA › Black Tea): 200g LKR 500 (stock 10), 400g LKR 900 (stock 0), 1kg LKR 2000 (not tracked)
    Ginger Tea Bags (TEA BAGS): 25 bags LKR 450 (stock 3), wholesale LKR 399
    Kokis (LEO SWEETS › Kokis): 10 pieces LKR 300 (stock 20)
    Draft Tea (draft, has stock) – must never appear
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.g, cls.kg = Unit.objects.get(symbol="g"), Unit.objects.get(symbol="kg")
        cls.bags, cls.pieces = Unit.objects.get(symbol="bags"), Unit.objects.get(symbol="pieces")
        cls.leo_tea = Category.objects.get(name="LEO TEA", parent=None)
        cls.black_sub = Category.objects.get(name="Black Tea", parent=cls.leo_tea)
        cls.tea_bags = Category.objects.get(name="TEA BAGS", parent=None)
        cls.sweets = Category.objects.get(name="LEO SWEETS", parent=None)
        cls.kokis_sub = Category.objects.get(name="Kokis", parent=cls.sweets)
        W, C, P = MeasurementType.WEIGHT, MeasurementType.COUNT, MeasurementType.PIECE

        cls.black = Product.objects.create(name="Black Tea", category=cls.leo_tea, subcategory=cls.black_sub,
                                           description="Strong morning tea from the hills.")
        cls.b200 = add_variation(cls.black, "200", cls.g, W, "500", stock=10, user=cls.owner)
        cls.b400 = add_variation(cls.black, "400", cls.g, W, "900", stock=0, user=cls.owner)
        cls.b1kg = add_variation(cls.black, "1", cls.kg, W, "2000")  # no stock record
        activate(cls.black)

        cls.ginger = Product.objects.create(name="Ginger Tea Bags", category=cls.tea_bags)
        cls.g25 = add_variation(cls.ginger, "25", cls.bags, C, "450", stock=3, user=cls.owner, wholesale_price=D("399"))
        activate(cls.ginger)

        cls.kokis = Product.objects.create(name="Kokis", category=cls.sweets, subcategory=cls.kokis_sub)
        cls.k10 = add_variation(cls.kokis, "10", cls.pieces, P, "300", stock=20, user=cls.owner)
        activate(cls.kokis)

        cls.draft = Product.objects.create(name="Draft Tea", category=cls.leo_tea)
        cls.d200 = add_variation(cls.draft, "200", cls.g, W, "100", stock=50, user=cls.owner)

    def setUp(self):
        super().setUp()
        cache.clear()

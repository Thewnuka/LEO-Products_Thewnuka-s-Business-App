from datetime import date
from decimal import Decimal

from apps.accounts.tests.helpers import AccountsTestCase
from apps.catalog.models import Category, MeasurementType, Product, ProductVariation, Unit
from apps.inventory.models import InventoryItem, Purchase, PurchaseLine, Supplier
from apps.inventory.services import create_item_with_opening_stock, save_new_purchase

D = Decimal


class InventoryTestCase(AccountsTestCase):
    """Users per role + seeded units, a raw tea item (kg), packets of 200g/400g tea and a supplier."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.g, cls.kg = Unit.objects.get(symbol="g"), Unit.objects.get(symbol="kg")
        cls.bags = Unit.objects.get(symbol="bags")
        cls.leo_tea = Category.objects.get(name="LEO TEA", parent=None)
        cls.product = Product.objects.create(name="Black Tea", category=cls.leo_tea)
        cls.v200 = ProductVariation.objects.create(product=cls.product, quantity=D("200"), unit=cls.g,
                                                   measurement_type=MeasurementType.WEIGHT, selling_price=D("500"))
        cls.v400 = ProductVariation.objects.create(product=cls.product, quantity=D("400"), unit=cls.g,
                                                   measurement_type=MeasurementType.WEIGHT, selling_price=D("900"))
        cls.supplier = Supplier.objects.create(name="Hill Country Estates", phone="0771234567", email="sales@hill.example")

    def setUp(self):
        super().setUp()
        self.raw = raw_item("Unpacked Black Tea", self.kg, self.owner, opening="20")
        self.packets = finished_item(self.v200, self.owner, opening="35", reorder="10")


def raw_item(name, unit, user, opening="0", reorder="0", **extra):
    item = InventoryItem(kind=InventoryItem.Kind.RAW_MATERIAL, name=name, stock_unit=unit, reorder_level=D(reorder), **extra)
    return create_item_with_opening_stock(item, D(opening), user)


def finished_item(variation, user, opening="0", reorder="0", **extra):
    item = InventoryItem(kind=InventoryItem.Kind.FINISHED_GOOD, variation=variation, reorder_level=D(reorder), **extra)
    return create_item_with_opening_stock(item, D(opening), user)


def draft_purchase(supplier, user, lines):
    """lines: [(item, quantity, unit_or_None, unit_cost)]"""
    purchase = save_new_purchase(Purchase(supplier=supplier, purchase_date=date(2026, 10, 30)), user)
    for item, qty, unit, cost in lines:
        PurchaseLine.objects.create(purchase=purchase, item=item, quantity=D(qty), unit=unit, unit_cost=D(cost))
    purchase.recalculate_totals()
    return purchase

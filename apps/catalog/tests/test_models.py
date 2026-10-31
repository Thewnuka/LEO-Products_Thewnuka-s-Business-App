from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalog.models import Category, MeasurementType, Product, ProductVariation, Unit
from apps.catalog.services import catalog_stats, suggest_sku

from .helpers import CatalogTestCase, make_product, make_variation


class SeedDataTests(CatalogTestCase):
    def test_initial_categories_and_units_exist(self):
        mains = list(Category.objects.main().values_list("name", flat=True))
        self.assertEqual(mains, ["LEO TEA", "LEO SWEETS"])  # TEA BAGS is a subcategory of LEO TEA (Phase 11)
        self.assertEqual(list(self.leo_tea.children.values_list("name", flat=True)), ["Tea Bags", "Tea Packets"])
        self.assertEqual(list(self.sweets.children.values_list("name", flat=True)), ["Kokis"])
        self.assertEqual(
            set(Unit.objects.values_list("symbol", "measurement_type")),
            {("g", "WEIGHT"), ("kg", "WEIGHT"), ("bags", "COUNT"), ("pieces", "PIECE")},
        )


class CategoryModelTests(CatalogTestCase):
    def test_create_main_and_subcategory_with_unique_slugs(self):
        spices = Category.objects.create(name="LEO SPICES")
        pepper = Category.objects.create(name="Pepper", parent=spices)
        self.assertTrue(spices.is_main)
        self.assertFalse(pepper.is_main)
        self.assertEqual(pepper.slug, "leo-spices-pepper")
        self.assertEqual(str(pepper), "LEO SPICES › Pepper")

    def test_duplicate_name_in_same_parent_is_rejected(self):
        dup = Category(name="tea packets", parent=self.leo_tea)
        with self.assertRaises(ValidationError):
            dup.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name="TEA PACKETS", parent=self.leo_tea, slug="x")

    def test_duplicate_main_category_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name="leo tea", slug="leo-tea-dup")

    def test_same_name_allowed_under_different_parents(self):
        Category.objects.create(name="Tea Packets", parent=self.sweets)  # no error

    def test_only_two_levels(self):
        deeper = Category(name="Extra Strong", parent=self.tea_packets)
        with self.assertRaises(ValidationError) as ctx:
            deeper.full_clean()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_category_with_products_or_children_cannot_be_deleted(self):
        make_product(category=self.leo_tea, subcategory=self.tea_packets)
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.tea_packets.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.sweets.delete()  # has the Kokis subcategory
        empty = Category.objects.create(name="Empty")
        empty.delete()


class ProductModelTests(CatalogTestCase):
    def test_slug_is_generated_and_unique(self):
        a = make_product("Ceylon Gold")
        b = make_product("Ceylon Gold")
        self.assertEqual(a.slug, "ceylon-gold")
        self.assertEqual(b.slug, "ceylon-gold-2")

    def test_subcategory_must_belong_to_main_category(self):
        product = Product(name="Mixed", category=self.leo_tea, subcategory=self.kokis)
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        self.assertIn("subcategory", ctx.exception.message_dict)

    def test_main_category_must_be_a_main_category(self):
        product = Product(name="Wrong", category=self.tea_packets)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_cannot_activate_without_an_active_variation(self):
        product = make_product()
        product.status = Product.Status.ACTIVE
        with self.assertRaises(ValidationError):
            product.full_clean()
        make_variation(product)
        product.full_clean()  # now allowed


class VariationModelTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product()

    def test_weight_count_and_piece_variations(self):
        weight = make_variation(self.product, "200", self.gram, measurement=MeasurementType.WEIGHT)
        bags_product = make_product("Ginger Bags", category=self.leo_tea, subcategory=self.tea_bags)
        count = make_variation(bags_product, "25", self.bags, measurement=MeasurementType.COUNT)
        kokis = make_product("Kokis Pack", category=self.sweets, subcategory=self.kokis)
        piece = make_variation(kokis, "10", self.pieces, measurement=MeasurementType.PIECE)
        self.assertEqual(weight.display_name, "200g")
        self.assertEqual(count.display_name, "25 bags")
        self.assertEqual(piece.display_name, "10 pieces")

    def test_new_unit_can_be_created_and_used(self):
        packs = Unit.objects.create(measurement_type=MeasurementType.COUNT, name="Pack", symbol="packs")
        v = make_variation(self.product, "3", packs, measurement=MeasurementType.COUNT)
        self.assertEqual(v.display_name, "3 packs")

    def test_unit_must_match_measurement_type(self):
        v = ProductVariation(product=self.product, quantity=Decimal("10"), unit=self.bags,
                             measurement_type=MeasurementType.WEIGHT, selling_price=Decimal("10"), sku="X-1-Y")
        with self.assertRaises(ValidationError) as ctx:
            v.full_clean()
        self.assertIn("unit", ctx.exception.message_dict)

    def test_sku_generated_and_unique(self):
        v = make_variation(self.product, "200")
        self.assertEqual(v.sku, f"LEO-LT-{self.product.pk:04d}-200G")
        self.assertEqual(suggest_sku(self.product, Decimal("1.5"), Unit.objects.get(symbol="kg")),
                         f"LEO-LT-{self.product.pk:04d}-1P5KG")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_variation(self.product, "400", sku=v.sku.lower())  # case-insensitive

    def test_generated_sku_avoids_collisions(self):
        taken = suggest_sku(self.product, Decimal("400"), self.gram)
        other = make_product("Other")
        make_variation(other, "100", sku=taken)
        v = make_variation(self.product, "400")
        self.assertEqual(v.sku, taken + "-2")

    def test_prices_and_quantity_must_be_positive(self):
        for field, value in (("selling_price", "0"), ("selling_price", "-5"), ("quantity", "0"), ("wholesale_price", "0")):
            v = ProductVariation(product=self.product, quantity=Decimal("50"), unit=self.gram, sku="LEO-T-1",
                                 measurement_type=MeasurementType.WEIGHT, selling_price=Decimal("10"))
            setattr(v, field, Decimal(value))
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                v.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductVariation.objects.create(product=self.product, quantity=Decimal("5"), unit=self.gram, sku="LEO-NEG",
                                            measurement_type=MeasurementType.WEIGHT, selling_price=Decimal("-1"))

    def test_duplicate_size_for_same_product_rejected(self):
        make_variation(self.product, "200")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_variation(self.product, "200.000", sku="LEO-DIFFERENT")

    def test_unit_in_use_cannot_be_deleted(self):
        make_variation(self.product)
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.gram.delete()


class StatsTests(CatalogTestCase):
    def test_stats_count_real_rows(self):
        stats = catalog_stats()
        self.assertEqual((stats["total_products"], stats["main_categories"], stats["subcategories"], stats["total_variations"]), (0, 2, 3, 0))
        p = make_product()
        make_variation(p)
        make_variation(p, "400", is_active=False)
        p.status = Product.Status.ACTIVE
        p.save()
        make_product("Second", status=Product.Status.INACTIVE)
        stats = catalog_stats()
        self.assertEqual(stats["total_products"], 2)
        self.assertEqual(stats["active_products"], 1)
        self.assertEqual(stats["inactive_products"], 1)
        self.assertEqual(stats["total_variations"], 2)
        self.assertEqual(stats["active_variations"], 1)

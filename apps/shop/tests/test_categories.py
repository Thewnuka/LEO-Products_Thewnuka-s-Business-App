"""
Phase 11: the store's category structure.

    LEO TEA › Tea Bags, Tea Packets   (varieties: Black, Ginger, Cinnamon)
    LEO SWEETS (separate main category)
"""
import importlib

from django.apps import apps as django_apps
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.inventory.models import InventoryItem

from .helpers import ShopTestCase, activate, add_variation

restructure = importlib.import_module("apps.catalog.migrations.0004_restructure_tea_categories").restructure


class CategoryStructureTests(ShopTestCase):
    def test_seeded_structure(self):
        self.assertEqual(list(Category.objects.main().values_list("name", flat=True)), ["LEO TEA", "LEO SWEETS"])
        self.assertEqual(list(self.leo_tea.children.values_list("name", flat=True)), ["Tea Bags", "Tea Packets"])
        self.assertFalse(Category.objects.filter(name__iexact="TEA BAGS", parent=None).exists())

    def test_tea_and_sweets_are_separate_sections(self):
        sections = self.client.get(reverse("shop:home")).context["sections"]
        by_main = {c.name: {p.category.name for p in ps} for c, ps in sections}
        self.assertEqual(by_main, {"LEO TEA": {"LEO TEA"}, "LEO SWEETS": {"LEO SWEETS"}})
        r = self.client.get(reverse("shop:category", args=[self.sweets.slug]))
        self.assertEqual([p.name for p in r.context["page_obj"]], ["Kokis"])

    def test_tea_pages_show_both_subcategories_and_varieties(self):
        self.ginger.status = Product.Status.DRAFT  # Tea Bags has nothing listed, but stays in the navigation
        self.ginger.save()
        r = self.client.get(reverse("shop:category", args=[self.leo_tea.slug]))
        self.assertEqual([c.name for c in r.context["subcategories"]], ["Tea Bags", "Tea Packets"])
        self.assertEqual(r.context["varieties"], ["Black", "Ginger", "Cinnamon"])
        self.assertContains(r, "?q=Cinnamon")
        r = self.client.get(reverse("shop:category", args=[self.tea_bags.slug]))
        self.assertContains(r, "no Tea Bags products yet")
        r = self.client.get(reverse("shop:category", args=[self.sweets.slug]))
        self.assertEqual(r.context["varieties"], [])

    def test_variety_filter(self):
        cinnamon = Product.objects.create(name="Cinnamon Tea", category=self.leo_tea, subcategory=self.black_sub)
        add_variation(cinnamon, "100", self.g, "WEIGHT", "650", stock=4, user=self.owner)
        activate(cinnamon)
        r = self.client.get(reverse("shop:category", args=[self.leo_tea.slug]), {"q": "Cinnamon"})
        self.assertEqual([p.name for p in r.context["page_obj"]], ["Cinnamon Tea"])
        r = self.client.get(reverse("shop:category", args=[self.leo_tea.slug]), {"q": "Ginger"})
        self.assertEqual([p.name for p in r.context["page_obj"]], ["Ginger Tea Bags"])


class RestructureMigrationTests(ShopTestCase):
    """The data migration on a database that still has the old layout."""

    def test_moves_products_without_losing_or_duplicating(self):
        # Rebuild the pre-Phase-11 layout around the fixture products.
        old_bags = Category.objects.create(name="TEA BAGS", sort_order=2)
        old_ginger_bags = Category.objects.create(name="Ginger Tea Bags", parent=old_bags)
        old_black = Category.objects.create(name="Black Tea", parent=self.leo_tea)
        Product.objects.filter(pk=self.ginger.pk).update(category=old_bags, subcategory=old_ginger_bags)
        Product.objects.filter(pk=self.black.pk).update(subcategory=old_black)
        raw = InventoryItem.objects.create(kind=InventoryItem.Kind.RAW_MATERIAL, name="Bag paper", category=old_ginger_bags,
                                           stock_unit=self.pieces)
        loose_bags = Product.objects.create(name="Cinnamon Bags", category=self.leo_tea)   # no subcategory, sold by the bag
        add_variation(loose_bags, "20", self.bags, "COUNT", "400")
        before = (Product.objects.count(), set(Product.objects.values_list("pk", "slug")))

        restructure(django_apps, None)
        restructure(django_apps, None)  # safe to run twice

        self.assertEqual((Product.objects.count(), set(Product.objects.values_list("pk", "slug"))), before)
        self.ginger.refresh_from_db(); self.black.refresh_from_db(); loose_bags.refresh_from_db(); raw.refresh_from_db()
        self.assertEqual((self.ginger.category, self.ginger.subcategory), (self.leo_tea, self.tea_bags))
        self.assertEqual((self.black.category, self.black.subcategory), (self.leo_tea, self.black_sub))  # Tea Packets
        self.assertEqual(loose_bags.subcategory, self.tea_bags)
        self.assertEqual(raw.category, self.tea_bags)
        self.assertEqual(self.kokis.subcategory, self.kokis_sub)  # sweets untouched
        for old in (old_bags, old_ginger_bags, old_black):
            self.assertFalse(Category.objects.filter(pk=old.pk).exists())
        self.assertEqual(list(Category.objects.main().values_list("name", flat=True)), ["LEO TEA", "LEO SWEETS"])
        self.assertEqual(self.g25.inventory_item.quantity, 3)  # stock unchanged

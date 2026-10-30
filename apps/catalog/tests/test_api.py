from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product

from .helpers import CatalogTestCase, image_file, make_product, make_variation


class CatalogApiTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def test_only_owner_and_manager_have_access(self):
        product = make_product()
        urls = [reverse("api:catalog-product-list"), reverse("api:catalog-category-list"),
                reverse("api:catalog-variation-list"), reverse("api:catalog-unit-list"),
                reverse("api:catalog-product-detail", args=[product.pk])]
        for user, expected in ((self.owner, 200), (self.manager, 200), (self.it_admin, 403), (self.cashier, 403), (self.customer, 403), (None, 403)):
            self.api.force_authenticate(user)
            for url in urls:
                with self.subTest(user=getattr(user, "role", "anon"), url=url):
                    self.assertEqual(self.api.get(url).status_code, expected)
        self.api.force_authenticate(self.cashier)
        r = self.api.post(reverse("api:catalog-category-list"), {"name": "Hacked"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Category.objects.filter(name="Hacked").exists())

    def test_create_product_and_variation(self):
        self.api.force_authenticate(self.manager)
        r = self.api.post(reverse("api:catalog-product-list"),
                          {"name": "API Tea", "category": self.leo_tea.pk, "subcategory": self.black_tea.pk, "status": "DRAFT"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        product = Product.objects.get(name="API Tea")
        self.assertEqual(product.created_by, self.manager)
        r = self.api.post(reverse("api:catalog-variation-list"), {
            "product": product.pk, "measurement_type": "WEIGHT", "quantity": "400", "unit": self.gram.pk,
            "selling_price": "1800.00"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["sku"], f"LEO-LT-{product.pk:04d}-400G")
        self.assertEqual(r.json()["size_label"], "400g")

    def test_validation_matches_web_forms(self):
        self.api.force_authenticate(self.owner)
        product = make_product()
        make_variation(product, "200", sku="LEO-TAKEN")
        url = reverse("api:catalog-variation-list")
        base = {"product": product.pk, "measurement_type": "WEIGHT", "quantity": "500", "unit": self.gram.pk, "selling_price": "10"}
        cases = {
            "negative price": {"selling_price": "-1"},
            "zero quantity": {"quantity": "0"},
            "duplicate sku (case)": {"sku": "leo-taken"},
            "unit/measurement mismatch": {"unit": self.bags.pk},
            "duplicate size": {"quantity": "200"},
            "wholesale above selling": {"wholesale_price": "20"},
        }
        for label, override in cases.items():
            with self.subTest(label):
                self.assertEqual(self.api.post(url, {**base, **override}, format="json").status_code, 400)
        r = self.api.post(reverse("api:catalog-product-list"), {"name": "X", "category": self.leo_tea.pk, "subcategory": self.kokis.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(reverse("api:catalog-category-list"), {"name": "black tea", "parent": self.leo_tea.pk}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_cannot_activate_product_without_variation(self):
        self.api.force_authenticate(self.owner)
        product = make_product()
        r = self.api.patch(reverse("api:catalog-product-detail", args=[product.pk]), {"status": "ACTIVE"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_delete_is_not_allowed(self):
        self.api.force_authenticate(self.owner)
        product = make_product()
        self.assertEqual(self.api.delete(reverse("api:catalog-product-detail", args=[product.pk])).status_code, 405)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_filters_and_image_upload(self):
        self.api.force_authenticate(self.owner)
        make_product("Searchable Tea")
        make_product("Other")
        r = self.api.get(reverse("api:catalog-product-list"), {"q": "searchable"})
        self.assertEqual([p["name"] for p in r.json()["results"]], ["Searchable Tea"])
        r = self.api.post(reverse("api:catalog-category-list"), {"name": "Pictured", "image": image_file()}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("/media/catalog/categories/", r.json()["image"])
        r = self.api.post(reverse("api:catalog-category-list"),
                          {"name": "Bad", "image": image_file("x.gif", "GIF")}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_prices_are_decimal_strings(self):
        self.api.force_authenticate(self.owner)
        product = make_product()
        make_variation(product, price="1250.50", wholesale_price=Decimal("999.99"))
        data = self.api.get(reverse("api:catalog-variation-list")).json()["results"][0]
        self.assertEqual((data["selling_price"], data["wholesale_price"]), ("1250.50", "999.99"))

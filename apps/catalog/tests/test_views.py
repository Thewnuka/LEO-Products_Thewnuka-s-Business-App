from decimal import Decimal

from django.urls import reverse

from apps.catalog.models import Category, MeasurementType, Product, ProductVariation, Unit

from .helpers import CatalogTestCase, image_file, make_product, make_variation


class CatalogPermissionTests(CatalogTestCase):
    """Every catalogue URL: Owner/Manager allowed; IT Admin, Cashier, Customer refused; anonymous redirected."""

    def urls(self):
        product = make_product()
        variation = make_variation(product)
        return [
            ("get", reverse("catalog:dashboard")),
            ("get", reverse("catalog:product_list")),
            ("get", reverse("catalog:product_create")),
            ("get", reverse("catalog:product_detail", args=[product.pk])),
            ("get", reverse("catalog:product_update", args=[product.pk])),
            ("post", reverse("catalog:product_status", args=[product.pk])),
            ("get", reverse("catalog:variation_list", args=[product.pk])),
            ("get", reverse("catalog:variation_create", args=[product.pk])),
            ("get", reverse("catalog:variation_update", args=[product.pk, variation.pk])),
            ("post", reverse("catalog:variation_toggle", args=[product.pk, variation.pk])),
            ("get", reverse("catalog:category_list")),
            ("get", reverse("catalog:category_create")),
            ("get", reverse("catalog:category_update", args=[self.tea_packets.pk])),
            ("post", reverse("catalog:category_toggle", args=[self.tea_packets.pk])),
            ("post", reverse("catalog:category_delete", args=[self.tea_packets.pk])),
            ("get", reverse("catalog:unit_list")),
            ("get", reverse("catalog:unit_create")),
            ("get", reverse("catalog:unit_update", args=[self.gram.pk])),
            ("post", reverse("catalog:unit_toggle", args=[self.gram.pk])),
        ]

    def test_refused_roles_get_403_and_change_nothing(self):
        urls = self.urls()
        for user in (self.it_admin, self.cashier, self.customer):
            self.client.force_login(user)
            for method, url in urls:
                with self.subTest(role=user.role, url=url):
                    response = getattr(self.client, method)(url, {"status": "ACTIVE"} if method == "post" else None)
                    self.assertEqual(response.status_code, 403)
        self.assertTrue(Category.objects.get(pk=self.tea_packets.pk).is_active)
        self.assertTrue(Unit.objects.get(pk=self.gram.pk).is_active)
        self.assertTrue(ProductVariation.objects.get().is_active)

    def test_anonymous_redirected_to_staff_login(self):
        for method, url in self.urls():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(reverse("accounts:staff_login")))

    def test_owner_and_manager_can_open_every_page(self):
        urls = [u for m, u in self.urls() if m == "get"]
        for user in (self.owner, self.manager):
            self.client.force_login(user)
            for url in urls:
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_sidebar_link_only_for_catalogue_roles(self):
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("dashboard:manager")), reverse("catalog:product_list"))
        self.client.force_login(self.it_admin)
        self.assertNotContains(self.client.get(reverse("dashboard:it_admin")), reverse("catalog:product_list"))


class CategoryViewTests(CatalogTestCase):
    def test_create_main_and_subcategory(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse("catalog:category_create"), {"name": "LEO SPICES", "sort_order": 4, "is_active": "on"})
        self.assertRedirects(r, reverse("catalog:category_list"))
        spices = Category.objects.get(name="LEO SPICES")
        self.client.post(reverse("catalog:category_create"), {"name": "Pepper", "parent": spices.pk, "sort_order": 1, "is_active": "on"})
        self.assertTrue(Category.objects.filter(name="Pepper", parent=spices).exists())

    def test_create_with_image(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("catalog:category_create"),
                         {"name": "With Image", "sort_order": 0, "is_active": "on", "image": image_file()})
        cat = Category.objects.get(name="With Image")
        self.assertTrue(cat.image.name.startswith("catalog/categories/"))

    def test_duplicate_category_shows_error(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("catalog:category_create"), {"name": "tea BAGS", "parent": self.leo_tea.pk, "sort_order": 0})
        self.assertEqual(r.status_code, 200)
        self.assertIn("name", r.context["form"].errors)

    def test_rename_and_deactivate(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("catalog:category_update", args=[self.kokis.pk]),
                         {"name": "Kokis (Traditional)", "parent": self.sweets.pk, "sort_order": 1, "is_active": "on"})
        self.kokis.refresh_from_db()
        self.assertEqual(self.kokis.name, "Kokis (Traditional)")
        self.client.post(reverse("catalog:category_toggle", args=[self.kokis.pk]))
        self.kokis.refresh_from_db()
        self.assertFalse(self.kokis.is_active)

    def test_delete_only_when_empty(self):
        self.client.force_login(self.owner)
        make_product(category=self.leo_tea, subcategory=self.tea_packets)
        r = self.client.post(reverse("catalog:category_delete", args=[self.tea_packets.pk]))
        self.assertRedirects(r, reverse("catalog:category_update", args=[self.tea_packets.pk]))
        self.assertTrue(Category.objects.filter(pk=self.tea_packets.pk).exists())
        empty = Category.objects.create(name="Temporary")
        self.client.post(reverse("catalog:category_delete", args=[empty.pk]))
        self.assertFalse(Category.objects.filter(pk=empty.pk).exists())
        self.assertEqual(self.client.get(reverse("catalog:category_delete", args=[empty.pk])).status_code, 405)


class ProductViewTests(CatalogTestCase):
    def test_create_product_then_redirect_to_variations(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse("catalog:product_create"), {
            "name": "Premium Black Tea", "category": self.leo_tea.pk, "subcategory": self.tea_packets.pk,
            "description": "Strong and bright.", "status": "DRAFT", "image": image_file("tea.jpg", "JPEG"),
        })
        product = Product.objects.get(name="Premium Black Tea")
        self.assertRedirects(r, reverse("catalog:variation_create", args=[product.pk]))
        self.assertEqual(product.created_by, self.manager)
        self.assertEqual(product.slug, "premium-black-tea")
        self.assertTrue(product.image.name.startswith("catalog/products/"))

    def test_new_product_cannot_start_active(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("catalog:product_create"), {"name": "X", "category": self.leo_tea.pk, "status": "ACTIVE"})
        self.assertIn("status", r.context["form"].errors)

    def test_mismatched_subcategory_rejected(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("catalog:product_create"), {"name": "X", "category": self.leo_tea.pk, "subcategory": self.kokis.pk, "status": "DRAFT"})
        self.assertIn("subcategory", r.context["form"].errors)
        self.assertFalse(Product.objects.exists())

    def test_edit_product_and_replace_image(self):
        self.client.force_login(self.owner)
        product = make_product()
        data = {"name": "Renamed Tea", "category": self.leo_tea.pk, "status": "DRAFT", "slug": product.slug}
        self.client.post(reverse("catalog:product_update", args=[product.pk]), {**data, "image": image_file("a.png")})
        product.refresh_from_db()
        first = product.image.name
        storage = product.image.storage
        self.assertTrue(storage.exists(first))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("catalog:product_update", args=[product.pk]), {**data, "image": image_file("b.webp", "WEBP")})
        product.refresh_from_db()
        self.assertEqual(product.name, "Renamed Tea")
        self.assertNotEqual(product.image.name, first)
        self.assertFalse(storage.exists(first))  # old file cleaned up
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("catalog:product_update", args=[product.pk]), {**data, "remove_image": "on"})
        product.refresh_from_db()
        self.assertFalse(product.image)

    def test_status_changes(self):
        self.client.force_login(self.manager)
        product = make_product()
        url = reverse("catalog:product_status", args=[product.pk])
        self.client.post(url, {"status": "ACTIVE"})
        product.refresh_from_db()
        self.assertEqual(product.status, "DRAFT")  # refused: no variations yet
        make_variation(product)
        self.client.post(url, {"status": "ACTIVE"})
        product.refresh_from_db()
        self.assertEqual(product.status, "ACTIVE")
        self.client.post(url, {"status": "INACTIVE"})
        product.refresh_from_db()
        self.assertEqual(product.status, "INACTIVE")
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_detail_shows_variations_and_placeholder(self):
        self.client.force_login(self.owner)
        product = make_product()
        make_variation(product, price="1250.50", wholesale_price=Decimal("1100"))
        r = self.client.get(reverse("catalog:product_detail", args=[product.pk]))
        self.assertContains(r, "LKR 1,250.50")
        self.assertContains(r, "LKR 1,100.00")
        self.assertContains(r, "placeholder-product.svg")


class VariationViewTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product = make_product()
        self.client.force_login(self.manager)
        self.url = reverse("catalog:variation_create", args=[self.product.pk])

    def post(self, **overrides):
        data = {"measurement_type": "WEIGHT", "quantity": "200", "unit": self.gram.pk, "name": "", "sku": "",
                "selling_price": "950.00", "wholesale_price": "", "sort_order": 0, "is_active": "on"}
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_create_with_generated_sku(self):
        r = self.post()
        self.assertRedirects(r, reverse("catalog:variation_list", args=[self.product.pk]))
        v = self.product.variations.get()
        self.assertEqual(v.sku, f"LEO-LT-{self.product.pk:04d}-200G")
        self.assertEqual(v.selling_price, Decimal("950.00"))
        self.assertEqual(v.created_by, self.manager)

    def test_custom_sku_uppercased_and_unique(self):
        self.post(sku="leo-black-200")
        self.assertTrue(ProductVariation.objects.filter(sku="LEO-BLACK-200").exists())
        r = self.post(quantity="400", sku="Leo-Black-200")
        self.assertIn("sku", r.context["form"].errors)
        r = self.post(quantity="500", sku="bad sku!")
        self.assertIn("sku", r.context["form"].errors)

    def test_invalid_prices_and_quantities(self):
        for field, value in (("selling_price", "0"), ("selling_price", "-10"), ("quantity", "0"), ("quantity", "-1"),
                             ("wholesale_price", "0"), ("wholesale_price", "2000")):
            with self.subTest(field=field, value=value):
                r = self.post(**{field: value})
                self.assertEqual(r.status_code, 200)
                self.assertIn(field, r.context["form"].errors)
        self.assertFalse(self.product.variations.exists())

    def test_unit_must_match_measurement_type(self):
        r = self.post(measurement_type="WEIGHT", unit=self.bags.pk, quantity="25")
        self.assertIn("unit", r.context["form"].errors)

    def test_duplicate_size_rejected(self):
        self.post()
        r = self.post(sku="")
        self.assertIn("quantity", r.context["form"].errors)
        self.assertEqual(self.product.variations.count(), 1)

    def test_count_and_piece_variations_through_form(self):
        bags_product = make_product("Ginger Tea Bags", category=self.leo_tea, subcategory=self.tea_bags)
        self.url = reverse("catalog:variation_create", args=[bags_product.pk])
        self.post(measurement_type="COUNT", unit=self.bags.pk, quantity="25", selling_price="600")
        sweets = make_product("Kokis Box", category=self.sweets, subcategory=self.kokis)
        self.url = reverse("catalog:variation_create", args=[sweets.pk])
        self.post(measurement_type="PIECE", unit=self.pieces.pk, quantity="10", selling_price="500", image=image_file())
        self.assertEqual(bags_product.variations.get().display_name, "25 bags")
        piece = sweets.variations.get()
        self.assertEqual(piece.display_name, "10 pieces")
        self.assertTrue(piece.image.name.startswith("catalog/variations/"))

    def test_edit_and_toggle(self):
        v = make_variation(self.product)
        url = reverse("catalog:variation_update", args=[self.product.pk, v.pk])
        self.client.post(url, {"measurement_type": "WEIGHT", "quantity": "200", "unit": self.gram.pk, "sku": v.sku,
                               "selling_price": "1200", "sort_order": 0, "is_active": "on"})
        v.refresh_from_db()
        self.assertEqual(v.selling_price, Decimal("1200"))
        self.client.post(reverse("catalog:variation_toggle", args=[self.product.pk, v.pk]))
        v.refresh_from_db()
        self.assertFalse(v.is_active)

    def test_last_active_variation_of_active_product_cannot_be_deactivated(self):
        v = make_variation(self.product)
        self.product.status = Product.Status.ACTIVE
        self.product.save()
        self.client.post(reverse("catalog:variation_toggle", args=[self.product.pk, v.pk]))
        v.refresh_from_db()
        self.assertTrue(v.is_active)

    def test_last_active_variation_rule_also_applies_to_edit_form_and_api(self):
        from rest_framework.test import APIClient

        v = make_variation(self.product)
        self.product.status = Product.Status.ACTIVE
        self.product.save()
        r = self.client.post(reverse("catalog:variation_update", args=[self.product.pk, v.pk]),
                             {"measurement_type": "WEIGHT", "quantity": "200", "unit": self.gram.pk, "sku": v.sku,
                              "selling_price": "1000", "sort_order": 0})  # "is_active" unticked
        self.assertIn("is_active", r.context["form"].errors)
        api = APIClient()
        api.force_authenticate(self.manager)
        r = api.patch(reverse("api:catalog-variation-detail", args=[v.pk]), {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 400)
        v.refresh_from_db()
        self.assertTrue(v.is_active)

    def test_variation_of_other_product_not_reachable(self):
        other = make_product("Other")
        v = make_variation(other)
        r = self.client.get(reverse("catalog:variation_update", args=[self.product.pk, v.pk]))
        self.assertEqual(r.status_code, 404)

    def test_new_unit_via_form(self):
        self.client.post(reverse("catalog:unit_create"), {"measurement_type": "COUNT", "name": "Pack", "symbol": "packs", "sort_order": 2, "is_active": "on"})
        packs = Unit.objects.get(symbol="packs")
        self.post(measurement_type="COUNT", unit=packs.pk, quantity="3")
        self.assertEqual(self.product.variations.get().display_name, "3 packs")
        r = self.client.post(reverse("catalog:unit_create"), {"measurement_type": "COUNT", "name": "Packs", "symbol": "PACKS", "sort_order": 0})
        self.assertEqual(r.status_code, 200)  # duplicate symbol in same type


class SearchFilterPaginationTests(CatalogTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for i in range(15):
            p = make_product(f"Black Tea {i:02d}", category=cls.leo_tea, subcategory=cls.tea_packets)
            make_variation(p, "200", price=str(100 + i))
        cls.bags_product = make_product("Ginger Bags", category=cls.leo_tea, subcategory=cls.tea_bags)
        cls.bag_variation = make_variation(cls.bags_product, "25", cls.bags, price="50", measurement=MeasurementType.COUNT, sku="LEO-GINGER-25")
        make_variation(cls.bags_product, "50", cls.bags, price="90", measurement=MeasurementType.COUNT)
        cls.bags_product.status = Product.Status.ACTIVE
        cls.bags_product.save()

    def get(self, **params):
        self.client.force_login(self.owner)
        return self.client.get(reverse("catalog:product_list"), params)

    def names(self, response):
        return [p.name for p in response.context["page_obj"]]

    def test_search_by_name_and_sku(self):
        self.assertEqual(self.names(self.get(q="ginger")), ["Ginger Bags"])
        self.assertEqual(self.names(self.get(q="leo-ginger")), ["Ginger Bags"])

    def test_filters(self):
        self.assertEqual(self.names(self.get(subcategory=self.tea_bags.pk)), ["Ginger Bags"])
        self.assertEqual(self.get(subcategory=self.tea_packets.pk).context["page_obj"].paginator.count, 15)
        self.assertEqual(self.names(self.get(status="ACTIVE")), ["Ginger Bags"])
        self.assertEqual(self.names(self.get(measurement="COUNT")), ["Ginger Bags"])
        self.assertEqual(self.get(measurement="WEIGHT").context["page_obj"].paginator.count, 15)

    def test_invalid_filter_values_are_ignored(self):
        r = self.get(category="abc", status="NOPE", sort="drop table")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page_obj"].paginator.count, 16)

    def test_sorting(self):
        self.assertEqual(self.names(self.get(sort="-name"))[0], "Ginger Bags")
        # Ginger Bags: LKR 50–90; Black Tea NN: LKR 100–114.
        self.assertEqual(self.names(self.get(sort="price"))[:2], ["Ginger Bags", "Black Tea 00"])
        self.assertEqual(self.names(self.get(sort="-price"))[0], "Black Tea 14")
        self.assertEqual(self.names(self.get(sort="-price"))[-1], "Black Tea 03")  # page 1 of 2 (12 per page)

    def test_pagination_keeps_filters(self):
        r = self.get(q="black", status="DRAFT", sort="-name")
        page = r.context["page_obj"]
        self.assertEqual(page.paginator.num_pages, 2)
        self.assertContains(r, "q=black&amp;status=DRAFT&amp;sort=-name&page=2")
        r2 = self.get(q="black", status="DRAFT", sort="-name", page=2)
        self.assertEqual(len(r2.context["page_obj"]), 3)
        self.assertEqual(self.names(r2)[-1], "Black Tea 00")

    def test_table_view(self):
        r = self.get(view="table", q="ginger")
        self.assertContains(r, "Price range")
        self.assertContains(r, "LKR")

from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.inventory.services import record_movement

from .helpers import D, ShopTestCase, activate, add_variation


class ListingTests(ShopTestCase):
    def names(self, response):
        if "page_obj" in response.context:
            return [p.name for p in response.context["page_obj"]]
        return [p.name for _, products in response.context["sections"] for p in products]

    def test_only_active_products_are_listed(self):
        r = self.client.get(reverse("shop:home"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(self.names(r)), {"Black Tea", "Ginger Tea Bags", "Kokis"})
        self.assertNotContains(r, "Draft Tea")

    def test_products_grouped_under_their_categories(self):
        sections = self.client.get(reverse("shop:home")).context["sections"]
        self.assertEqual([(c.name, [p.name for p in ps]) for c, ps in sections],
                         [("LEO TEA", ["Ginger Tea Bags", "Black Tea"]), ("LEO SWEETS", ["Kokis"])])  # Tea Bags, then Tea Packets

    def test_hidden_when_category_unavailable(self):
        self.black_sub.is_active = False
        self.black_sub.save()
        r = self.client.get(reverse("shop:home"))
        self.assertEqual(set(self.names(r)), {"Ginger Tea Bags", "Kokis"})

    def test_out_of_stock_products_are_listed_but_not_buyable(self):
        # Phase 11: customers see the whole range; sold-out products are marked and can't be added.
        record_movement(self.k10.inventory_item, "DECREASE", "20", self.owner, reason="sold out")
        r = self.client.get(reverse("shop:home"))
        kokis = next(p for _, ps in r.context["sections"] for p in ps if p.name == "Kokis")
        self.assertEqual((kokis.available_count, kokis.card_options), (0, []))
        self.assertEqual(kokis.from_price, self.k10.selling_price)
        self.assertContains(r, "Out of stock")
        self.assertNotContains(r, f'name="variation" value="{self.k10.pk}"')

    def test_product_without_any_stock_record_is_listed(self):
        # e.g. a product created by staff before its stock is entered in Inventory
        p = Product.objects.create(name="New Cinnamon Tea", category=self.leo_tea, description="Warm and sweet.")
        add_variation(p, "100", self.g, "WEIGHT", "700")
        activate(p)
        r = self.client.get(reverse("shop:category", args=[self.leo_tea.slug]))
        self.assertIn("New Cinnamon Tea", self.names(r))
        self.assertContains(r, "Warm and sweet.")
        self.assertContains(r, "LKR 700.00")

    def test_inactive_variation_hides_product_without_other_options(self):
        self.k10.is_active = False
        self.k10.save()
        self.assertNotIn("Kokis", self.names(self.client.get(reverse("shop:home"))))
        item = self.g25.inventory_item
        item.is_active = False
        item.save()
        self.assertIn("Ginger Tea Bags", self.names(self.client.get(reverse("shop:home"))))  # listed, not buyable

    def test_new_category_and_product_appear_dynamically(self):
        spices = Category.objects.create(name="LEO SPICES", sort_order=9)
        pepper = Product.objects.create(name="Black Pepper", category=spices)
        add_variation(pepper, "100", self.g, "WEIGHT", "650", stock=5, user=self.owner)
        activate(pepper)
        sections = self.client.get(reverse("shop:home")).context["sections"]
        self.assertIn(("LEO SPICES", ["Black Pepper"]), [(c.name, [p.name for p in ps]) for c, ps in sections])

    def test_category_pages(self):
        r = self.client.get(reverse("shop:category", args=[self.leo_tea.slug]))
        self.assertEqual(self.names(r), ["Ginger Tea Bags", "Black Tea"])
        r = self.client.get(reverse("shop:category", args=[self.kokis_sub.slug]))
        self.assertEqual(self.names(r), ["Kokis"])
        self.assertContains(r, "LEO SWEETS")  # breadcrumb to parent
        self.leo_tea.is_active = False
        self.leo_tea.save()
        self.assertEqual(self.client.get(reverse("shop:category", args=[self.leo_tea.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("shop:category", args=["no-such-category"])).status_code, 404)

    def test_card_shows_from_price_and_only_available_options(self):
        r = self.client.get(reverse("shop:home"))
        black = next(p for _, ps in r.context["sections"] for p in ps if p.name == "Black Tea")
        self.assertEqual(black.from_price, D("500"))
        self.assertEqual([v.pk for v in black.card_options], [self.b200.pk])
        self.assertContains(r, "LKR 500.00")
        self.assertContains(r, "Add to cart")
        self.assertContains(r, reverse("shop:product", args=[self.black.slug]))

    def test_wholesale_price_never_shown(self):
        for url in (reverse("shop:home"), reverse("shop:product", args=[self.ginger.slug]),
                    reverse("shop:category", args=[self.tea_bags.slug])):
            self.assertNotContains(self.client.get(url), "399")

    def test_empty_shop_message(self):
        Product.objects.update(status=Product.Status.INACTIVE)
        r = self.client.get(reverse("shop:home"))
        self.assertContains(r, "Our shop is getting ready")


class SearchSortTests(ShopTestCase):
    def names(self, **params):
        return [p.name for p in self.client.get(reverse("shop:home"), params).context["page_obj"]]

    def test_search_by_name_description_and_category(self):
        self.assertEqual(self.names(q="ginger"), ["Ginger Tea Bags"])
        self.assertEqual(self.names(q="morning"), ["Black Tea"])          # description
        self.assertEqual(self.names(q="sweets"), ["Kokis"])               # category name
        self.assertEqual(self.names(q="draft"), [])                       # never shows hidden products

    def test_no_results_message(self):
        r = self.client.get(reverse("shop:home"), {"q": "chocolate"})
        self.assertContains(r, "No products found")

    def test_relevance_puts_name_matches_first(self):
        self.assertEqual(self.names(q="tea")[:2], ["Black Tea", "Ginger Tea Bags"])

    def test_sorting(self):
        self.assertEqual(self.names(sort="price_asc"), ["Kokis", "Ginger Tea Bags", "Black Tea"])
        self.assertEqual(self.names(sort="price_desc"), ["Black Tea", "Ginger Tea Bags", "Kokis"])
        self.assertEqual(self.names(sort="newest")[0], "Kokis")
        self.assertEqual(self.names(sort="name"), ["Black Tea", "Ginger Tea Bags", "Kokis"])
        self.assertEqual(self.client.get(reverse("shop:home"), {"sort": "DROP TABLE"}).status_code, 200)

    def test_category_search_and_sort(self):
        r = self.client.get(reverse("shop:category", args=[self.tea_bags.slug]), {"q": "black"})
        self.assertEqual(list(r.context["page_obj"]), [])

    def test_pagination_keeps_search(self):
        for i in range(13):
            p = Product.objects.create(name=f"Tea Blend {i:02d}", category=self.leo_tea)
            add_variation(p, "100", self.g, "WEIGHT", str(100 + i), stock=5, user=self.owner)
            activate(p)
        r = self.client.get(reverse("shop:home"), {"q": "blend", "sort": "price_asc"})
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(r, "q=blend&amp;sort=price_asc&page=2")
        r2 = self.client.get(reverse("shop:home"), {"q": "blend", "sort": "price_asc", "page": 2})
        self.assertEqual([p.name for p in r2.context["page_obj"]], ["Tea Blend 12"])


class ProductDetailTests(ShopTestCase):
    def test_shows_all_options_with_unavailable_disabled(self):
        r = self.client.get(reverse("shop:product", args=[self.black.slug]))
        variations = {v.pk: v for v in r.context["variations"]}
        self.assertEqual(variations[self.b200.pk].available, 10)
        self.assertEqual(variations[self.b400.pk].available, 0)
        self.assertEqual(variations[self.b1kg.pk].available, 0)
        self.assertEqual(r.context["selected"].pk, self.b200.pk)
        html = r.content.decode()
        self.assertRegex(html, rf'value="{self.b400.pk}"[^>]*disabled')
        self.assertRegex(html, rf'value="{self.b1kg.pk}"[^>]*disabled')
        self.assertContains(r, "Out of stock")
        self.assertContains(r, 'max="10"')

    def test_option_query_selects_variation_and_ignores_unavailable(self):
        extra = add_variation(self.black, "500", self.g, "WEIGHT", "1100", stock=2, user=self.owner)
        r = self.client.get(reverse("shop:product", args=[self.black.slug]), {"option": extra.pk})
        self.assertEqual(r.context["selected"].pk, extra.pk)
        self.assertContains(r, "Only 2 left")
        r = self.client.get(reverse("shop:product", args=[self.black.slug]), {"option": self.b400.pk})
        self.assertEqual(r.context["selected"].pk, self.b200.pk)  # out-of-stock option can't be pre-selected

    def test_count_and_piece_variations(self):
        self.assertContains(self.client.get(reverse("shop:product", args=[self.ginger.slug])), "25 bags")
        self.assertContains(self.client.get(reverse("shop:product", args=[self.kokis.slug])), "10 pieces")

    def test_draft_or_hidden_category_products_404(self):
        self.assertEqual(self.client.get(reverse("shop:product", args=[self.draft.slug])).status_code, 404)
        self.kokis_sub.is_active = False
        self.kokis_sub.save()
        self.assertEqual(self.client.get(reverse("shop:product", args=[self.kokis.slug])).status_code, 404)

    def test_sold_out_product_page_says_unavailable(self):
        record_movement(self.k10.inventory_item, "DECREASE", "20", self.owner, reason="sold")
        r = self.client.get(reverse("shop:product", args=[self.kokis.slug]))
        self.assertContains(r, "Out of stock: this product can't be ordered right now")
        self.assertNotContains(r, 'name="quantity"')

    def test_staff_can_browse_but_not_buy(self):
        self.client.force_login(self.manager)
        r = self.client.get(reverse("shop:product", args=[self.black.slug]))
        self.assertContains(r, "staff account")
        self.assertNotContains(r, 'name="quantity"')


class StaffShopPanelTests(ShopTestCase):
    """Phase 11: the staff product page says whether customers can buy the product, and why not."""

    def panel(self, product):
        self.client.force_login(self.owner)
        return self.client.get(reverse("catalog:product_detail", args=[product.pk]))

    def test_states(self):
        r = self.panel(self.black)
        self.assertEqual(r.context["shop"]["state"], "buyable")
        self.assertContains(r, "10 in stock")
        self.assertContains(r, f"?variation={self.b1kg.pk}")  # untracked option -> start tracking stock
        new = Product.objects.create(name="New Tea", category=self.leo_tea)
        add_variation(new, "100", self.g, "WEIGHT", "700")
        self.assertEqual(self.panel(new).context["shop"]["state"], "hidden")  # still a draft
        activate(new)
        r = self.panel(new)
        self.assertEqual(r.context["shop"]["state"], "out")
        self.assertContains(r, "No stock record")

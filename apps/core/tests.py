from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base.html")
        self.assertTemplateUsed(response, "core/home.html")
        self.assertTemplateUsed(response, "partials/_logo.html")
        self.assertContains(response, settings.BRAND["NAME"])
        self.assertContains(response, settings.BRAND["TAGLINE"])

    def test_logo_comes_from_central_setting(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, settings.BRAND["LOGO"])

    def test_no_buying_controls_on_landing_page(self):
        # Buying happens in the shop; the landing page only links to it.
        response = self.client.get(reverse("core:home"))
        for word in ("Add to cart", "Buy now"):
            self.assertNotContains(response, word)
        self.assertContains(response, reverse("shop:home"))

    def test_account_links_for_visitors(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, reverse("accounts:customer_login"))
        self.assertContains(response, reverse("accounts:register"))
        self.assertContains(response, reverse("accounts:staff_login"))


class BrandContextTests(TestCase):
    def test_brand_context_available(self):
        response = self.client.get(reverse("core:home"))
        brand = response.context["brand"]
        self.assertEqual(brand["name"], "LEO PRODUCTS")
        self.assertEqual(brand["logo"], "images/leo-logo.png")


class StaticFilesTests(SimpleTestCase):
    def test_required_static_files_exist(self):
        for path in (
            "images/leo-logo.png",
            "css/leo.css",
            "js/leo.js",
            "vendor/bootstrap/css/bootstrap.min.css",
            "vendor/bootstrap/js/bootstrap.bundle.min.js",
            "vendor/bootstrap-icons/bootstrap-icons.min.css",
            "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path), f"{path} not found")


class TemplateLoadingTests(SimpleTestCase):
    def test_templates_compile(self):
        for name in (
            "base.html",
            "layouts/sidebar.html",
            "core/home.html",
            "core/style_guide.html",
            "partials/_logo.html",
            "partials/_navbar.html",
            "partials/_footer.html",
            "partials/_messages.html",
            "partials/_alert.html",
            "400.html",
            "403.html",
            "404.html",
            "500.html",
        ):
            with self.subTest(template=name):
                get_template(name)


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def test_404_page_is_branded(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, settings.BRAND["LOGO"], status_code=404)

    def test_error_handlers_render(self):
        from django.test import RequestFactory

        from apps.core import views

        request = RequestFactory().get("/")
        cases = [
            (views.bad_request(request), 400, "Bad request"),
            (views.permission_denied(request), 403, "Access denied"),
            (views.page_not_found(request), 404, "Page not found"),
            (views.server_error(request), 500, "Something went wrong"),
        ]
        for response, status, text in cases:
            with self.subTest(status=status):
                self.assertEqual(response.status_code, status)
                self.assertIn(text, response.content.decode())


class HealthApiTests(TestCase):
    def test_health_endpoint(self):
        response = self.client.get(reverse("api:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

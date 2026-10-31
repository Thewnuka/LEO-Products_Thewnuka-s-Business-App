"""
Phase 10: final security, PWA, deployment and whole-site checks.
"""
import json
import os
import re
import subprocess
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.tests.helpers import PASSWORD
from apps.core import checks
from apps.finance.tests.helpers import FinanceTestCase
from apps.orders.tests.helpers import PM, pdf_slip, slip
from apps.payments import services as payments
from apps.shop import reviews

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", re.I)


class SecurityHeaderTests(FinanceTestCase):
    def test_csp_and_permissions_policy_on_pages(self):
        response = self.client.get(reverse("core:home"))
        csp = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("'unsafe-inline'", csp.split("script-src")[1].split(";")[0])
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_signed_in_pages_are_never_cached(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        for url in (reverse("orders:my_orders"), reverse("accounts:customer_home"), reverse("shop:home")):
            cache = self.client.get(url)["Cache-Control"]
            self.assertIn("no-store", cache, url)
            self.assertIn("private", cache, url)
        self.client.logout()
        self.assertNotIn("no-store", self.client.get(reverse("shop:home")).get("Cache-Control", ""))

    @override_settings(PAYMENT_GATEWAY="payhere")
    def test_gateway_allowed_as_form_target_only_when_configured(self):
        from apps.core.middleware import build_csp

        self.assertIn("https://www.payhere.lk", build_csp())
        with override_settings(PAYMENT_GATEWAY=""):
            self.assertNotIn("payhere", build_csp())

    def test_no_inline_scripts_in_pages(self):
        self.open()
        sale = self.sell()
        pages = {None: [reverse("core:home"), reverse("shop:home"), reverse("accounts:customer_login"),
                        reverse("accounts:staff_login")],
                 self.cashier: [reverse("pos:terminal"), reverse("pos:receipt", args=[sale.number]),
                                reverse("dashboard:cashier")],
                 self.owner: [reverse("finance:dashboard"), reverse("finance:report", args=["sales"]) + "?print=1",
                              reverse("orders:staff_list"), reverse("notifications:list")]}
        for user, urls in pages.items():
            self.client.logout()
            if user:
                self.client.login(username=user.username, password=PASSWORD)
            for url in urls:
                html = self.client.get(url).content.decode()
                self.assertIsNone(INLINE_SCRIPT.search(html), f"inline script on {url}")

    def test_pdf_slips_are_downloaded_not_displayed(self):
        order = self.place(method=PM.BANK_TRANSFER)
        payment = payments.submit_bank_transfer(order, self.customer, "REF", pdf_slip())
        self.client.login(username="owner", password=PASSWORD)
        response = self.client.get(reverse("payments:evidence", args=[payment.reference]))
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        response.close()
        other = self.place(method=PM.BANK_TRANSFER)
        image = payments.submit_bank_transfer(other, self.customer, "REF2", slip())
        response = self.client.get(reverse("payments:evidence", args=[image.reference]))
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        response.close()


class PwaTests(FinanceTestCase):
    def test_manifest(self):
        response = self.client.get(reverse("core:manifest"))
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual((data["name"], data["display"], data["start_url"], data["theme_color"]),
                         ("LEO PRODUCTS", "standalone", "/?source=app", "#123d28"))
        purposes = {icon["purpose"] for icon in data["icons"]}
        self.assertEqual(purposes, {"any", "maskable"})
        for icon in data["icons"]:
            path = icon["src"].replace(settings.STATIC_URL, "", 1).lstrip("/")
            self.assertTrue(finders.find(path), icon["src"])

    def test_service_worker_caches_static_only(self):
        response = self.client.get(reverse("core:service_worker"))
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertIn("no-cache", response["Cache-Control"])
        js = response.content.decode()
        self.assertIn('const STATIC_PREFIX = "/static/"', js)
        self.assertIn('request.method !== "GET"', js)
        precache = re.search(r"const PRECACHE = \[(.*?)\];", js).group(1)
        for url in json.loads(f"[{precache}]"):
            self.assertTrue(url.startswith("/static/"), url)

    def test_offline_page_has_no_personal_data(self):
        self.client.login(username="customer@example.com", password=PASSWORD)
        html = self.client.get(reverse("core:offline")).content.decode()
        self.assertIn("You're offline", html)
        for private in ("customer@example.com", "leo-bell", "Sign out", self.customer.first_name):
            self.assertNotIn(private, html)

    def test_pages_link_manifest_and_register_worker(self):
        html = self.client.get(reverse("shop:home")).content.decode()
        self.assertIn(reverse("core:manifest"), html)
        self.assertIn("apple-touch-icon", html)
        self.assertIn("js/pwa.js", html)


# ---------------------------------------------------------------------------
# Every protected URL: customers and visitors never get a staff page
# ---------------------------------------------------------------------------
SAMPLE = {"int": "1", "str": "x", "slug": "x", "path": "x", "uuid": str(uuid.uuid4())}
CONVERTER = re.compile(r"<(?:(\w+):)?(\w+)>")


def all_routes(patterns=None, prefix=""):
    for p in patterns if patterns is not None else get_resolver().url_patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from all_routes(p.url_patterns, route)
        elif isinstance(p, URLPattern) and not route.startswith("^"):
            yield "/" + CONVERTER.sub(lambda m: SAMPLE.get(m.group(1) or "str", "x"), route)


class AccessSweepTests(FinanceTestCase):
    def protected_routes(self):
        prefixes = ("/staff/", "/" + settings.ADMIN_URL, "/api/v1/")
        public = ("/api/v1/health/",)  # plus the sign-in forms themselves (staff portal and admin)
        return sorted({r for r in all_routes()
                       if r.startswith(prefixes) and r not in public and not r.endswith("/login/")})

    def test_customers_and_visitors_never_get_staff_pages(self):
        routes = self.protected_routes()
        self.assertGreater(len(routes), 80)
        for who in ("anonymous", "customer@example.com"):
            self.client.logout()
            if who != "anonymous":
                self.client.login(username=who, password=PASSWORD)
            for url in routes:
                if who != "anonymous" and url == "/api/v1/accounts/me/":
                    continue  # every signed-in user may read their OWN profile (Phase 02)
                status = self.client.get(url).status_code
                self.assertIn(status, (302, 403, 404, 405), f"{who} got {status} for {url}")

    def test_it_admin_has_no_business_pages(self):
        self.client.login(username="itadmin", password=PASSWORD)
        allowed_prefixes = ("/staff/users/", "/staff/profile/", "/staff/dashboard/", "/staff/alerts/")
        for url in self.protected_routes():
            if url.startswith(allowed_prefixes) or url.startswith("/api/v1/accounts/"):
                continue
            status = self.client.get(url).status_code
            self.assertNotEqual(status, 200, f"IT admin can open {url}")


# ---------------------------------------------------------------------------
# Deployment configuration
# ---------------------------------------------------------------------------
class DeployCheckTests(SimpleTestCase):
    def ids(self, **overrides):
        with override_settings(**overrides):
            return {issue.id for issue in checks.leo_deploy_checks(None)}

    def test_project_deploy_checks(self):
        found = self.ids(ADMIN_URL="admin/", EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
                         PAYMENT_GATEWAY="payhere", PAYHERE_SANDBOX=True)
        self.assertTrue({"leo.W001", "leo.W002", "leo.W003", "leo.W004"} <= found)
        self.assertIn("leo.E001", self.ids(PRIVATE_MEDIA_ROOT=Path(settings.MEDIA_ROOT) / "private"))
        clean = self.ids(ADMIN_URL="office-7381/", EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                         PAYMENT_GATEWAY="", DATABASES={"default": {"ENGINE": "django.db.backends.postgresql"}})
        self.assertEqual(clean, set())

    def run_settings(self, **env):
        base = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.production", "SECRET_KEY": "x" * 60,
                "DATABASE_URL": "sqlite:///:memory:", **env}
        code = "import django; django.setup(); from django.conf import settings; " \
               "print(settings.SESSION_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT, settings.DEBUG)"
        return subprocess.run([sys.executable, "-c", code], env=base, capture_output=True, text=True,
                              cwd=settings.BASE_DIR, timeout=120)

    def test_production_settings_and_local_mode_guard(self):
        normal = self.run_settings(ALLOWED_HOSTS="shop.example.test")
        self.assertEqual(normal.stdout.strip(), "True True False", normal.stderr)
        local = self.run_settings(ALLOWED_HOSTS="127.0.0.1,localhost", LOCAL_HTTP_ONLY="True")
        self.assertEqual(local.stdout.strip(), "False False False", local.stderr)
        refused = self.run_settings(ALLOWED_HOSTS="shop.example.test", LOCAL_HTTP_ONLY="True")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("LOCAL_HTTP_ONLY", refused.stderr)
        missing = self.run_settings(ALLOWED_HOSTS="", DATABASE_URL="")
        self.assertNotEqual(missing.returncode, 0)


# ---------------------------------------------------------------------------
# Whole-site link crawl per role: no server errors, no broken links
# ---------------------------------------------------------------------------
class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in ("img", "script", "link") and (attrs.get("src") or attrs.get("href")):
            self.links.append(attrs.get("src") or attrs.get("href"))


SKIP = ("/logout/", "export=", "mailto:", "tel:", "javascript:", "#", "/sw.js")


class CrawlTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        from apps.inventory.models import InventoryItem

        self.purchase([(InventoryItem.objects.get(variation=self.k10), "5", "100")])
        self.open()
        self.sell()
        self.sell(method="BANK_TRANSFER")
        order = self.place()
        payments.record_cash_payment(order, self.cashier)
        self.place(method=PM.BANK_TRANSFER)
        self.expense("500")
        self.pay_supplier("100")
        reviews.save_review(self.customer, self.black, 5, "Great", "Very good tea")

    def crawl(self, user, start, limit=220):
        self.client.logout()
        if user:
            self.client.login(username=user.username, password=PASSWORD)
        seen, queue, problems = set(), [start], []
        while queue and len(seen) < limit:
            url = queue.pop(0)
            key = urlsplit(url).path
            if key in seen:
                continue
            seen.add(key)
            response = self.client.get(url)
            if response.status_code >= 500 or response.status_code == 404:
                problems.append((url, response.status_code))
                continue
            if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                continue
            parser = _Links()
            parser.feed(response.content.decode())
            for href in parser.links:
                if any(s in href for s in SKIP) or href.startswith(("http://", "https://", "//")):
                    continue
                target = urljoin(url, href)
                if urlsplit(target).path.startswith("/static/"):
                    path = urlsplit(target).path[len("/static/"):]
                    if not finders.find(path):
                        problems.append((f"{url} -> {target}", "missing static file"))
                    continue
                if urlsplit(target).path not in seen:
                    queue.append(target)
        return seen, problems

    def test_no_broken_links_or_errors_for_any_role(self):
        starts = [(None, reverse("core:home")), (self.customer, reverse("accounts:customer_home")),
                  (self.cashier, reverse("dashboard:cashier")), (self.manager, reverse("dashboard:manager")),
                  (self.owner, reverse("dashboard:owner")), (self.it_admin, reverse("dashboard:it_admin"))]
        total = 0
        for user, start in starts:
            seen, problems = self.crawl(user, start)
            total += len(seen)
            self.assertEqual(problems, [], f"{getattr(user, 'username', 'visitor')}: {problems}")
        self.assertGreater(total, 150)

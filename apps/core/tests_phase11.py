"""
Phase 11: customer store layout and staff dashboard navigation.
(Store listing, categories, password toggles and payments are tested in their own apps.)
"""
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.accounts.tests.helpers import AccountsTestCase


def static_text(path):
    with open(finders.find(path), encoding="utf-8") as f:
        return f.read()


class LayoutTests(AccountsTestCase):
    def test_customer_pages_use_the_fluid_page_width(self):
        css = static_text("css/leo.css")
        self.assertIn("max-width: 1600px;\n  padding-inline: clamp(1rem, 3.5vw, 3rem);", css)

    def test_staff_sidebar_scrolls_independently_and_keeps_its_position(self):
        self.client.force_login(self.owner)
        html = self.client.get(reverse("accounts:staff_profile")).content.decode()
        self.assertIn('class="leo-staff-header"', html)
        self.assertIn('class="leo-sidebar"', html)
        css = static_text("css/leo.css")
        sidebar_rule = css.split(".leo-staff-header { position: sticky")[1].split("/* 14.")[0]
        for rule in ("position: sticky;", "overflow-y: auto;", "overscroll-behavior: contain;"):
            self.assertIn(rule, sidebar_rule)
        js = static_text("js/leo.js")
        self.assertIn('"leo-sidebar-scroll"', js)
        self.assertIn("--leo-header-h", js)

"""
Home page hero: background photo, three rotating image cards and the Owner's
"Home page images" manager (Staff portal → Administration).
"""
import os
import re

from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.accounts.tests.helpers import PASSWORD
from apps.catalog.tests.helpers import CatalogTestCase, image_file
from apps.core import hero
from apps.core.models import HomeHeroImage, HomeHeroSettings

URL = reverse("core:hero_images")


def hero_section(html):
    return re.search(r'<section class="leo-hero.*?</section>', html, re.S).group(0)


class HeroHomePageTests(CatalogTestCase):
    def test_sample_images_exist_and_are_used_by_default(self):
        self.assertTrue(finders.find(hero.SAMPLE_BACKGROUND))
        for images in hero.SAMPLE_IMAGES.values():
            for path, alt in images:
                self.assertTrue(finders.find(path), path)
                self.assertTrue(alt)
        data = hero.build_hero()
        self.assertTrue(data["background_is_sample"])
        self.assertTrue(all(card["is_sample"] for card in data["cards"]))
        self.assertEqual([card["box"] for card in data["cards"]], [1, 2, 3])

    def test_cards_and_background_are_inside_the_hero(self):
        html = self.client.get(reverse("core:home")).content.decode()
        section = hero_section(html)
        self.assertIn("leo-hero--photo", section)
        self.assertIn("--leo-hero-bg: url('/static/images/hero/hero-bg.jpg')", section)
        self.assertEqual(section.count("data-hero-card>"), 3)
        for n in (1, 2, 3):
            self.assertIn(f"leo-hero-card--{n}", section)
            self.assertIn(f"/static/images/hero/box{n}-1.jpg", section)
        # Box 1 → Box 3 → Box 2 (0-based card positions), every 3.5 seconds
        self.assertIn('data-order="0,2,1"', section)
        self.assertIn('data-interval="3500"', section)
        self.assertIn("leo-logo.png", section)  # the official logo is kept
        self.assertIn("js/hero.js", html)

    def test_uploaded_images_replace_samples_box_by_box(self):
        item = hero.add_image(self.owner, 3, image_file("mine.png"), "My kokis")
        html = hero_section(self.client.get(reverse("core:home")).content.decode())
        self.assertIn(item.image.url, html)
        self.assertIn('alt="My kokis"', html)
        self.assertNotIn("box3-1.jpg", html)
        self.assertIn("box1-1.jpg", html)  # other boxes keep their samples
        self.assertIn("box2-1.jpg", html)

    def test_uploaded_background_and_focus_are_used(self):
        config = hero.save_background(self.owner, image_file("bg.jpg", "JPEG", (1800, 900)), "left center")
        html = hero_section(self.client.get(reverse("core:home")).content.decode())
        self.assertIn(config.background.url, html)
        self.assertIn("--leo-hero-focus: left center", html)


class HeroManagerPermissionTests(CatalogTestCase):
    def test_only_owner_can_open_and_post(self):
        for user in (self.manager, self.cashier, self.it_admin, self.customer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(URL).status_code, 403, user.role)
            response = self.client.post(URL, {"action": "add", "box_number": 1, "box1-box": 1,
                                              "box1-image": image_file(), "box1-alt_text": "x"})
            self.assertEqual(response.status_code, 403, user.role)
        self.assertFalse(HomeHeroImage.objects.exists())
        self.client.logout()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:staff_login"), response["Location"])

    def test_owner_sees_page_and_sidebar_link(self):
        self.client.login(username="owner", password=PASSWORD)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Background photo")
        for n in (1, 2, 3):
            self.assertContains(response, f'id="box-{n}"')
        self.assertContains(response, f'href="{URL}"')  # sidebar
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse("dashboard:home"), follow=True), f'href="{URL}"')


class HeroManagerUploadTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def add(self, box=1, image=None, alt="Tea leaves"):
        return self.client.post(URL, {"action": "add", "box_number": box, f"box{box}-box": box,
                                      f"box{box}-image": image or image_file(), f"box{box}-alt_text": alt})

    def test_add_valid_image(self):
        response = self.add(2, image_file("tea.webp", "WEBP", (2400, 3200)))
        self.assertRedirects(response, URL)
        item = HomeHeroImage.objects.get()
        self.assertEqual((item.box, item.alt_text, item.created_by), (2, "Tea leaves", self.owner))
        self.assertTrue(item.image.name.startswith("hero/"))
        self.assertTrue(os.path.exists(item.image.path))
        from PIL import Image
        with Image.open(item.image.path) as img:
            self.assertLessEqual(max(img.size), 1600)  # resized by the shared image processing

    def test_rejects_wrong_type_fake_image_and_oversize(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        gif = image_file("a.gif", "GIF")
        fake = SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        for upload in (gif, fake):
            response = self.add(1, upload)
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "is-invalid", status_code=400)
            self.assertContains(response, 'class="invalid-feedback d-block"', status_code=400)
        with self.settings(CATALOG_IMAGE_MAX_BYTES=1024):
            response = self.add(1, image_file("big.png", size=(900, 900), color=(1, 2, 3)))
            self.assertContains(response, "too large", status_code=400)
        self.assertFalse(HomeHeroImage.objects.exists())

    def test_alt_text_and_valid_box_required(self):
        self.assertEqual(self.add(1, alt="").status_code, 400)
        response = self.client.post(URL, {"action": "add", "box_number": 9, "box9-box": 9,
                                          "box9-image": image_file(), "box9-alt_text": "x"})
        self.assertRedirects(response, URL)
        self.assertFalse(HomeHeroImage.objects.exists())

    def test_box_limit(self):
        for _ in range(hero.MAX_IMAGES_PER_BOX):
            hero.add_image(self.owner, 1, image_file(), "x")
        self.assertContains(self.add(1), "up to", status_code=400)
        self.assertEqual(HomeHeroImage.objects.filter(box=1).count(), hero.MAX_IMAGES_PER_BOX)

    def test_replace_image_deletes_old_file(self):
        item = hero.add_image(self.owner, 1, image_file(), "Old")
        old_path = item.image.path
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(URL, {"action": "update", "pk": item.pk, f"img{item.pk}-alt_text": "New",
                                              f"img{item.pk}-sort_order": 5,
                                              f"img{item.pk}-image": image_file("n.jpg", "JPEG")})
        self.assertRedirects(response, URL)
        item.refresh_from_db()
        self.assertEqual((item.alt_text, item.sort_order), ("New", 5))
        self.assertNotEqual(item.image.path, old_path)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(item.image.path))

    def test_edit_without_new_file_keeps_image(self):
        item = hero.add_image(self.owner, 1, image_file(), "Old")
        name = item.image.name
        self.client.post(URL, {"action": "update", "pk": item.pk, f"img{item.pk}-alt_text": "Renamed",
                               f"img{item.pk}-sort_order": 0})
        item.refresh_from_db()
        self.assertEqual((item.alt_text, item.image.name), ("Renamed", name))

    def test_remove_image_deletes_file_and_brings_samples_back(self):
        item = hero.add_image(self.owner, 3, image_file(), "Mine")
        path = item.image.path
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(URL, {"action": "remove", "pk": item.pk})
        self.assertRedirects(response, URL)
        self.assertFalse(HomeHeroImage.objects.exists())
        self.assertFalse(os.path.exists(path))
        self.assertTrue(hero.build_hero()["cards"][2]["is_sample"])

    def test_background_upload_replace_and_remove(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(URL, {"action": "background", "focus": "center top",
                                   "image": image_file("bg.jpg", "JPEG", (1920, 1080))})
        config = HomeHeroSettings.load()
        first = config.background.path
        self.assertEqual(config.background_focus, "center top")
        self.assertEqual(config.updated_by, self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(URL, {"action": "background", "focus": "center",
                                   "image": image_file("bg2.png", size=(1600, 900))})
        config.refresh_from_db()
        self.assertFalse(os.path.exists(first))
        second = config.background.path
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(URL, {"action": "remove_background"})
        self.assertRedirects(response, URL)
        config.refresh_from_db()
        self.assertFalse(config.background)
        self.assertFalse(os.path.exists(second))
        self.assertTrue(hero.build_hero()["background_is_sample"])

    def test_background_rejects_invalid_file(self):
        response = self.client.post(URL, {"action": "background", "focus": "center", "image": image_file("x.gif", "GIF")})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HomeHeroSettings.load().background)

    def test_focus_only_change(self):
        response = self.client.post(URL, {"action": "background", "focus": "right center"})
        self.assertRedirects(response, URL)
        self.assertEqual(HomeHeroSettings.load().background_focus, "right center")
        self.assertEqual(self.client.post(URL, {"action": "background", "focus": "evil"}).status_code, 400)

    def test_position_order(self):
        a = hero.add_image(self.owner, 1, image_file(), "A")
        b = hero.add_image(self.owner, 1, image_file(), "B")
        hero.update_image(b, "B", 0)
        hero.update_image(a, "A", 9)
        self.assertEqual([i["alt"] for i in hero.build_hero()["cards"][0]["images"]], ["B", "A"])

import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.images import process_image
from apps.catalog.models import Product

from .helpers import CatalogTestCase, image_file


class ProcessImageTests(CatalogTestCase):
    def test_accepts_jpeg_png_webp(self):
        for name, fmt in (("a.jpg", "JPEG"), ("b.png", "PNG"), ("c.webp", "WEBP")):
            with self.subTest(fmt=fmt):
                clean = process_image(image_file(name, fmt))
                with Image.open(clean) as img:
                    self.assertEqual(img.format, fmt)

    def test_large_images_are_resized(self):
        clean = process_image(image_file("big.png", size=(4000, 3000)))
        with Image.open(clean) as img:
            self.assertEqual(max(img.size), 1600)

    def test_metadata_is_stripped(self):
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[0x010E] = "secret description"  # ImageDescription
        Image.new("RGB", (100, 100)).save(buf, "JPEG", exif=exif)
        clean = process_image(SimpleUploadedFile("e.jpg", buf.getvalue(), content_type="image/jpeg"))
        with Image.open(clean) as img:
            self.assertNotIn(0x010E, img.getexif())

    def test_rejects_non_images_and_other_formats(self):
        bad = {
            "script renamed .jpg": SimpleUploadedFile("evil.jpg", b"<?php echo 'hi'; ?>", content_type="image/jpeg"),
            "svg": SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", content_type="image/svg+xml"),
            "gif": image_file("anim.gif", "GIF"),
            "png named .exe": SimpleUploadedFile("a.exe", image_file().read(), content_type="image/png"),
            "truncated png": SimpleUploadedFile("t.png", image_file().read()[:200], content_type="image/png"),
        }
        for label, upload in bad.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                process_image(upload)

    @override_settings(CATALOG_IMAGE_MAX_BYTES=1024)
    def test_rejects_oversized_files(self):
        with self.assertRaises(ValidationError) as ctx:
            process_image(image_file(size=(600, 600), color=None))
        self.assertIn("too large", str(ctx.exception))

    def test_rejects_decompression_bombs(self):
        buf = io.BytesIO()
        Image.new("1", (9000, 9000)).save(buf, "PNG")  # 81 MP, tiny file
        with self.assertRaises(ValidationError):
            process_image(SimpleUploadedFile("bomb.png", buf.getvalue(), content_type="image/png"))


class UploadThroughFormTests(CatalogTestCase):
    def test_invalid_upload_shows_error_and_saves_nothing(self):
        self.client.force_login(self.owner)
        fake = SimpleUploadedFile("tea.jpg", b"not really an image", content_type="image/jpeg")
        r = self.client.post(reverse("catalog:product_create"), {"name": "Tea", "category": self.leo_tea.pk, "status": "DRAFT", "image": fake})
        self.assertEqual(r.status_code, 200)
        self.assertIn("image", r.context["form"].errors)
        self.assertFalse(Product.objects.exists())

    def test_stored_under_random_name(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("catalog:product_create"),
                         {"name": "Tea", "category": self.leo_tea.pk, "status": "DRAFT", "image": image_file("../../etc/passwd.png")})
        name = Product.objects.get().image.name
        self.assertRegex(name, r"^catalog/products/\d{4}/\d{2}/[0-9a-f]{32}\.png$")

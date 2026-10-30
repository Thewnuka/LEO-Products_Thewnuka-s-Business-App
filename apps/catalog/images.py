"""
Safe image uploads for categories, products and variations.

Every upload is:
  1. limited in size (CATALOG_IMAGE_MAX_BYTES) and pixel count;
  2. opened and fully decoded with Pillow, so only real JPEG, PNG or WebP
     images are accepted (renamed scripts, SVG, GIF and so on are rejected);
  3. re-encoded: rotated upright, shrunk to at most CATALOG_IMAGE_MAX_SIDE
     pixels and saved again, which strips hidden metadata (e.g. GPS
     location) and anything appended to the file;
  4. stored under a random file name in media/catalog/<kind>/<yyyy>/<mm>/.

Replaced or removed images are deleted from disk after the database change
is committed (ImageFileCleanupMixin).
"""
import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_PIXELS = 40_000_000  # refuse "decompression bombs" (huge dimensions, tiny file)


def _upload_path(kind, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ALLOWED_EXTENSIONS:
        ext = "jpg"
    return f"catalog/{kind}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


def category_image_path(instance, filename):
    return _upload_path("categories", filename)


def product_image_path(instance, filename):
    return _upload_path("products", filename)


def variation_image_path(instance, filename):
    return _upload_path("variations", filename)


def process_image(upload):
    """Validate an uploaded image and return a clean, re-encoded copy. Raises ValidationError."""
    max_bytes = settings.CATALOG_IMAGE_MAX_BYTES
    if upload.size > max_bytes:
        raise ValidationError(f"The image is too large. The maximum size is {max_bytes // (1024 * 1024)} MB.")
    ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError("Upload a JPG, PNG or WebP image.")

    try:
        upload.seek(0)
        with Image.open(upload) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise ValidationError("Upload a JPG, PNG or WebP image.")
            if width * height > MAX_PIXELS:
                raise ValidationError("The image dimensions are too large.")
            probe.verify()  # detects truncated or corrupted files
        upload.seek(0)
        with Image.open(upload) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            max_side = settings.CATALOG_IMAGE_MAX_SIDE
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            if fmt == "JPEG":
                img.convert("RGB").save(out, "JPEG", quality=85, optimize=True, progressive=True)
            elif fmt == "PNG":
                if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    img = img.convert("RGBA")
                img.save(out, "PNG", optimize=True)
            else:
                img.save(out, "WEBP", quality=85)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("This file is not a valid image, or it is damaged.")

    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
    return SimpleUploadedFile(f"image.{ALLOWED_FORMATS[fmt]}", out.getvalue(), content_type=content_type)


class ImageFileCleanupMixin:
    """Deletes an old image file from storage once a replacement/removal is saved."""

    image_fields = ()

    def save(self, *args, **kwargs):
        old_files = []
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(*self.image_fields).first() or {}
            for field in self.image_fields:
                old_name = previous.get(field)
                new_name = getattr(self, field).name if getattr(self, field) else ""
                if old_name and old_name != new_name:
                    old_files.append((getattr(self, field).storage, old_name))
        super().save(*args, **kwargs)
        for storage, name in old_files:
            transaction.on_commit(lambda s=storage, n=name: s.delete(n))

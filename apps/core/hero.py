"""
Home page hero: background photo and three slanted image cards.

Images are managed in the staff portal (Administration → Home page images, Owner only)
and stored in Django media storage (media/hero/...). Until images are uploaded, the
built-in samples below are shown; removing every uploaded image of a card (or the
uploaded background) brings its samples back.

Behaviour settings (not images) live here: the order in which the cards change and
the time between changes.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.templatetags.static import static

from apps.catalog.images import process_image

from .models import HomeHeroImage, HomeHeroSettings

# One card changes at a time, in this order (box numbers), then the order repeats.
CHANGE_ORDER = [1, 3, 2]
INTERVAL_SECONDS = 3.5
MAX_IMAGES_PER_BOX = 8

# Built-in sample images (static/images/hero/), used until the Owner uploads their own.
SAMPLE_BACKGROUND = "images/hero/hero-bg.jpg"
SAMPLE_IMAGES = {
    1: [("images/hero/box1-1.jpg", "Freshly picked tea leaves in a woven basket"),
        ("images/hero/box1-2.jpg", "Loose tea leaves in a clay pot with a wooden spoon"),
        ("images/hero/box1-3.jpg", "A young tea shoot growing in a tea garden")],
    2: [("images/hero/box2-1.jpg", "A cup of spiced milk tea with ginger and biscuits"),
        ("images/hero/box2-2.jpg", "A glass of tea with lemon, ginger and honey")],
    3: [("images/hero/box3-1.jpg", "Plates of traditional Sri Lankan sweets"),
        ("images/hero/box3-2.jpg", "Kokis, kavum and other sweets in a woven basket beside an oil lamp"),
        ("images/hero/box3-3.jpg", "Golden kokis on a white plate")],
}


class HeroImageError(ValidationError):
    pass


def build_hero():
    """Everything the home page needs, with uploaded images first and samples as fallback."""
    config = HomeHeroSettings.load()
    uploaded = {}
    for item in HomeHeroImage.objects.all():
        uploaded.setdefault(item.box, []).append({"src": item.image.url, "alt": item.alt_text})
    cards = []
    for box in HomeHeroImage.Box:
        images = uploaded.get(box.value) or [{"src": static(p), "alt": alt} for p, alt in SAMPLE_IMAGES[box.value]]
        cards.append({"box": box.value, "images": images, "is_sample": not uploaded.get(box.value)})
    return {
        "background": config.background.url if config.background else static(SAMPLE_BACKGROUND),
        "background_focus": config.background_focus,
        "background_is_sample": not config.background,
        "cards": cards,
        "order": ",".join(str(n - 1) for n in CHANGE_ORDER),
        "interval_ms": int(INTERVAL_SECONDS * 1000),
    }


def _delete_file_later(field_file):
    if field_file:
        storage, name = field_file.storage, field_file.name
        transaction.on_commit(lambda: storage.delete(name))


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------
@transaction.atomic
def save_background(user, upload=None, focus=None):
    config = HomeHeroSettings.objects.select_for_update().get_or_create(pk=1)[0]
    if upload is not None:
        clean = process_image(upload)
        _delete_file_later(config.background)
        config.background.save(clean.name, clean, save=False)
    if focus:
        config.background_focus = focus
    config.updated_by = user
    config.save()
    return config


@transaction.atomic
def remove_background(user):
    config = HomeHeroSettings.objects.select_for_update().get_or_create(pk=1)[0]
    _delete_file_later(config.background)
    config.background = ""
    config.updated_by = user
    config.save()
    return config


# ---------------------------------------------------------------------------
# Card images
# ---------------------------------------------------------------------------
@transaction.atomic
def add_image(user, box, upload, alt_text):
    if box not in HomeHeroImage.Box.values:
        raise HeroImageError("Choose Box 1, 2 or 3.")
    if HomeHeroImage.objects.filter(box=box).count() >= MAX_IMAGES_PER_BOX:
        raise HeroImageError(f"A box can hold up to {MAX_IMAGES_PER_BOX} images. Remove one first.")
    clean = process_image(upload)
    last = HomeHeroImage.objects.filter(box=box).order_by("-sort_order").values_list("sort_order", flat=True).first()
    item = HomeHeroImage(box=box, alt_text=alt_text.strip(), sort_order=(last or 0) + 1, created_by=user)
    item.image.save(clean.name, clean, save=False)
    item.save()
    return item


@transaction.atomic
def update_image(item, alt_text, sort_order, upload=None):
    item = HomeHeroImage.objects.select_for_update().get(pk=item.pk)
    if upload is not None:
        clean = process_image(upload)
        _delete_file_later(item.image)
        item.image.save(clean.name, clean, save=False)
    item.alt_text = alt_text.strip()
    item.sort_order = sort_order
    item.save()
    return item


@transaction.atomic
def remove_image(item):
    _delete_file_later(item.image)
    item.delete()

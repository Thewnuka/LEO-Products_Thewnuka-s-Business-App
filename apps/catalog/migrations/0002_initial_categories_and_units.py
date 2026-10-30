"""
Starting data: the initial LEO PRODUCTS categories and measurement units.

This is seed data only. Everything created here can be renamed, extended or
deactivated afterwards from Staff portal → Catalogue; the application code
does not depend on these names. Safe to run on a database that already has
some of these rows (get_or_create).
"""
from django.db import migrations
from django.utils.text import slugify

CATEGORIES = [
    ("LEO TEA", ["Black Tea", "Ginger Tea", "Cinnamon Tea"]),
    ("TEA BAGS", ["Black Tea Bags", "Ginger Tea Bags", "Cinnamon Tea Bags"]),
    ("LEO SWEETS", ["Kokis"]),
]

# (measurement type, name, symbol, attach symbol to number, sort order)
UNITS = [
    ("WEIGHT", "Gram", "g", True, 1),
    ("WEIGHT", "Kilogram", "kg", True, 2),
    ("COUNT", "Tea bag", "bags", False, 1),
    ("PIECE", "Piece", "pieces", False, 1),
]


def unique_slug(Category, text):
    base, n = slugify(text), 2
    slug = base
    while Category.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def seed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Unit = apps.get_model("catalog", "Unit")

    for main_order, (main_name, subs) in enumerate(CATEGORIES, start=1):
        main = Category.objects.filter(parent__isnull=True, name__iexact=main_name).first()
        if main is None:
            main = Category.objects.create(name=main_name, slug=unique_slug(Category, main_name), sort_order=main_order)
        for sub_order, sub_name in enumerate(subs, start=1):
            if not Category.objects.filter(parent=main, name__iexact=sub_name).exists():
                Category.objects.create(
                    parent=main, name=sub_name, sort_order=sub_order,
                    slug=unique_slug(Category, f"{main_name}-{sub_name}"),
                )

    for measurement_type, name, symbol, attach, order in UNITS:
        if not Unit.objects.filter(measurement_type=measurement_type, symbol__iexact=symbol).exists():
            Unit.objects.create(measurement_type=measurement_type, name=name, symbol=symbol,
                                attach_symbol=attach, sort_order=order)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_catalog_models")]

    # Reversing leaves the data in place: it may already be in use.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

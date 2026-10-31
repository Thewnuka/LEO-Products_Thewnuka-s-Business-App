"""
Phase 11: the customer store's category structure.

    LEO TEA                      (main category)
      ├─ Tea Bags                (subcategory)  products: Black, Ginger, Cinnamon ...
      └─ Tea Packets             (subcategory)  products: Black, Ginger, Cinnamon ...
    LEO SWEETS                   (main category, kept separate; its subcategories are untouched)

Before this, TEA BAGS was its own main category (with Black/Ginger/Cinnamon Tea Bags
subcategories) and LEO TEA had Black/Ginger/Cinnamon Tea subcategories.

Nothing is lost or duplicated:
  - products keep their ids, names, slugs, SKUs, variations, stock and order history;
    only their category/subcategory links change:
      * products in TEA BAGS (or its subcategories)          -> LEO TEA › Tea Bags
      * products in LEO TEA's flavour subcategories / none    -> LEO TEA › Tea Packets,
        or LEO TEA › Tea Bags when the product is sold by the bag (a "COUNT" variation)
  - inventory items that pointed at a moved category point at its new place;
  - an old category is deleted only when nothing refers to it any more, otherwise it is
    deactivated (hidden from customers and from new products) so its history stays intact.
LEO SWEETS products are never touched. Safe to run more than once.
"""
from django.db import migrations
from django.utils.text import slugify

TEA = "LEO TEA"
SWEETS = "LEO SWEETS"
OLD_BAGS_MAIN = "TEA BAGS"
BAGS, PACKETS = "Tea Bags", "Tea Packets"


def unique_slug(Category, text):
    base, n = slugify(text), 2
    slug = base
    while Category.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def main(Category, name, order):
    cat = Category.objects.filter(parent__isnull=True, name__iexact=name).first()
    if cat is None:
        cat = Category.objects.create(name=name, slug=unique_slug(Category, name), sort_order=order)
    return cat


def sub(Category, parent, name, order):
    cat = Category.objects.filter(parent=parent, name__iexact=name).first()
    if cat is None:
        cat = Category.objects.create(parent=parent, name=name, sort_order=order,
                                      slug=unique_slug(Category, f"{parent.name}-{name}"))
    return cat


def sold_by_the_bag(product):
    return product.variations.filter(measurement_type="COUNT").exists()


def retire(Category, InventoryItem, Product, category):
    """Delete an emptied category, or deactivate it if anything still refers to it."""
    in_use = (Product.objects.filter(category=category).exists() or Product.objects.filter(subcategory=category).exists()
              or InventoryItem.objects.filter(category=category).exists()
              or Category.objects.filter(parent=category).exists())
    if in_use:
        Category.objects.filter(pk=category.pk).update(is_active=False)
    else:
        category.delete()


def restructure(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")
    InventoryItem = apps.get_model("inventory", "InventoryItem")

    tea = main(Category, TEA, 1)
    Category.objects.filter(pk=tea.pk).update(sort_order=1, is_active=True)
    sweets = main(Category, SWEETS, 2)
    Category.objects.filter(pk=sweets.pk).update(sort_order=2)
    bags = sub(Category, tea, BAGS, 1)
    packets = sub(Category, tea, PACKETS, 2)
    Category.objects.filter(pk__in=[bags.pk, packets.pk]).update(is_active=True)
    keep = {bags.pk, packets.pk}

    # 1. TEA BAGS main category (and its subcategories) -> LEO TEA › Tea Bags
    old_bags = Category.objects.filter(parent__isnull=True, name__iexact=OLD_BAGS_MAIN).first()
    if old_bags is not None:
        old_ids = [old_bags.pk, *Category.objects.filter(parent=old_bags).values_list("pk", flat=True)]
        Product.objects.filter(category_id__in=old_ids).update(category=tea, subcategory=bags)
        InventoryItem.objects.filter(category_id__in=old_ids).update(category=bags)
        for old in Category.objects.filter(parent=old_bags):
            retire(Category, InventoryItem, Product, old)
        retire(Category, InventoryItem, Product, old_bags)

    # 2. LEO TEA products outside the two new subcategories -> Tea Packets (or Tea Bags if sold by the bag)
    for product in Product.objects.filter(category=tea).exclude(subcategory_id__in=keep):
        product.subcategory = bags if sold_by_the_bag(product) else packets
        product.save(update_fields=["subcategory"])

    # 3. LEO TEA's old flavour subcategories (Black Tea, Ginger Tea, ...) are now empty of products
    for old in Category.objects.filter(parent=tea).exclude(pk__in=keep):
        InventoryItem.objects.filter(category=old).update(category=packets)
        retire(Category, InventoryItem, Product, old)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_unit_base_quantity"),
        ("inventory", "0001_inventory_models"),
    ]

    # Reversing leaves the new structure in place (products may have been added to it since).
    operations = [migrations.RunPython(restructure, migrations.RunPython.noop)]

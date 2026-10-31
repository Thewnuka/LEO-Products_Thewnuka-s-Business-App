from django.db import migrations

CATEGORIES = [
    ("Transport & delivery", "Fuel, vehicle hire, couriers, delivery costs"),
    ("Utilities", "Electricity, water, gas"),
    ("Rent", "Shop, store or factory rent"),
    ("Salaries & wages", "Staff pay and allowances"),
    ("Telephone & internet", ""),
    ("Marketing & advertising", ""),
    ("Repairs & maintenance", "Equipment, vehicles, premises"),
    ("Bank & payment charges", "Bank fees, payment gateway fees"),
    ("Office & stationery", ""),
    ("Other", "Anything that doesn't fit another category"),
]


def seed(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    for name, description in CATEGORIES:
        ExpenseCategory.objects.get_or_create(name=name, defaults={"description": description})


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

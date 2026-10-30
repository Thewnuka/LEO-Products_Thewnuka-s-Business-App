from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.shop.models import Cart


class Command(BaseCommand):
    help = "Delete guest carts not changed for N days (default 30). Customer carts are never touched."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, days, **options):
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = Cart.objects.filter(user__isnull=True, updated_at__lt=cutoff).delete()
        self.stdout.write(f"Deleted {deleted} guest cart record(s) older than {days} days.")

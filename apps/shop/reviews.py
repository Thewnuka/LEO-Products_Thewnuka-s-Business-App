"""
Wishlist and product reviews (Phase 09).

Only customers who actually bought a product (a paid, not cancelled order containing
one of its sizes) can review it, so reviews can't be invented. Reviews are checked by
a Manager/Owner before they are shown, unless the Owner turns approval off.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.utils import timezone

from apps.accounts.roles import Role
from apps.notifications import events
from apps.notifications.models import AlertSettings
from apps.orders.models import Order, OrderItem

from .models import ProductReview, WishlistItem


class ReviewError(ValidationError):
    pass


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
def is_wishlisted(user, product):
    return bool(user.is_authenticated and WishlistItem.objects.filter(user=user, product=product).exists())


def toggle_wishlist(user, product):
    """Add or remove; returns True if the product is now on the wishlist."""
    deleted, _ = WishlistItem.objects.filter(user=user, product=product).delete()
    if deleted:
        return False
    try:
        with transaction.atomic():
            WishlistItem.objects.create(user=user, product=product)
    except IntegrityError:  # added by a simultaneous request
        pass
    return True


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
def has_bought(user, product):
    if not (user.is_authenticated and user.role == Role.CUSTOMER):
        return False
    return OrderItem.objects.filter(order__customer=user, order__payment_status=Order.PaymentStatus.PAID,
                                    variation__product=product).exclude(order__status=Order.Status.CANCELLED).exists()


def rating_summary(product):
    data = product.reviews.filter(status=ProductReview.Status.APPROVED).aggregate(avg=Avg("rating"), count=Count("pk"))
    return {"average": round(data["avg"], 1) if data["avg"] else None, "count": data["count"]}


@transaction.atomic
def save_review(user, product, rating, title, body):
    if not has_bought(user, product):
        raise ReviewError("You can review products you have bought and paid for.")
    if not 1 <= int(rating) <= 5:
        raise ReviewError("Choose a rating from 1 to 5 stars.")
    status = ProductReview.Status.PENDING if AlertSettings.load().reviews_need_approval else ProductReview.Status.APPROVED
    title, body = title.strip(), body.strip()
    review, created = ProductReview.objects.select_for_update().get_or_create(
        product=product, customer=user,
        defaults={"rating": rating, "title": title, "body": body, "status": status, "submitted_at": timezone.now()})
    if not created:  # an edit is checked again, like a new review
        review.rating, review.title, review.body, review.status = rating, title, body, status
        review.submitted_at = timezone.now()
        review.moderated_by, review.moderated_at, review.moderation_note = None, None, ""
        review.save()
    if review.status == ProductReview.Status.PENDING:
        events.review_submitted(review)
    return review


@transaction.atomic
def moderate_review(review, staff, approve, note=""):
    new = ProductReview.Status.APPROVED if approve else ProductReview.Status.REJECTED
    if not approve and not note.strip():
        raise ReviewError("Please give the customer a short reason.")
    done = ProductReview.objects.filter(pk=review.pk).exclude(status=new).update(
        status=new, moderated_by=staff, moderated_at=timezone.now(), moderation_note=note.strip()[:300],
        updated_at=timezone.now())
    if not done:
        raise ReviewError(f"This review is already {review.get_status_display().lower()}.")
    review.refresh_from_db()
    events.review_moderated(review)
    return review

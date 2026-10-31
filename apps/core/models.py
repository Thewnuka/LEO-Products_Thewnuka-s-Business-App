from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base for business models.

    Inherit from this in future apps to get created_at / updated_at
    automatically. Being abstract, it creates no database table itself.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# Home page hero images (managed by the Owner: Staff portal → Home page images)
# ---------------------------------------------------------------------------
def hero_image_path(instance, filename):
    """Random file names under media/hero/<yyyy>/<mm>/ (the extension is set by the image processing)."""
    import uuid

    from django.utils import timezone

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"hero/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class HomeHeroSettings(TimeStampedModel):
    """Single row (pk=1): the hero background. Empty = the built-in sample background is used."""

    class Focus(models.TextChoices):
        CENTER = "center", "Centre"
        LEFT = "left center", "Left"
        RIGHT = "right center", "Right"
        TOP = "center top", "Top"
        BOTTOM = "center bottom", "Bottom"

    background = models.ImageField(upload_to=hero_image_path, blank=True)
    background_focus = models.CharField("keep this part of the photo in view", max_length=20,
                                        choices=Focus.choices, default=Focus.CENTER)
    updated_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = verbose_name_plural = "home page hero settings"

    def __str__(self):
        return "Home page hero"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class HomeHeroImage(TimeStampedModel):
    """One image in one of the three hero cards. A card with no images shows the built-in samples."""

    class Box(models.IntegerChoices):
        BOX_1 = 1, "Box 1 (left)"
        BOX_2 = 2, "Box 2 (middle)"
        BOX_3 = 3, "Box 3 (right)"

    box = models.PositiveSmallIntegerField(choices=Box.choices, db_index=True)
    image = models.ImageField(upload_to=hero_image_path)
    alt_text = models.CharField("description", max_length=150,
                                help_text="What the photo shows (read aloud by screen readers).")
    sort_order = models.PositiveIntegerField("position", default=0)
    created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(TimeStampedModel.Meta):
        ordering = ["box", "sort_order", "pk"]

    def __str__(self):
        return f"{self.get_box_display()}: {self.alt_text}"

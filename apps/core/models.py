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

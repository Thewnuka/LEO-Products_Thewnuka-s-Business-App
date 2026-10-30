"""
Private file storage for payment evidence.

Files are kept in PRIVATE_MEDIA_ROOT, which is NOT served by Django or the web
server. They can only be opened through payments.views.evidence, which checks
that the visitor is the order's customer or authorised staff.
"""
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils import timezone
from django.utils.functional import LazyObject, empty


class _PrivateStorage(LazyObject):
    def _setup(self):
        # base_url=None: these files have no public URL.
        self._wrapped = FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


private_storage = _PrivateStorage()


@receiver(setting_changed)
def _reset_private_storage(*, setting, **kwargs):
    # Tests point PRIVATE_MEDIA_ROOT at a temporary folder.
    if setting == "PRIVATE_MEDIA_ROOT":
        private_storage._wrapped = empty


def evidence_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"payment-evidence/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"

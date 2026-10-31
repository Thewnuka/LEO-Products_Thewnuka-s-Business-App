"""
Project-specific deployment checks, shown by `python manage.py check --deploy`
(together with Django's own security checks).
"""
from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


def _inside(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


@register(Tags.security, deploy=True)
def leo_deploy_checks(app_configs, **kwargs):
    issues = []
    if settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
        issues.append(Warning("The database is SQLite.", hint="Use PostgreSQL in production (DATABASE_URL=postgres://...).",
                              id="leo.W001"))
    if settings.ADMIN_URL == "admin/":
        issues.append(Warning("The Django admin is at the default /admin/ address.",
                              hint="Set ADMIN_URL to something less obvious, e.g. ADMIN_URL=leo-office-7381/.", id="leo.W002"))
    if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        issues.append(Warning("Emails are only printed to the console (order emails and password resets won't arrive).",
                              hint="Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend and the EMAIL_* settings.",
                              id="leo.W003"))
    if getattr(settings, "PAYMENT_GATEWAY", "") == "payhere" and getattr(settings, "PAYHERE_SANDBOX", True):
        issues.append(Warning("PayHere is in sandbox mode: real customers can't pay online.",
                              hint="Set PAYHERE_SANDBOX=False with live credentials after testing.", id="leo.W004"))
    for name in ("MEDIA_ROOT", "STATIC_ROOT"):
        root = getattr(settings, name, None)
        if root and _inside(settings.PRIVATE_MEDIA_ROOT, root):
            issues.append(Error(f"PRIVATE_MEDIA_ROOT is inside {name}, so payment slips could be downloaded by anyone.",
                                hint="Keep PRIVATE_MEDIA_ROOT in a separate folder that the web server never serves.",
                                id="leo.E001"))
    return issues

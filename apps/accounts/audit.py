from .models import AccountAuditLog


def client_ip(request):
    # REMOTE_ADDR only: X-Forwarded-For can be forged by the client unless a
    # trusted proxy is configured (a deployment-phase decision).
    return request.META.get("REMOTE_ADDR") if request else None


def record(action, *, actor=None, target=None, request=None, **details):
    """Write an audit entry. Never pass passwords or tokens in `details`."""
    return AccountAuditLog.objects.create(
        action=action,
        actor=actor if actor is not None and actor.is_authenticated else None,
        target=target,
        details=details,
        ip_address=client_ip(request),
    )

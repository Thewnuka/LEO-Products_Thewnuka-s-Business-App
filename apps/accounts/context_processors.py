from .roles import ROLE_CAPABILITIES, Capability

_CAPABILITY_NAMES = {name: value for name, value in vars(Capability).items() if name.isupper()}


def access(request):
    """
    Exposes the signed-in user's capabilities to templates, e.g.
        {% if can.MANAGE_STAFF %} ... {% endif %}
    Only for showing or hiding links. Views enforce the real checks.
    """
    user = getattr(request, "user", None)
    granted = ()
    if user is not None and user.is_authenticated and user.is_active:
        granted = ROLE_CAPABILITIES.get(user.role, ())
    return {"can": {name: value in granted for name, value in _CAPABILITY_NAMES.items()}}

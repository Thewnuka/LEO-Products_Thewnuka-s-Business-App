from django.shortcuts import render
from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = "core/home.html"


class StyleGuideView(TemplateView):
    """Development-only preview of the shared UI components."""

    template_name = "core/style_guide.html"


# ---------------------------------------------------------------------------
# Error handlers (wired up in config/urls.py). They only take effect when
# DEBUG is False; with DEBUG on, Django shows its detailed debug pages.
# ---------------------------------------------------------------------------
def bad_request(request, exception=None):
    return render(request, "400.html", status=400)


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    # Rendered with request context so the brand header still appears.
    # 500.html also has safe fallbacks in case that context is unavailable.
    return render(request, "500.html", status=500)

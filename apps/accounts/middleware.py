from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """
    Users flagged with must_change_password (new staff, the bootstrapped
    owner, or after an admin password reset) can only reach the change-
    password page and log out until they pick a new password.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.must_change_password:
            change_url = reverse("accounts:password_change")
            allowed = (
                change_url,
                reverse("accounts:logout"),
                "/" + settings.STATIC_URL.lstrip("/"),
                "/" + settings.MEDIA_URL.lstrip("/"),
            )
            if not request.path.startswith(allowed):
                if request.path.startswith("/api/"):
                    return JsonResponse({"detail": "You must change your password first."}, status=403)
                messages.warning(request, "Please choose a new password before continuing.")
                return redirect(change_url)
        return self.get_response(request)

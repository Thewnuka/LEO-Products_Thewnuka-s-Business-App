from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from apps.accounts.permissions import CapabilityRequiredMixin
from apps.accounts.roles import Capability

from . import hero
from .forms import HeroBackgroundForm, HeroImageAddForm, HeroImageEditForm
from .models import HomeHeroImage, HomeHeroSettings


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["hero"] = hero.build_hero()
        return ctx


class HeroImagesView(CapabilityRequiredMixin, TemplateView):
    """
    Owner-only manager for the home page hero: the background photo and the
    images that rotate in Box 1, 2 and 3. Every form on the page posts here
    with an `action`; uploads are validated and re-encoded in hero.py.
    """

    required_capability = Capability.MANAGE_BUSINESS_SETTINGS
    template_name = "core/hero_images.html"

    def get_context_data(self, bound=None, **kwargs):
        # `bound` = (action, pk_or_box, form) of a form that failed, so it is shown with its errors.
        ctx = super().get_context_data(**kwargs)
        config = HomeHeroSettings.load()
        bound_key, bound_form = (bound[:2], bound[2]) if bound else (None, None)

        def pick(key, default):
            return bound_form if bound_key == key else default

        live = hero.build_hero()
        boxes = []
        for box, card in zip(HomeHeroImage.Box, live["cards"]):
            items = [
                {"item": item, "form": pick(("update", item.pk), HeroImageEditForm(
                    initial={"alt_text": item.alt_text, "sort_order": item.sort_order}, prefix=f"img{item.pk}"))}
                for item in HomeHeroImage.objects.filter(box=box)
            ]
            boxes.append({
                "number": box.value, "label": box.label, "items": items, "card": card,
                "full": len(items) >= hero.MAX_IMAGES_PER_BOX,
                "add_form": pick(("add", box.value), HeroImageAddForm(initial={"box": box.value}, prefix=f"box{box.value}")),
            })
        ctx.update({
            "config": config, "live": live, "boxes": boxes,
            "background_form": pick(("background", None), HeroBackgroundForm(initial={"focus": config.background_focus})),
            "max_per_box": hero.MAX_IMAGES_PER_BOX,
            "order_label": " → ".join(f"Box {n}" for n in hero.CHANGE_ORDER),
            "interval": hero.INTERVAL_SECONDS,
        })
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        handler = {
            "background": self._background, "remove_background": self._remove_background,
            "add": self._add, "update": self._update, "remove": self._remove,
        }.get(action)
        if handler is None:
            messages.error(request, "Unknown action.")
            return redirect("core:hero_images")
        return handler(request)

    def _redisplay(self, key, form, error=None):
        if error:  # raised while saving (e.g. not a real image), after the form itself was valid
            form.add_error("image", error)
            attrs = form.fields["image"].widget.attrs
            attrs["class"] = f"{attrs.get('class', '')} is-invalid".strip()
            attrs["aria-invalid"] = "true"
        messages.error(self.request, "Please check the highlighted field.")
        return self.render_to_response(self.get_context_data(bound=(*key, form)), status=400)

    def _done(self, text):
        messages.success(self.request, text + " The home page now shows the change.")
        return redirect("core:hero_images")

    def _background(self, request):
        form = HeroBackgroundForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._redisplay(("background", None), form)
        try:
            hero.save_background(request.user, form.cleaned_data["image"], form.cleaned_data["focus"])
        except ValidationError as exc:
            return self._redisplay(("background", None), form, exc)
        return self._done("Background saved." if form.cleaned_data["image"] else "Background position saved.")

    def _remove_background(self, request):
        hero.remove_background(request.user)
        return self._done("Uploaded background removed; the sample background is shown again.")

    def _add(self, request):
        prefix = f"box{request.POST.get('box_number', '')}"
        form = HeroImageAddForm(request.POST, request.FILES, prefix=prefix)
        if not form.is_valid():
            box = form.cleaned_data.get("box") or _int(request.POST.get("box_number"))
            if box not in HomeHeroImage.Box.values:
                messages.error(request, "Choose Box 1, 2 or 3.")
                return redirect("core:hero_images")
            return self._redisplay(("add", box), form)
        box = form.cleaned_data["box"]
        try:
            hero.add_image(request.user, box, form.cleaned_data["image"], form.cleaned_data["alt_text"])
        except ValidationError as exc:
            return self._redisplay(("add", box), form, exc)
        return self._done(f"Image added to Box {box}.")

    def _update(self, request):
        item = get_object_or_404(HomeHeroImage, pk=_int(request.POST.get("pk")))
        form = HeroImageEditForm(request.POST, request.FILES, prefix=f"img{item.pk}")
        if not form.is_valid():
            return self._redisplay(("update", item.pk), form)
        try:
            hero.update_image(item, form.cleaned_data["alt_text"], form.cleaned_data["sort_order"],
                              form.cleaned_data["image"])
        except ValidationError as exc:
            return self._redisplay(("update", item.pk), form, exc)
        return self._done(f"Image in Box {item.box} saved.")

    def _remove(self, request):
        item = get_object_or_404(HomeHeroImage, pk=_int(request.POST.get("pk")))
        box = item.box
        hero.remove_image(item)
        if not HomeHeroImage.objects.filter(box=box).exists():
            return self._done(f"Image removed. Box {box} has no uploaded images, so its sample images are shown again.")
        return self._done(f"Image removed from Box {box}.")


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

from django.conf import settings
from django.urls import path

from . import pwa, views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("staff/home-images/", views.HeroImagesView.as_view(), name="hero_images"),
    # Installable app (PWA)
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
]

if settings.DEBUG:
    urlpatterns += [
        path("style-guide/", views.StyleGuideView.as_view(), name="style_guide"),
    ]

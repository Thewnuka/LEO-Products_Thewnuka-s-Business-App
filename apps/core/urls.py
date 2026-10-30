from django.conf import settings
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
]

if settings.DEBUG:
    urlpatterns += [
        path("style-guide/", views.StyleGuideView.as_view(), name="style_guide"),
    ]

from django.urls import path

from .api import MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
]

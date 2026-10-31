from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.NotificationListView.as_view(), name="list"),
    path("notifications/preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("notifications/read-all/", views.MarkReadView.as_view(), name="read_all"),
    path("notifications/<int:pk>/open/", views.OpenNotificationView.as_view(), name="open"),
    path("notifications/<int:pk>/read/", views.MarkReadView.as_view(), name="read"),
    path("staff/alerts/", views.AlertsView.as_view(), name="alerts"),
    path("staff/settings/alerts/", views.AlertSettingsView.as_view(), name="alert_settings"),
]

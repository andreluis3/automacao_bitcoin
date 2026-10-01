from django.urls import path
from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/state/", views.api_state, name="state"),
    path("api/action/", views.api_action, name="action"),
    path("api/download-logs/", views.api_download_logs, name="download_logs"),
]

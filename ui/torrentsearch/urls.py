"""Root URL configuration — delegate everything to the torrents app."""
from django.urls import include, path

urlpatterns = [
    path("", include("torrents.urls")),
]

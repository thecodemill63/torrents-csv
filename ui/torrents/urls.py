from django.urls import path

from . import views

urlpatterns = [
    path("", views.search, name="search"),
    path("download/", views.download, name="download"),
    path("history/", views.history, name="history"),
    path("config/", views.app_config, name="app_config"),
    path("list-tv-folders/", views.list_tv_folders, name="list_tv_folders"),
    path("create-tv-folder/", views.create_tv_folder, name="create_tv_folder"),
]

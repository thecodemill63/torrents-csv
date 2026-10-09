"""Django settings for torrentsearch — a localhost-only read-only UI
over ~/torrents-csv/torrents.db.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TORRENTS_CSV_DIR = Path(os.environ.get("TORRENTS_CSV_DIR", str(Path.home() / "torrents-csv")))
DB_PATH = TORRENTS_CSV_DIR / "torrents.db"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-torrents-csv-local-only-not-exposed-to-network",
)
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.humanize",
    "torrents",
]
MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "torrentsearch.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]
WSGI_APPLICATION = "torrentsearch.wsgi.application"
ASGI_APPLICATION = "torrentsearch.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DB_PATH),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = False
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
    },
}

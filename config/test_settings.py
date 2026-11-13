"""Pruebas locales aisladas de PostgreSQL y de sus credenciales."""
from .settings import *  # noqa: F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
STATICFILES_DIRS = []

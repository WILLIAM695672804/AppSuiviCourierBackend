"""Developpement local. Jamais utilise ailleurs."""

from config.reglages.base import *  # noqa: F403

DEBUG = env("DEBUG")  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Le front de developpement tourne sur un autre port : sans cette ligne, le
# jeton CSRF est refuse et toutes les ecritures echouent en 403.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

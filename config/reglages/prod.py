"""
Production.

Hebergement sur site : RNF-SOUV-01 impose que les donnees ne quittent pas le
perimetre defini par l'institution.
"""

from config.reglages.base import *  # noqa: F403

DEBUG = False

# RNF-SEC-01 : chiffrement des donnees en transit.
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

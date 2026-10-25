"""
Preproduction — recette avec des donnees reelles.

Cet environnement n'est pas la production : il est servi depuis un poste de
travail, derriere un tunnel sortant, et son horizon est la bascule sur site
(ADR 044). Il en porte neanmoins toutes les contraintes de securite, parce
qu'il porte les memes donnees.

Trois ecarts avec `prod.py`, et trois seulement :

 1. **HSTS est court et sans sous-domaines.** Un an et `includeSubDomains`
    sur un nom qui sert aussi a autre chose enfermerait le domaine entier
    pour un environnement temporaire. Une heure suffit a la recette.

 2. **La journalisation part sur la sortie standard.** Django, en
    `DEBUG=False`, n'ecrit les erreurs nulle part sans configuration : le
    gestionnaire `console` par defaut est filtre par `require_debug_true`.
    Une 500 serait donc invisible — dans un environnement dont le but est
    precisement d'observer ce qui casse.

 3. **Aucun envoi de courriel.** `notifications.courriel_actif` reste a
    faux (A51) et le moteur de messagerie ecrit sur la console : une
    recette qui expedierait de vrais courriels a de vrais agents leur
    ferait prendre un essai pour un acte.
"""

from config.reglages.base import *  # noqa: F403

DEBUG = False

# ---------------------------------------------------------------------
#  Durcissement — RNF-SEC-01, identique a la production.
#
#  PIEGE : la terminaison TLS a lieu chez Cloudflare, et `cloudflared`
#  parle en clair a Nginx. Sans `SECURE_PROXY_SSL_HEADER` et sans que Nginx
#  transmette `X-Forwarded-Proto`, Django se croit en HTTP, redirige vers
#  HTTPS, recoit la meme requete en clair, redirige encore — boucle infinie,
#  et le navigateur affiche ERR_TOO_MANY_REDIRECTS sans autre indice.
# ---------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 3_600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# ---------------------------------------------------------------------
#  Sessions
#
#  Huit heures : la journee de travail d'un agent du Port. Au-dela, une
#  session laissee ouverte sur un poste partage du bureau d'ordre est une
#  identite pretee.
# ---------------------------------------------------------------------
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ---------------------------------------------------------------------
#  Journaux
#
#  Format plat, sur la sortie standard : c'est `docker compose logs` qui les
#  collecte, et un fichier dans un conteneur disparait avec lui.
# ---------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "horodate": {
            "format": "{asctime} {levelname:8} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "sortie": {
            "class": "logging.StreamHandler",
            "formatter": "horodate",
        },
    },
    "root": {"handlers": ["sortie"], "level": "INFO"},
    "loggers": {
        # Les 500 passent ici. Sans cette entree, elles n'apparaissent
        # nulle part : c'est le defaut de Django, pas un oubli du projet.
        "django.request": {"handlers": ["sortie"], "level": "ERROR", "propagate": False},
        # Trop bavard des que la recette charge un registre : chaque requete
        # SQL y passerait.
        "django.db.backends": {"level": "WARNING"},
    },
}

# Le courriel n'est pas branche (A51). La console evite qu'un essai parte.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

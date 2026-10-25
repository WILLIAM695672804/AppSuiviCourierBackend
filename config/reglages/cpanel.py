"""
Hebergement mutualise cPanel.

Ces reglages ne sont pas une variante de confort : ils constatent trois
absences que l'hebergement impose, et les rendent explicites plutot que de
laisser l'application echouer a l'usage (ADR 046).

 1. **Aucun processus resident.** Ni ouvrier Celery, ni horloge, ni Redis.
    Les taches differees s'executent donc dans la requete qui les demande,
    et les sept traitements de nuit sont appeles par le « cron job » du
    panneau : `manage.py traitements`.

 2. **Aucun binaire LibreOffice.** La conversion en PDF est impossible. Le
    code le prevoit : la route sert le `.docx` et refuse le PDF avec un
    message explicite, plutot qu'une page blanche (ADR 023).

 3. **Aucune maitrise du serveur frontal.** C'est Apache et Passenger qui
    servent l'application ; le durcissement TLS est celui du panneau, et
    `SECURE_SSL_REDIRECT` doit rester **faux** — la redirection est faite
    par le `.htaccess`, en amont. La laisser vraie ajouterait une seconde
    redirection a la premiere, sans rien garantir de plus.
"""

from pathlib import Path

from config.reglages.base import *  # noqa: F403

DEBUG = False

# ---------------------------------------------------------------------
#  Durcissement
#
#  Apache redirige deja vers HTTPS (.htaccess) et AutoSSL fournit le
#  certificat. Django ne redirige donc pas lui-meme, mais il exige que ses
#  cookies ne voyagent qu'en clair chiffre : c'est la moitie du contrat
#  qui lui revient, et la seule qu'il puisse tenir ici.
# ---------------------------------------------------------------------
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# HSTS est laisse au panneau : l'entete vaut pour tout le domaine, que
# d'autres sites de l'hebergement partagent peut-etre.
SECURE_HSTS_SECONDS = 0

SESSION_COOKIE_AGE = 8 * 60 * 60

# ---------------------------------------------------------------------
#  Les taches differees, sans courtier
#
#  `ALWAYS_EAGER` execute la tache dans le processus appelant, au moment
#  de l'appel. `EAGER_PROPAGATES` la fait echouer bruyamment : sans lui,
#  une exception serait avalee et la requete repondrait « fait » alors que
#  rien ne l'a ete.
# ---------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------
#  Journaux
#
#  Pas de sortie standard a collecter ici : Passenger la jette. Un fichier,
#  hors de la racine web — un journal lisible depuis un navigateur
#  livrerait les chemins, les identifiants d'objets et les traces.
# ---------------------------------------------------------------------
CHEMIN_JOURNAL = env("CHEMIN_JOURNAL", default=str(RACINE / "journaux" / "application.log"))  # noqa: F405

# Le repertoire est cree ici, et non par la procedure d'installation.
# `RotatingFileHandler` ouvre son fichier au CHARGEMENT de la configuration :
# si le repertoire n'existe pas, Django ne demarre pas du tout, et
# l'hebergeur rend une 500 nue — sans journal, precisement parce que c'est
# le journal qui a echoue. Le diagnostic est alors tres couteux.
Path(CHEMIN_JOURNAL).parent.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "horodate": {"format": "{asctime} {levelname:8} {name} — {message}", "style": "{"},
    },
    "handlers": {
        "fichier": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": CHEMIN_JOURNAL,
            # 5 Mo x 5 : au-dela, le quota disque d'un mutualise se remplit
            # sans que personne ne regarde.
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "horodate",
        },
    },
    "root": {"handlers": ["fichier"], "level": "INFO"},
    "loggers": {
        # Sans cette entree, une 500 ne laisse aucune trace : le
        # gestionnaire par defaut de Django est filtre par
        # `require_debug_true`.
        "django.request": {"handlers": ["fichier"], "level": "ERROR", "propagate": False},
        "django.db.backends": {"level": "WARNING"},
    },
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------
#  Les URL
#
#  Passenger monte l'application sur /api et lui transmet le chemin sans
#  ce prefixe. Voir `config/urls_cpanel.py`, qui explique pourquoi il
#  existe.
# ---------------------------------------------------------------------
ROOT_URLCONF = "config.urls_cpanel"

"""
Reglages communs a tous les environnements.

Ce qui distingue ces reglages de ceux d'un projet Django ordinaire tient en
trois points, chacun impose par une decision deja prise :

 1. `AUTH_USER_MODEL` pointe sur `noyau.Utilisateur`, qui est la table
    `utilisateur` du schema existant. Django ne cree pas sa propre table de
    comptes : elle existe deja, avec ses colonnes metier (matricule, poste,
    structure, identifiant d'annuaire).

 2. Les permissions ne passent PAS par `django.contrib.auth`. Le modele
    d'habilitation du projet porte une notion que Django n'a pas — le
    perimetre — et la modeliser deux fois aurait garanti la divergence.
    Voir docs/architecture/002-permissions-hors-django-auth.md.

 3. `APPEND_SLASH = False`. Le front appelle `/api/activites`, sans barre
    finale. Une redirection 301 sur chaque appel casserait les POST.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

RACINE = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(RACINE / ".env")

SECRET_KEY = env("SECRET_KEY", default="developpement-uniquement-ne-pas-utiliser-en-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ---------------------------------------------------------------------
#  Applications
#
#  Une application par pilier du descriptif fonctionnel, plus le noyau.
#  `django.contrib.auth` reste installe pour les sessions et le middleware,
#  mais son systeme de permissions n'est pas utilise.
# ---------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # Uniquement pour la commande `export_openapi_schema` (cible `make api`) :
    # l'API elle-meme n'a pas besoin que `ninja` soit une application installee.
    "ninja",
    # Socle transverse. N'importe aucun pilier.
    "noyau",
    # Piliers. Decommenter au fur et a mesure de leur creation.
    "activite",
    "gouvernance",
    # `courrier` ne cree aucune table : les siennes sont dans le socle depuis le
    # premier jour, et sa migration 0001 se contente d'en declarer l'etat
    # (`SeparateDatabaseAndState`). Il ne declare pas `instance_circuit` :
    # `circuit_etape` est vide, le trajet reel d'un courrier n'a pas ete
    # communique (A24).
    "courrier",
    "performance",
    "exploitation",
    # `dossier` porte le pilier « projets et dossiers » — le perimetre pilote
    # du BRD (§6.1). Il n'a **aucune** table d'evenements : l'historique d'un
    # dossier se lit dans le journal du noyau (ADR 012).
    "dossier",
    # `archivage` depend de `dossier` : un versement porte un dossier clos. La
    # file des dossiers a verser n'est pas une table mais une lecture.
    "archivage",
    # `pilotage` ne stocke aucun agregat : cockpit, statistiques et analyses se
    # recalculent a chaque lecture (ADR 010). Ses deux seules tables portent ce
    # qu'aucun calcul ne deduit — la **cible** d'un indicateur du programme, et
    # la valeur d'une annee **quand elle est rapportee** de l'exterieur.
    "pilotage",
    # `portail` est le seul pilier atteint par des comptes exterieurs a
    # l'institution. Il ne passe pas par `restreindre()` : sa restriction est
    # `deposant = moi`, plus stricte, ecrite dans `portail/lecture.py` (ADR 013).
    "portail",
    # `supervision` mesure ce que le serveur traverse — une table d'agregats
    # horaires alimentee par un middleware, et rien d'autre (ADR 014).
    "supervision",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Le thermometre de la plateforme. En dernier : il mesure ce que les autres
    # middlewares ont laisse passer, c'est-a-dire le temps reellement vu par
    # l'agent. Toute erreur d'ecriture y est avalee — une plateforme qui tombe
    # parce que son thermometre est casse est pire qu'une plateforme sans
    # thermometre. Voir supervision/mesure.py.
    "supervision.mesure.MesureRequetes",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

# ---------------------------------------------------------------------
#  Base de donnees
#
#  PostgreSQL 16 minimum : le schema utilise le partitionnement declaratif,
#  les contraintes d'exclusion GiST, TSVECTOR et GENERATED AS IDENTITY.
# ---------------------------------------------------------------------
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://suivi:suivi@localhost:5432/suivi"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------
#  Identite
#
#  Le compte vit dans la table `utilisateur`. Aucun mot de passe n'y est
#  stocke : l'authentification est deleguee a l'annuaire (RF-ADM-02). En
#  developpement, un backend local permet de travailler sans annuaire.
# ---------------------------------------------------------------------
AUTH_USER_MODEL = "noyau.Utilisateur"
AUTHENTICATION_BACKENDS = ["noyau.identite.authentification.BackendAnnuaire"]

# Le front porte le cookie de session ; aucun jeton en localStorage.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "suivi_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "suivi_csrf"
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Voir l'entete de ce fichier, point 3.
APPEND_SLASH = False

# ---------------------------------------------------------------------
#  Localisation
#
#  RNF-LOC-01 : langue de l'institution, formats de date et d'heure locaux.
#  Douala est en UTC+1, sans heure d'ete.
# ---------------------------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = RACINE / "static"

# ---------------------------------------------------------------------
#  Stockage des pieces
#
#  Les fichiers ne sont jamais en base : le schema le dit explicitement,
#  « une base contenant les binaires devient insauvegardable ».
# ---------------------------------------------------------------------
MEDIA_ROOT = env("MEDIA_ROOT", default=str(RACINE / "media"))
MEDIA_URL = "media/"

# ---------------------------------------------------------------------
#  Les documents produits
#
#  Le PDF est obtenu en convertissant le .docx par LibreOffice sans
#  interface : une source, deux formats, aucune divergence possible entre
#  le Word et le PDF (ADR 023). Le binaire doit etre present sur le serveur
#  applicatif. En son absence, la route sert le .docx et refuse le PDF avec
#  un message explicite plutot qu'une page blanche.
# ---------------------------------------------------------------------
LIBREOFFICE_BINAIRE = env("LIBREOFFICE_BINAIRE", default="soffice")

#: Delai de garde de la conversion, en secondes. Un `soffice` qui ne rend pas
#: la main immobiliserait un ouvrier gunicorn jusqu'au redemarrage.
LIBREOFFICE_DELAI = env.int("LIBREOFFICE_DELAI", default=60)

# ---------------------------------------------------------------------
#  Traitements differes
# ---------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = False

# ---------------------------------------------------------------------
#  Le calendrier des traitements nocturnes.
#
#  L'ordre des heures n'est pas decoratif : les obligations sont engendrees
#  avant que les relances ne cherchent des retards, et les agregats sont
#  calcules en dernier pour refleter ce que les deux precedents ont ecrit.
#
#  Tous entre 1 h et 3 h du matin, heure de Douala : c'est la fenetre ou
#  personne ne saisit, et un agregat calcule pendant qu'on ecrit serait faux
#  d'une ligne sans que rien ne le signale.
# ---------------------------------------------------------------------
CELERY_BEAT_SCHEDULE = {
    "obligations-du-jour": {
        "task": "activite.engendrer_obligations",
        "schedule": crontab(hour=1, minute=0),
    },
    "relances-des-retards": {
        "task": "activite.relancer_les_retards",
        "schedule": crontab(hour=2, minute=0),
    },
    "agregats-des-activites": {
        "task": "activite.recalculer_agregats",
        "schedule": crontab(hour=3, minute=0),
    },
    # Une fois par jour en decembre : la tache se retire elle-meme le reste de
    # l'annee. Une planification annuelle unique n'aurait aucun rattrapage si
    # le service etait arrete ce jour-la.
    "ouverture-de-l-exercice": {
        "task": "activite.ouvrir_exercice_suivant",
        "schedule": crontab(hour=4, minute=0, day_of_month="1-28", month_of_year=12),
    },
    # Gouvernance. Les relances passent avant les agregats : un agregat calcule
    # apres coup compte la relance du jour, l'inverse la manquerait de vingt-
    # quatre heures.
    "relances-des-engagements": {
        "task": "gouvernance.relancer_les_engagements",
        "schedule": crontab(hour=2, minute=30),
    },
    "depots-en-souffrance": {
        "task": "gouvernance.signaler_les_depots",
        "schedule": crontab(hour=2, minute=45),
    },
    "agregats-de-gouvernance": {
        "task": "gouvernance.recalculer_agregats",
        "schedule": crontab(hour=3, minute=30),
    },
}

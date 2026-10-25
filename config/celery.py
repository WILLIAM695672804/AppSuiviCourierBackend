"""
Celery — les traitements que personne ne declenche.

Le pilier « activites » en depend directement : l'avancement attendu bouge
avec le calendrier, pas avec les saisies. Une echeance franchie pendant la
nuit doit se voir au matin, sans qu'aucun agent n'ait rien fait.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.reglages.dev")

app = Celery("suivi")
app.config_from_object("django.conf:settings", namespace="CELERY")

# `related_name` : Celery cherche `tasks.py` par defaut. Tout le depot ecrit en
# francais, y compris les noms de fichiers — le module s'appelle `taches.py`, et
# sans cette ligne aucune tache ne serait jamais decouverte. L'echec est
# silencieux : le worker demarre, et rien ne s'execute.
app.autodiscover_tasks(related_name="taches")

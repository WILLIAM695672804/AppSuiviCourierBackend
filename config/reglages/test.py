"""
Reglages de la suite de tests.

Celery en mode synchrone : une tache appelee dans un test s'execute sur place.
Sans cela, les tests qui verifient l'effet d'un recalcul nocturne ne verifient
rien du tout.
"""

from config.reglages.base import *  # noqa: F403

DEBUG = False
CELERY_TASK_ALWAYS_EAGER = True

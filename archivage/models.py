"""
Point d'entree des modeles du pilier archivage.

Django cherche les modeles dans `models.py` ; ils sont ecrits dans `modeles.py`,
en francais comme le reste. Ce fichier ne fait que les reexporter.
"""

from archivage.modeles import MaillonIntegrite, RegleConservation, Versement

__all__ = [
    "MaillonIntegrite",
    "RegleConservation",
    "Versement",
]

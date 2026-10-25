"""
Point d'entree des modeles du pilier supervision.

Django cherche les modeles dans `models.py` ; ils sont ecrits dans `modeles.py`,
en francais comme le reste. Ce fichier ne fait que les reexporter.
"""

from supervision.modeles import Integration, MesureRequete

__all__ = ["Integration", "MesureRequete"]

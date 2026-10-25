"""
Point d'entree des modeles du pilier courrier.

Django cherche les modeles dans `models.py` ; ils sont ecrits dans `modeles.py`,
en francais comme le reste. Ce fichier ne fait que les reexporter.
"""

from courrier.modeles import (
    Affectation,
    Cotation,
    CotationStructure,
    CotationSuivi,
    Courrier,
    SequenceNumerotation,
    Traitement,
)

__all__ = [
    "Affectation",
    "Cotation",
    "CotationStructure",
    "CotationSuivi",
    "Courrier",
    "SequenceNumerotation",
    "Traitement",
]

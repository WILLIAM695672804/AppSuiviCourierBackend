"""
Lecture des parametres, avec cache.

Une regle relue a chaque ligne d'un registre de deux cents activites, c'est
deux cents requetes pour une valeur qui change deux fois par an. Le cache est
invalide a l'ecriture, jamais expire par duree : une regle modifiee doit
prendre effet tout de suite, sinon deux serveurs appliquent deux seuils.
"""

from collections import OrderedDict
from decimal import Decimal
from typing import Any

from noyau.parametres.modeles import Parametre

TAILLE_CACHE = 512
_cache: OrderedDict[str, Any] = OrderedDict()

#: Les ecritures qu'un parametre booleen accepte. Elles vivent ici, et non dans
#: `services.py` qui valide les saisies : le module de lecture est le seul a
#: savoir ce qu'il sait relire, et deux listes divergentes produiraient une
#: valeur acceptee a l'ecriture et lue comme fausse ensuite.
VRAIS = ("true", "vrai", "1", "oui")
FAUX = ("false", "faux", "0", "non")


def _convertir(parametre: Parametre) -> Any:
    if parametre.type_valeur == "entier":
        return int(parametre.valeur)
    if parametre.type_valeur == "decimal":
        return Decimal(parametre.valeur)
    if parametre.type_valeur == "booleen":
        return parametre.valeur.lower() in VRAIS
    return parametre.valeur


def valeur(cle: str, defaut: Any = None) -> Any:
    """
    La valeur du parametre, convertie selon son type.

    `defaut` sert au demarrage, avant que la table ne soit peuplee. Il ne
    dispense pas de creer la ligne : un parametre absent de la table est un
    parametre que personne ne peut corriger sans redeploiement, ce qui est
    exactement ce que cette table evite.
    """
    if cle in _cache:
        _cache.move_to_end(cle)
        return _cache[cle]

    parametre = Parametre.objects.filter(cle=cle).first()
    if parametre is None:
        return defaut

    _cache[cle] = _convertir(parametre)
    _cache.move_to_end(cle)
    while len(_cache) > TAILLE_CACHE:
        _cache.popitem(last=False)
    return _cache[cle]


def vider_cache() -> None:
    """A appeler apres toute ecriture sur la table, et dans les tests."""
    _cache.clear()

"""
Les sentinelles « tout » des filtres de registre.

Un registre du front ouvre sur « Toutes » ou « Tous » — c'est le libelle du
selecteur, et c'est **ce libelle qui part dans l'URL**. Le serveur, lui,
comparait a `"toutes"` et `"tous"` en minuscules. Aucun des deux n'avait tort
isolement ; ensemble, ils vidaient quatre registres a l'ouverture, sans erreur
ni journal — le filtre cherchait une structure nommee « Toutes ».

Le releve d'ecarts du 15 aout 2026 n'a pas vu ce cas : il comparait les **noms**
des parametres de requete, pas les **valeurs** qui y circulent. C'est la lecon,
et elle vaut au-dela de ce module : deux cotes peuvent s'accorder sur un
vocabulaire et diverger sur une casse.

Ce module tient donc la question en un seul endroit. Un pilier qui ajoute un
filtre appelle `est_tout()` plutot que de reecrire sa propre liste — c'est
exactement en la reecrivant que `gouvernance.lecture` en etait venu a accepter
« Toutes » a un endroit et pas aux trois autres.
"""

#: Ce qui vaut « pas de filtre ». Compare hors casse et hors espaces.
_SENTINELLES = frozenset({"", "tous", "toutes", "tout", "toute"})


def est_tout(valeur: str | None) -> bool:
    """
    Vrai quand la valeur recue ne restreint rien.

    Accepte `None`, la chaine vide, et les quatre accords de « tout », quelle
    que soit la casse. Ne fait **pas** de normalisation d'accents : aucune de
    ces sentinelles n'en porte, et en ajouter une qui en porterait serait une
    mauvaise idee pour la meme raison qu'ici.
    """
    return valeur is None or valeur.strip().lower() in _SENTINELLES

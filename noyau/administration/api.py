"""
Route du tableau de bord d'administration — `/api/administration/*`.

**Une garde large, un contenu filtre.** La route s'ouvre a quiconque porte
l'une des permissions d'administration ou d'audit, parce que l'ecran est
l'accueil de tous ces postes ; mais chaque bloc de la reponse est rempli selon
ce que le compte porte reellement (voir `lecture.tableau_de_bord`). Exiger les
quatre permissions aurait ferme l'accueil au poste d'audit ; n'en exiger
qu'une sans filtrer le contenu aurait livre les acces signales a un
administrateur de l'organigramme.

`restreindre()` n'est pas appele : le tableau de bord d'une institution est par
definition institutionnel — un total reduit au perimetre de son lecteur
n'apprendrait rien a personne. C'est la meme raison qu'en tracabilite, et
comme la, toute la garde repose sur la permission.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.administration import lecture
from noyau.administration.schemas import TableauDeBordAdmin
from noyau.habilitation.dependances import PERM, exige

routeur = Router()


@routeur.get(
    "/tableau-de-bord",
    response=TableauDeBordAdmin,
    auth=exige(PERM.ADM_HAB, PERM.ADM_ORG, PERM.AUDIT, PERM.ADM_TEC),
)
def tableau_de_bord(request, periode: str = "30j"):
    """
    L'usage de l'application, l'etat du referentiel et les acces a examiner.

    `periode` vaut `30j`, `trimestre` ou `annee`. Une valeur inconnue retombe
    sur `30j` plutot que de rendre 422 : le parametre vient d'un selecteur a
    trois positions, et un ecran d'accueil qui refuse de s'afficher pour un
    parametre de confort serait un mauvais echange.
    """
    return lecture.tableau_de_bord(request.auth, periode)

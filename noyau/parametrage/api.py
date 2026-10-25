"""
Routes du parametrage metier — `/api/parametrage`.

**Une seule route de lecture pour neuf onglets.** Les referentiels sont petits
et l'administrateur passe de l'un a l'autre sans arret ; neuf appels auraient
fait clignoter l'ecran a chaque onglet pour economiser quelques kilo-octets.

`ADM_PAR` et rien d'autre : le §3.9 confie le parametrage metier a
l'administrateur fonctionnel. Ce n'est pas `ADM_TEC` — regler un delai
d'escalade est une decision d'organisation, pas d'exploitation.

**Les huit premiers onglets sont en lecture seule ; le neuvieme ne l'est pas.**
Les referentiels de circuit attendent le pilier courrier : les rendre
modifiables avant qu'il ne les consomme aurait produit des circuits que rien
n'emprunte. Les regles de gestion, elles, sont deja lues par le code en
production a travers `noyau.parametres.service.valeur()`, et **la moitie d'entre
elles sont des hypotheses** que le metier doit trancher. Sans ces deux routes,
l'arbitrage du client passe par un `UPDATE` en SQL — c'est-a-dire par le
developpement, sans trace et sans controle.

`restreindre()` n'est pas appele : un referentiel de parametrage n'a pas de
perimetre, les regles de l'institution sont les memes pour tous.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige
from noyau.parametrage import lecture
from noyau.parametrage.schemas import (
    DonneesParametrage,
    RegleMetier,
    SaisieArbitrage,
    SaisieRegleMetier,
)
from noyau.parametres import services

routeur = Router()


@routeur.get("", response=DonneesParametrage, auth=exige(PERM.ADM_PAR))
def parametrage(request):
    """Les neuf referentiels du parametrage metier, dans l'ordre des onglets."""
    return lecture.parametrage()


@routeur.patch("/regles-metier/{cle}", response=RegleMetier, auth=exige(PERM.ADM_PAR))
def modifier_regle(request, cle: str, saisie: SaisieRegleMetier):
    """
    Change la valeur d'une regle sans toucher a son statut — H-07.

    Corriger une hypothese est libre ; changer un acte exige de citer la
    decision qui le change. La difference tient dans `services.modifier_regle`.
    """
    services.modifier_regle(
        request.auth,
        cle,
        valeur=saisie.valeur,
        source=saisie.source,
    )
    return _relire(cle)


@routeur.post("/regles-metier/{cle}/arbitrage", response=RegleMetier, auth=exige(PERM.ADM_PAR))
def trancher_regle(request, cle: str, saisie: SaisieArbitrage):
    """
    Fait passer une hypothese au rang d'acte — H-07.

    C'est **la sortie de docs/questions-ouvertes.md** : chaque appel retire une
    question de la liste, en inscrivant qui a tranche et sur quel document.
    """
    services.trancher_regle(
        request.auth,
        cle,
        source=saisie.source,
        valeur=saisie.valeur,
    )
    return _relire(cle)


def _relire(cle: str) -> dict:
    """
    La regle telle que la lecture la sert, apres ecriture.

    Relire plutot que construire la reponse depuis l'objet ecrit : c'est
    `services.regles()` qui decide de la forme, et deux constructions
    divergentes finiraient par afficher un champ que la liste ne montre pas.
    """
    ligne = next(regle for regle in services.regles() if regle["cle"] == cle)
    return ligne

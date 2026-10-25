"""
Routes de la supervision technique — `/api/supervision*`.

Deux lectures, aucune ecriture, sous `ADM_TEC`. Aucune ecriture parce qu'il n'y
a rien a saisir : ce que ces ecrans montrent, le serveur le mesure de lui-meme
(ADR 014). Une route de declaration d'incident aurait ouvert un second recit,
alimente a la main, a cote de mesures qui n'attendent personne.

`restreindre()` n'apparait pas, et c'est le seul cas du depot ou son absence
n'est pas une derogation : la plateforme n'appartient a aucune structure, et sa
disponibilite ne se decline pas par direction. La reponse de ces deux routes est
la meme pour tous ceux qui ont le droit de les ouvrir.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige
from supervision import lecture
from supervision.schemas import Integrations, Supervision

routeur = Router()


@routeur.get("", response=Supervision, auth=exige(PERM.ADM_TEC))
def plateforme(request):
    """
    Disponibilite et performance, confrontees aux engagements du BRD.

    99,5 % de disponibilite (RNF-DISP-01), 2 secondes au 95e centile
    (RNF-PERF-01), reprise en moins de quatre heures (RNF-DISP-02). L'ecran ne
    se contente pas d'afficher des chiffres : il dit si l'engagement est tenu,
    et il dit ce qu'il ne mesure pas.
    """
    return lecture.plateforme()


@routeur.get("/integrations", response=Integrations, auth=exige(PERM.ADM_TEC))
def integrations(request):
    """
    SSO et systemes tiers — RF-ADM-02.

    Le compte des connexions encore faites par mot de passe applicatif est le
    chiffre a suivre : tant qu'il n'est pas nul, la bascule vers l'annuaire
    n'est pas achevee, quoi que dise l'etat de l'integration.
    """
    return lecture.integrations()

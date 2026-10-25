"""
Routes de lecture large du parametrage metier — `/api/referentiels/*`.

**Pourquoi un second routeur sur `/referentiels`.** L'organigramme y est deja
monte (`noyau.organisation.api`, ADR 007). Natures, mentions et correspondants
ne sont pas de l'organigramme : ils appartiennent au parametrage metier, dont
l'ecriture reste sous `ADM_PAR`. Les fondre dans le routeur de l'organisation
aurait fait mentir sa docstring ; les monter sous `/parametrage` aurait exige
`ADM_PAR` pour enregistrer un courrier. Deux routeurs, un prefixe, deux
domaines.

**`session_seule`, et pourquoi ce n'est pas une extension silencieuse de
l'ADR 007.** Cette derogation-la se justifie par elle-meme : l'agent de session
qui enregistre un courrier doit choisir sa nature, la mention qui l'accompagne et
l'expediteur dans le carnet d'adresses. Aucun de ces trois referentiels ne
nomme de donnee metier — une nature est un mot, une mention est un mot, un
correspondant est une adresse deja imprimee sur l'enveloppe qu'il tient en main.
`restreindre()` n'a rien a filtrer : ces tables n'ont pas de structure
proprietaire.

**Ce que cela ferme.** Jusqu'ici la matiere ne sortait que par `GET /parametrage`,
sous `ADM_PAR`. L'ecran d'enregistrement d'un courrier ne pouvait donc proposer
ni nature, ni mention, ni correspondant a un agent qui n'etait pas
administrateur du parametrage — c'est-a-dire a tous ceux dont c'est le metier.
Les trois routes repondaient 404 depuis le debranchement du serveur de
demonstration (ADR 008).

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige, session_seule
from noyau.parametrage import lecture_referentiel, services
from noyau.parametrage.schemas_referentiel import (
    CorrespondantRef,
    MentionRef,
    NatureRef,
    SaisieCorrespondant,
)

routeur = Router()


@routeur.get("/natures", response=list[NatureRef], auth=session_seule)
def lister_natures(request):
    """
    Les natures de courrier en vigueur, avec le delai qu'elles emportent.

    Le front s'en sert deux fois : pour remplir la liste, et pour **proposer**
    le delai attache a la nature choisie. Proposer et non imposer — l'agent peut
    en retenir un autre, et c'est la cotation qui tranchera.
    """
    return lecture_referentiel.natures()


@routeur.get("/mentions", response=list[MentionRef], auth=session_seule)
def lister_mentions(request):
    """
    Les mentions portees a la cotation — « Pour attribution », « Pour avis »…

    Deux champs seulement : la modale de cotation n'affiche qu'un libelle. Ce que
    chaque mention **declenche** n'est pas rendu ici, parce que personne ne l'a
    encore dit (A25) ; l'ecran de parametrage le montre tel qu'il est administre,
    ce qui est le bon endroit pour une regle en attente d'arbitrage.
    """
    return lecture_referentiel.mentions()


@routeur.get("/correspondants", response=list[CorrespondantRef], auth=session_seule)
def chercher_correspondants(request, q: str = "", limite: int = 20):
    """
    Le carnet d'adresses, cherche par nom.

    **La recherche est obligatoire.** `q` vide rend une liste vide et non le
    carnet entier : le referentiel est destine a grossir jusqu'a plusieurs
    milliers d'entrees, et le front n'interroge qu'a partir de deux caracteres.
    Rendre tout sur une requete sans critere serait la seule facon de faire
    tomber l'ecran d'enregistrement le jour ou le carnet sera plein.

    Le parametre s'appelle `q` — c'est ce que le front envoie.
    """
    return lecture_referentiel.correspondants(q, limite)


@routeur.post(
    "/correspondants",
    response={201: CorrespondantRef},
    auth=exige(PERM.ENR, PERM.ADM_PAR),
)
def creer_correspondant(request, saisie: SaisieCorrespondant):
    """
    Inscrit un expediteur au carnet d'adresses — le « Créer un correspondant »
    de l'ecran A-01.

    **Pourquoi `ENR` et pas seulement `ADM_PAR`.** Le carnet est ferme a la
    saisie libre, pour de bonnes raisons (voir `SelecteurCorrespondant`). Mais un
    agent de session tient l'enveloppe en main : lui demander d'attendre
    l'administrateur fonctionnel pour enregistrer un courrier arrive reviendrait
    a arreter le registre. L'ecriture est donc ouverte a qui enregistre, et
    inscrite au journal — c'est la trace, non la permission, qui tient le
    referentiel propre.

    Rend la meme forme que la recherche : le selecteur affiche l'entree creee
    sans second aller-retour.
    """
    correspondant = services.creer_correspondant(
        request.auth,
        type=saisie.type,
        raison_sociale=saisie.raisonSociale,
        nom=saisie.nom,
        prenom=saisie.prenom,
        sigle=saisie.sigle,
        adresse=saisie.adresse,
        ville=saisie.ville,
        courriel=saisie.courriel,
        telephone=saisie.telephone,
    )
    return 201, lecture_referentiel.correspondant(correspondant)

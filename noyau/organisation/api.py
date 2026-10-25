"""
Routes du referentiel de l'organisation — `/api/referentiels/*`.

Le referentiel appartient au **socle** : c'est `noyau.organisation.Structure`
qui est lu, le meme objet que `POST /organisation/structures` ecrit. L'ecriture
est gardee par `ADM_ORG` (ADR 021) ; la lecture, elle, sert sept ecrans de
quatre piliers et n'appartient a aucun.

**`session_seule` et non une permission nommee** — derogation ecrite, ADR 007.
Un agent qui cote un courrier vers une autre direction doit la trouver dans la
liste ; exiger `ADM_ORG` fermerait la liste a tout le monde sauf a
l'administrateur, et `restreindre()` la reduirait au perimetre de l'agent, ce
qui rendrait la cotation impossible. La derogation porte sur l'organigramme seul : rien de ce
qui s'y rattache — courriers, decisions, activites — ne se lit ainsi.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import session_seule
from noyau.organisation import lecture
from noyau.organisation.schemas import AgentRef, PosteRef, StructureRef

routeur = Router()


@routeur.get("/structures", response=list[StructureRef], auth=session_seule)
def lister_structures(request):
    """Les structures en vigueur — l'annuaire de l'organigramme, sans filtre."""
    return lecture.referentiel_structures()


@routeur.get("/postes", response=list[PosteRef], auth=session_seule)
def lister_postes(request, structureId: int | None = None):
    """
    Les postes en vigueur, filtrables par structure.

    Meme derogation que les structures (ADR 007) : affecter un agent ailleurs
    suppose de voir les postes d'une structure hors de son propre perimetre.

    Le parametre est en camelCase parce qu'il traverse l'URL et que la
    convention de sortie du projet est celle-la — le nommer `structure_id`
    obligerait le front a une exception a lui seul.
    """
    return lecture.referentiel_postes(structureId)


@routeur.get("/agents", response=list[AgentRef], auth=session_seule)
def lister_agents(request, structureId: int | None = None):
    """
    Les agents actifs, filtrables par structure — ADR 020.

    C'est ce que lisent les selecteurs de responsable : responsable d'une
    activite, d'une tache ou d'une instruction, president d'une seance,
    rapporteur d'un point, agent absent et son interimaire.

    **Meme derogation que l'organigramme, et pour la meme raison.** Elle est
    ici plus lourde de consequence — un annuaire nomme des personnes, pas des
    boites — d'ou trois champs seulement dans `AgentRef`, et aucun moyen de
    joindre qui que ce soit.
    """
    return lecture.referentiel_agents(structureId)

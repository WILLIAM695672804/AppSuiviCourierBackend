"""
Application du perimetre a une requete.

**C'est la piece la plus sensible du backend.** Tout ce qui se lit passe par
ici. Une erreur ne provoque pas de plantage : elle montre a un agent des
donnees qu'il n'a pas le droit de voir, sans que personne ne s'en apercoive.

Trois regles, non negociables :

 1. **Le filtrage se fait en base, jamais a l'affichage.** La decision de
    cadrage D5 le dit pour le courrier confidentiel — « filtrage au niveau
    des donnees, pas au niveau de l'affichage » — et la raison vaut partout :
    un total calcule sur des lignes qu'on masque ensuite reste faux.

 2. **Aucune vue ne construit son filtre elle-meme.** Elle appelle
    `restreindre()`. Un filtre recopie a la main est un filtre qui sera
    oublie au prochain endpoint.

 3. **En cas de doute, on ne montre rien.** Un utilisateur sans perimetre en
    vigueur ne voit rien, et cela doit rester ainsi : l'inverse — tout voir
    faute de restriction — est la faille classique de ce type de couche.
"""

from collections.abc import Sequence

from django.db import models

from noyau.identite.modeles import Utilisateur
from noyau.perimetre.modeles import (
    PORTEE_PROPRE,
    PORTEE_SOUS_ARBRE,
    PORTEE_STRUCTURE,
    PORTEE_TOUTES,
    Perimetre,
)

#: Un chemin ORM vers la structure d'un objet, ou plusieurs combines par OU.
#: Un chemin qui traverse une table de rattachement porte ses conditions avec
#: lui : `("structures_associees__structure", {"…__invalide_le__isnull": True})`.
CheminsStructure = str | Sequence[str | tuple[str, dict]]


def perimetre_en_vigueur(utilisateur: Utilisateur) -> Perimetre | None:
    """Le perimetre non clos de l'utilisateur. `None` s'il n'en a aucun."""
    return (
        Perimetre.objects.filter(utilisateur=utilisateur, valide_au__isnull=True)
        .select_related("structure")
        .order_by("-valide_du")
        .first()
    )


def structures_visibles(utilisateur: Utilisateur) -> models.QuerySet | None:
    """
    Les structures que l'utilisateur peut voir.

    Renvoie `None` — et non une liste vide — lorsque la portee est
    `toutes` : l'appelant doit alors ne poser aucun filtre. Une liste
    contenant toutes les structures aurait produit un `IN` de plusieurs
    centaines d'identifiants a chaque requete.
    """
    from noyau.organisation.modeles import Structure

    perimetre = perimetre_en_vigueur(utilisateur)
    if perimetre is None:
        return Structure.objects.none()

    if perimetre.portee == PORTEE_TOUTES:
        return None

    if perimetre.structure is None:
        # Incoherence de donnees : une portee bornee sans structure. La
        # contrainte CHECK l'interdit en base, mais on ne parie pas sur elle
        # pour decider de ce qu'un agent voit.
        return Structure.objects.none()

    if perimetre.portee == PORTEE_SOUS_ARBRE:
        return perimetre.structure.descendants()

    # `propre` et `structure` bornent tous deux a la structure de rattachement.
    # Ce qui les distingue tient au champ de restriction supplementaire, que
    # `restreindre()` applique par `champ_agent`.
    #
    # `perimetre.structure` et non `structure_id` : le cas None est deja traite
    # plus haut, et l'objet porte le type que mypy attend.
    return Structure.objects.filter(pk=perimetre.structure.pk)


def porte_une_structure(utilisateur: Utilisateur) -> bool:
    """
    Vrai partout **sauf** en portee `propre`.

    A appeler avant `restreindre()` lorsque l'objet a restreindre **n'a pas
    d'agent responsable** — une obligation pese sur une structure, un engagement
    aussi. `restreindre()` leve dans ce cas plutot que d'elargir la restriction
    au niveau de la structure ; l'appelant doit donc passer par les structures
    accessibles, ce qui donne exactement la structure de rattachement de l'agent.

    Ni un contournement ni un raccourci : c'est la question « cet objet a-t-il
    un responsable nomme ? » posee au bon endroit.
    """
    perimetre = perimetre_en_vigueur(utilisateur)
    return perimetre is not None and perimetre.portee != PORTEE_PROPRE


def restreindre(
    requete: models.QuerySet,
    utilisateur: Utilisateur,
    *,
    champ_structure: CheminsStructure = "structure",
    champ_agent: str | None = None,
) -> models.QuerySet:
    """
    Restreint une requete au perimetre de l'utilisateur.

    `champ_structure` est le chemin ORM vers la structure de l'objet — souvent
    `structure`, parfois `plan__structure`.

    **Il peut y en avoir plusieurs**, et les chemins sont alors combines par
    OU : une activite se rattache a la structure de son plan *ou* a l'une de
    ses structures associees (ADR 047). Le resultat est `distinct()`, car une
    activite associee a trois structures visibles reviendrait trois fois.

    Un chemin qui traverse une table de rattachement se donne avec ses
    conditions, sous la forme `(chemin, {filtres})` — typiquement « le
    rattachement n'est pas retire ». Les conditions rejoignent le meme `Q`, donc
    la meme jointure : les poser dans un `filter()` separe porterait sur une
    autre ligne de la table de rattachement et exclurait des activites
    parfaitement visibles.

    `champ_agent` est le chemin vers l'agent responsable. Il n'est utilise
    qu'en portee `propre`, et c'est ce qui distingue un agent instructeur
    — qui ne voit que ses propres dossiers — d'un chef de service qui voit
    ceux de sa structure. L'omettre en portee `propre` degrade silencieusement
    la restriction au niveau `structure` : le journal l'aurait mauvaise, donc
    on leve plutot que de laisser passer.
    """
    perimetre = perimetre_en_vigueur(utilisateur)
    if perimetre is None:
        return requete.none()

    if perimetre.portee == PORTEE_TOUTES:
        return requete

    if perimetre.portee == PORTEE_PROPRE:
        if champ_agent is None:
            raise ValueError(
                "Portee « propre » sans champ_agent : la restriction serait plus large "
                "que le perimetre. Precisez le chemin vers l'agent responsable."
            )
        return requete.filter(**{champ_agent: utilisateur.pk})

    structures = structures_visibles(utilisateur)
    if structures is None:
        return requete

    if perimetre.portee in (PORTEE_STRUCTURE, PORTEE_SOUS_ARBRE):
        return _filtrer_sur_structures(requete, champ_structure, structures)

    # Portee inconnue : on ne montre rien. Voir regle 3 de l'entete.
    return requete.none()


def _filtrer_sur_structures(
    requete: models.QuerySet,
    champ_structure: CheminsStructure,
    structures: models.QuerySet,
) -> models.QuerySet:
    """
    Le filtre de portee bornee, sur un chemin ou sur plusieurs.

    Un seul chemin : le filtre direct, sans `distinct()` — l'ajouter partout
    couterait un tri a chaque registre du produit pour un doublon qui ne peut
    pas se produire sur une cle etrangere simple.
    """
    chemins = [champ_structure] if isinstance(champ_structure, str) else list(champ_structure)
    if not chemins:
        raise ValueError("Aucun chemin de structure : la restriction serait vide de sens.")

    if len(chemins) == 1 and isinstance(chemins[0], str):
        return requete.filter(**{f"{chemins[0]}__in": structures})

    condition = models.Q()
    for entree in chemins:
        chemin, filtres = (entree, {}) if isinstance(entree, str) else entree
        # Un seul `Q` : les conditions du rattachement portent sur la meme
        # jointure que le test de structure.
        condition |= models.Q(**{f"{chemin}__in": structures}, **filtres)
    # La jointure sur une relation inverse duplique la ligne mere.
    return requete.filter(condition).distinct()

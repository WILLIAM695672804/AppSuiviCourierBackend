"""
Ce qui se lit du referentiel de l'organisation.

**Ce module ne passe pas par `restreindre()`, et c'est une derogation ecrite** :
voir l'ADR 007. Un referentiel de saisie doit montrer les structures que l'agent
ne voit pas — on ne cote pas vers une direction qu'on ne peut pas lire dans la
liste. La derogation vaut pour l'organigramme, jamais pour ce qui s'y rattache.

Seules les structures **en vigueur** sortent : `Structure.objects.en_vigueur()`.
Une direction dissoute garde sa ligne close pour l'histoire, mais elle ne doit
plus pouvoir etre choisie dans un selecteur.
"""

from django.db.models import F, QuerySet

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Poste, Structure


def responsables(structures: QuerySet[Structure]) -> dict[int, str]:
    """
    Qui repond pour chaque structure, deduit du **poste** occupe.

    Il n'existe pas de colonne « responsable » sur `structure`, et c'est
    delibere (`gouvernance.services.creer_structure`) : la hierarchie est portee
    par le poste, avec sa date d'effet. La deduire ici coute une requete ; la
    stocker aurait coute une seconde verite, qui aurait vieilli.

    Trois criteres, dans cet ordre : le poste **sans superieur** dans la
    structure passe devant — c'est le sommet local ; puis le rang du niveau
    hierarchique ; puis, a egalite, l'ordre du modele (`nom`, `prenom`).
    Arbitraire au dernier cran, mais stable : un referentiel qui change d'avis
    d'un rafraichissement a l'autre est illisible.

    Le jeu d'essai ne renseigne pas `poste_superieur` : les deux premiers
    criteres y sont neutres, et c'est le nom qui tranche. En production, la
    hierarchie saisie reprend la main sans qu'on ait a toucher a ce code.
    """
    return {
        structure_id: agent.nom_complet
        for structure_id, agent in responsables_comptes(structures).items()
    }


def responsables_comptes(structures: QuerySet[Structure]) -> dict[int, Utilisateur]:
    """
    Les memes responsables, mais **le compte** et non le nom.

    `responsables()` sert les referentiels, qui affichent ; ce que veut celui
    qui notifie, c'est a qui ecrire. Deux requetes avec le meme tri auraient
    fini par diverger sur un des trois criteres, et la notification serait
    partie a un autre que celui que l'ecran designe comme responsable.
    """
    agents = (
        Utilisateur.objects.actifs()
        .filter(poste__structure__in=structures, poste__valide_au__isnull=True)
        .select_related("poste__niveau_hierarchique")
        .order_by(
            F("poste__poste_superieur").asc(nulls_first=True),
            "poste__niveau_hierarchique__rang",
            "nom",
            "prenom",
        )
    )

    trouves: dict[int, Utilisateur] = {}
    for agent in agents:
        trouves.setdefault(agent.poste.structure_id, agent)
    return trouves


def referentiel_agents(structure_id: int | None = None) -> list[dict]:
    """
    Les agents actifs, filtrables par structure — l'annuaire des selecteurs.

    Meme derogation que les structures et les postes, etendue aux personnes :
    lu **sans perimetre**, ADR 020. Un point focal inscrit les activites de
    toute sa direction et doit pouvoir en designer le responsable ; borner
    cette liste a son perimetre lui interdirait de nommer son propre directeur,
    qui releve d'une structure superieure a la sienne.

    `structure` est prise du **poste** quand il y en a un, et de la colonne
    `structure` du compte sinon. Les deux existent et ne disent pas la meme
    chose : le poste dit ou l'agent travaille, la colonne ou il est rattache.
    Elles coincident chez tous les comptes du jeu d'essai, et la premiere fait
    foi le jour ou elles divergent — c'est le poste qui porte la hierarchie.

    Les comptes du portail n'en sont pas : un usager n'a ni poste ni structure,
    et n'a rien a faire dans un selecteur de responsable interne. Le filtre est
    donc `structure` non nulle **ou** poste renseigne.
    """
    agents = (
        Utilisateur.objects.actifs()
        .select_related("poste", "poste__structure", "structure")
        .exclude(poste__isnull=True, structure__isnull=True)
    )
    if structure_id is not None:
        agents = agents.filter(poste__structure_id=structure_id)

    resultat = []
    for agent in agents.order_by("nom", "prenom"):
        structure = agent.poste.structure if agent.poste else agent.structure
        resultat.append(
            {
                "id": agent.pk,
                "nomComplet": agent.nom_complet,
                "poste": agent.poste.libelle if agent.poste else "",
                "structure": structure.code if structure else "",
                "structureId": structure.pk if structure else None,
            }
        )
    return resultat


def referentiel_postes(structure_id: int | None = None) -> list[dict]:
    """
    Les postes en vigueur, filtrables par structure.

    Ils servent un seul ecran — la creation et la mutation d'un compte — mais
    ils lui sont indispensables : `POST /habilitations/utilisateurs` exige un
    `posteId`, et le service refuse un poste qui ne releve pas de la structure
    choisie. Sans cette liste, le formulaire n'aurait rien a proposer.

    Meme derogation que les structures : lu **sans perimetre** (ADR 007).
    Choisir le poste d'un agent qu'on affecte ailleurs suppose de voir les
    postes de sa structure d'arrivee, par definition hors du sien.

    `structureId` n'est pas un confort : la liste complete melerait des postes
    homonymes de directions differentes — « Chef de service » y figurerait
    huit fois sans que rien ne les distingue.

    **`posteSuperieurId` peut pointer hors du lot rendu** quand le filtre est
    pose : le superieur d'un chef de service est le directeur, qui releve de la
    meme structure, mais celui d'un directeur est le Directeur general, qui
    n'en releve pas. Un appelant qui construit l'arbre nominatif demande donc
    la liste complete ; le filtre sert au selecteur de poste, qui n'a que faire
    de la hierarchie.
    """
    postes = Poste.objects.en_vigueur().select_related("structure", "niveau_hierarchique")
    if structure_id is not None:
        postes = postes.filter(structure_id=structure_id)

    return [
        {
            "id": poste.pk,
            "libelle": poste.libelle,
            "structureId": poste.structure_id,
            "structure": poste.structure.code,
            "niveau": poste.niveau_hierarchique.rang,
            "posteSuperieurId": poste.poste_superieur_id,
        }
        for poste in postes.order_by("structure__code", "niveau_hierarchique__rang", "libelle")
    ]


def referentiel_structures() -> list[dict]:
    """
    La liste des structures en vigueur, ordonnee du sommet vers la base.

    `parentId` est rendu **brut**, sans verifier que le parent est lui-meme en
    vigueur. Le cas se produit : cloturer une structure et en reouvrir une
    nouvelle ligne lui donne un nouvel identifiant, et ses filles pointent
    encore vers l'ancienne. Le front verrait alors des racines multiples sans
    savoir pourquoi.

    Le corriger ici — remonter au grand-parent, ou rendre `None` — reviendrait
    a masquer une incoherence du referentiel derriere un arbre qui a l'air
    juste. Elle est donc **signalee** : `administration.lecture` la compte
    parmi les anomalies du referentiel, et le front affiche ces structures a
    part au lieu de les fondre dans la racine.

    `delaiMoyenJours` et `courriersEnCours` n'ont **aucune source** : le pilier
    courrier n'existe pas encore cote serveur. Ils sortent a `None` et `0`
    plutot que d'etre inventes — une moyenne fabriquee serait recopiee dans un
    rapport avant d'etre corrigee. Question ouverte notee dans
    `docs/questions-ouvertes.md`.
    """
    structures = (
        Structure.objects.en_vigueur()
        .select_related("niveau_hierarchique")
        .order_by("niveau_hierarchique__rang", "code")
    )

    chefs = responsables(structures)

    return [
        {
            "id": structure.pk,
            "libelle": structure.libelle,
            "sigle": structure.code,
            "nature": structure.nature,
            "niveau": structure.niveau_hierarchique.rang,
            "parentId": structure.parent_id,
            "responsable": chefs.get(structure.pk),
            "delaiMoyenJours": None,
            "courriersEnCours": 0,
        }
        for structure in structures
    ]

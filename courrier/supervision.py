"""
Le mapping complet de la DSR — ou est bloque chaque courrier, et depuis quand.

    « Le profil DSR doit conserver l'acces au mapping complet — date, heure,
      responsable exact ou est bloque le courrier — pour assurer sa mission de
      suivi des delais. »

La matiere existait deja : la fiche de vie donne la date, l'heure, l'acteur et
la marge entre deux etapes ; `_detenteurs()` donne qui a tenu le courrier et
combien de temps. **Ce qui manquait est transversal.** Le registre affiche
l'etape et le delai, mais ni le detenteur courant ni depuis quand : « ou est
bloque le courrier » se lisait courrier par courrier, ce qui n'est pas une
mission de suivi mais une enquete.

D'ou cet ecran, qui repond a une seule question — **qu'est-ce qui n'avance
pas** — et la classe par immobilisation decroissante.

**Ce que « bloque » veut dire ici.** Le courrier est arrete a l'endroit ou son
dernier fait s'est produit, et cet endroit a trois formes, dans cet ordre :

 1. un **agent affecte** — il detient le dossier, c'est le responsable exact ;
 2. une **structure qui n'a pas accuse reception** — le courrier est arrive chez
    elle et personne ne l'a ouvert. C'est le blocage le plus difficile a voir
    autrement, parce qu'aucun acteur ne s'y attache ;
 3. le **bureau d'ordre central** — le courrier est enregistre et n'est pas
    cote. Il attend l'autorite.

Aucune de ces trois n'est une invention : chacune se lit dans une table, et la
troisieme est simplement l'absence des deux autres.

Le cloisonnement ne s'applique pas a cet ecran, et il n'y a pas de contradiction :
il protege une structure de sa voisine, pas de son autorite de suivi. La route
exige `REL` — la permission de relancer —, qui est aussi ce qui ouvre le dossier
interne dans `cloisonnement.py`. Les deux tiennent la meme frontiere, et il faut
qu'elles la tiennent au meme endroit.
"""

from django.db.models import Q
from django.utils import timezone

from courrier.lecture import _delai, _etapes
from courrier.modeles import STATUT_CLOTURE, Affectation, Courrier, PassageStructure
from courrier.visibilite import visibles
from noyau.identite.modeles import Utilisateur

#: Le plafond de lignes rendues. La supervision se lit du haut : ce qui dort
#: depuis le plus longtemps est en tete, et la deux-centieme ligne d'une liste
#: triee par immobilisation n'a jamais decide d'une relance.
PLAFOND = 200


def carte_des_blocages(
    utilisateur: Utilisateur,
    *,
    structure_id: int | None = None,
    seuil_jours: int = 0,
) -> dict:
    """
    Tous les courriers en cours, avec qui les detient et depuis quand.

    `seuil_jours` ecarte ce qui vient d'arriver : un courrier immobilise depuis
    deux heures n'est pas bloque, il est en cours de lecture. Le defaut est a
    zero — l'ecran pose le filtre, pas le serveur, qui n'a pas a decider a partir
    de quand un retard est un retard.
    """
    base = visibles(
        Courrier.objects.filter(invalide_le__isnull=True).exclude(statut_courrier=STATUT_CLOTURE),
        utilisateur,
    ).select_related("nature", "priorite")

    if structure_id is not None:
        base = base.filter(
            Q(structure_chef_file_id=structure_id)
            | Q(
                cotations__invalide_le__isnull=True,
                cotations__structures__structure_id=structure_id,
            )
        ).distinct()

    courriers = list(base[: PLAFOND * 2])
    identifiants = [courrier.pk for courrier in courriers]
    etapes = _etapes(identifiants, courriers)
    detenteurs = _detenteurs_courants(identifiants)

    maintenant = timezone.now()
    lignes = []
    for courrier in courriers:
        blocage = detenteurs.get(courrier.pk) or _attente_du_central(courrier)
        immobilise = max(0, (maintenant - blocage["depuis"]).days)
        if immobilise < seuil_jours:
            continue

        delai = _delai(courrier)
        lignes.append(
            {
                "courrierId": courrier.pk,
                "numero": courrier.numero,
                "objet": courrier.objet,
                "correspondant": courrier.expediteur_libelle,
                "etape": etapes[courrier.pk],
                "echeance": courrier.date_limite,
                "joursDepassement": delai["joursDepassement"] if delai else 0,
                # Le responsable exact, ou la structure quand personne n'est
                # nomme. Les deux champs coexistent parce que l'exigence demande
                # « le responsable exact » et que, dans un cas sur trois, il
                # n'existe pas encore — c'est precisement le blocage.
                "detenteur": blocage["detenteur"],
                "structure": blocage["structure"],
                "motif": blocage["motif"],
                "depuis": blocage["depuis"],
                "joursImmobilise": immobilise,
            }
        )

    # Le tri est en Python et non en base : l'immobilisation se calcule sur trois
    # tables differentes selon le cas, et un `ORDER BY` unique ne saurait pas
    # laquelle regarder.
    lignes.sort(key=lambda ligne: ligne["joursImmobilise"], reverse=True)
    lignes = lignes[:PLAFOND]

    return {
        "lignes": lignes,
        "total": len(lignes),
        "arreteLe": maintenant,
        "resume": _resume(lignes),
    }


def _detenteurs_courants(identifiants: list[int]) -> dict[int, dict]:
    """
    Qui detient chaque courrier, en deux requetes d'ensemble.

    L'affectation ouverte l'emporte sur le passage non accuse : quand un agent
    est nomme, c'est lui le responsable exact, et dire « la DAF » a sa place
    serait exactement l'imprecision que l'exigence reproche.

    Le tri par date **croissante** puis l'ecrasement du dictionnaire retient la
    ligne la plus recente : c'est le detenteur actuel, pas le premier.
    """
    if not identifiants:
        return {}

    par_courrier: dict[int, dict] = {}

    # 1. Les structures ou le courrier dort sans avoir ete ouvert.
    passages = (
        PassageStructure.objects.filter(
            courrier_id__in=identifiants, accuse_le__isnull=True, sorti_le__isnull=True
        )
        .select_related("structure")
        .order_by("entre_le")
    )
    for passage in passages:
        par_courrier[passage.courrier_id] = {
            "detenteur": None,
            "structure": passage.structure.code,
            "motif": "Reçu, non accusé par le bureau d'ordre",
            "depuis": passage.entre_le,
        }

    # 2. Les agents affectes, qui l'emportent.
    affectations = (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier_id__in=identifiants,
            retire_le__isnull=True,
        )
        .select_related(
            "utilisateur",
            "cotation_structure__structure",
            "cotation_structure__cotation",
        )
        .order_by("affecte_le")
    )
    for affectation in affectations:
        agent = affectation.utilisateur
        par_courrier[affectation.cotation_structure.cotation.courrier_id] = {
            "detenteur": f"{agent.prenom} {agent.nom}",
            "structure": affectation.cotation_structure.structure.code,
            "motif": "Affecté, traitement en cours",
            "depuis": affectation.affecte_le,
        }

    return par_courrier


def _attente_du_central(courrier: Courrier) -> dict:
    """
    Le courrier n'est ni affecte ni en attente d'accuse : il attend l'autorite.

    On date l'immobilisation a l'enregistrement, et « faute de mieux » serait
    inexact : rien d'autre ne s'est produit depuis, c'est bien le sens du
    chiffre. `cree_le` est pose par `auto_now_add` et ne manque jamais ; le
    repli sur maintenant couvre la seule ligne qui pourrait venir d'une reprise
    de donnees, et il vaut alors « immobilise depuis zero jour », ce qui ne
    declenche aucune relance a tort.
    """
    return {
        "detenteur": None,
        "structure": None,
        "motif": "Enregistré, en attente de cotation",
        "depuis": courrier.cree_le or timezone.now(),
    }


def _resume(lignes: list[dict]) -> list[dict]:
    """
    Les quatre chiffres de l'entete.

    Le ton n'est pas decoratif : c'est lui qui dit, sans lire la liste, si la
    situation demande une relance aujourd'hui.
    """
    hors_delai = sum(1 for ligne in lignes if ligne["joursDepassement"] > 0)
    sans_accuse = sum(1 for ligne in lignes if ligne["motif"].startswith("Reçu"))
    plus_ancien = max((ligne["joursImmobilise"] for ligne in lignes), default=0)

    return [
        {"libelle": "En cours", "valeur": str(len(lignes)), "ton": "neutre"},
        {
            "libelle": "Hors délai",
            "valeur": str(hors_delai),
            "ton": "alerte" if hors_delai else "succes",
        },
        {
            "libelle": "Sans accusé de réception",
            "valeur": str(sans_accuse),
            "ton": "alerte" if sans_accuse else "succes",
        },
        {
            "libelle": "Immobilisation la plus longue",
            "valeur": f"{plus_ancien} j",
            "ton": "alerte" if plus_ancien > 15 else "neutre",
        },
    ]

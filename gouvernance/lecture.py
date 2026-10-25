"""
Ce qui se lit du pilier gouvernance.

**Toute requete part de `_engagements_visibles()` ou de `_seances_visibles()`.**
Aucune vue ne construit son filtre : un filtre recopie a la main est un filtre
qui sera oublie au prochain endpoint, et l'oubli ne produit aucune erreur — il
montre a un agent la decision qui contraint une autre direction.

Un engagement n'a **pas d'agent responsable** : il pese sur des structures, comme
une obligation. `restreindre()` leve donc en portee `propre` faute de
`champ_agent`, et l'on passe par `porte_une_structure()` — le detour est le meme
que pour les obligations, et pour la meme raison.

L'etat affiche ne se lit jamais des colonnes : il vient de `v_engagement_etat`.
Le recalculer ici ferait deux verites, dont l'une serait fausse le lendemain —
« en retard » change avec le temps sans qu'aucune ecriture ne survienne.
"""

from collections.abc import Iterable
from datetime import date

from django.db.models import Count, Q, QuerySet

from gouvernance.modeles import (
    CongeDroit,
    Disponibilite,
    Engagement,
    OrganeGestion,
    Representation,
    Seance,
    VueEngagementEtat,
)
from noyau.calendrier import en_toutes_lettres
from noyau.erreurs import HorsPerimetre
from noyau.feu import feu
from noyau.filtres import est_tout
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.organisation.tete import consolide, tete_de
from noyau.perimetre.portee import porte_une_structure, restreindre, structures_visibles

# =====================================================================
#  Traductions vers le front
#
#  Faites **une seule fois**, ici. La base garde ses codes sans accent ;
#  l'ecran affiche du francais lisible.
# =====================================================================

ETATS_VERS_FRONT = {
    "a_lancer": "À lancer",
    "en_cours": "En cours",
    "execute": "Exécutée",
    "en_retard": "En retard",
    "suspendu": "Suspendue",
}

INSTANCES_VERS_FRONT = {
    "conseil_administration": "Conseil d'administration",
    "codir": "CODIR",
    "directeur_general": "Directeur général",
    "assemblee_generale": "Assemblée générale",
}

TYPES_SEANCE_VERS_FRONT = {
    "reunion_dg": "Réunion présidée par le DG",
    "session_ca": "Session du Conseil d'administration",
    "assemblee_generale": "Assemblée générale",
    "codir": "CODIR",
    "rapport_activite": "Rapport d'activité",
    "rapport_sectoriel": "Rapport sectoriel",
}

NATURES_DOCUMENT_VERS_FRONT = {
    "ordre_du_jour": "Ordre du jour",
    "compte_rendu": "Compte rendu",
    "proces_verbal": "Procès-verbal",
    "dossier_seance": "Dossier de séance",
    "rapport": "Rapport",
}

TYPES_ABSENCE_VERS_FRONT = {
    "conge_annuel": "Congé annuel",
    "mission": "Mission",
    "interim": "Intérim",
    "formation": "Formation",
    "absence_exceptionnelle": "Absence exceptionnelle",
}

ETATS_CONGE_VERS_FRONT = {
    "souhaite": "Souhaité",
    "arbitre": "Arbitré",
    "valide": "Validé",
    "reporte": "Reporté",
}

NATURES_ENTITE_VERS_FRONT = {"filiale": "Filiale", "succursale": "Succursale"}

ORGANES_VERS_FRONT = {
    "conseil_administration": "Conseil d'administration",
    "assemblee_generale": "Assemblée générale",
    "comite_gestion": "Comité de gestion",
}

PREPARATIONS_VERS_FRONT = {
    "a_preparer": "À préparer",
    "dossier_en_cours": "Dossier en cours",
    "dossier_transmis": "Dossier transmis",
    "tenue": "Tenue",
}

NATURES_ORGANISATION_VERS_FRONT = {
    "comite_national": "Comité national",
    "organisation_portuaire": "Organisation portuaire",
    "association_professionnelle": "Association professionnelle",
    "groupement": "Groupement",
}

#: Le front distingue trois provenances **d'affichage** pour une decision
#: d'instance. Ce n'est pas `engagement.origine` — qui vaut ici toujours
#: `instance` — mais la nature de la seance dont elle est issue.
ORIGINES_AFFICHEES = {
    "session_ca": "Session",
    "assemblee_generale": "Session",
    "reunion_dg": "Réunion",
    "codir": "Réunion",
    "rapport_activite": "Réunion",
    "rapport_sectoriel": "Réunion",
}


# =====================================================================
#  Points de passage
# =====================================================================


def _structures_accessibles(utilisateur: Utilisateur) -> list[Structure]:
    """
    Les structures dont l'agent voit les objets.

    Portee `toutes` : toutes celles en vigueur. Portee bornee ou `propre` :
    celles que `structures_visibles()` renvoie — pour `propre`, sa seule
    structure de rattachement.
    """
    visibles = structures_visibles(utilisateur)
    if visibles is None:
        return list(Structure.objects.filter(valide_au__isnull=True).order_by("code"))
    return list(visibles.filter(valide_au__isnull=True).order_by("code"))


def _engagements_visibles(utilisateur: Utilisateur) -> QuerySet:
    """
    Les engagements que l'utilisateur peut voir. **Le point de passage unique.**

    Un engagement est visible par les structures qui en sont **chargees**, et par
    elles seules. Ni la seance d'origine ni l'auteur de la saisie n'ouvrent le
    droit de lecture : la DSR voit tout parce que son perimetre est large, pas
    parce qu'elle a tenu la plume.

    Consequence assumee : un engagement **sans structure chargee** n'est visible
    de personne. C'est pourquoi `services.creer_engagement()` en exige au moins
    une — un engagement que nul ne porte n'est pas un engagement.

    `distinct()` n'est pas decoratif : la jointure sur les structures chargees
    duplique la ligne autant de fois qu'il y a de structures visibles, et les
    compteurs du tableau de bord compteraient deux fois le meme engagement.
    """
    base = Engagement.objects.filter(invalide_le__isnull=True)
    if porte_une_structure(utilisateur):
        return restreindre(base, utilisateur, champ_structure="structures__structure").distinct()
    return base.filter(structures__structure__in=_structures_accessibles(utilisateur)).distinct()


def _seances_visibles(utilisateur: Utilisateur) -> QuerySet:
    """
    Les seances que l'utilisateur peut voir, bornees par la structure
    organisatrice — celle qui en tient le secretariat.

    Le president ne sert pas de `champ_agent` : presider une seance n'est pas
    en repondre, et un directeur qui ne verrait que les seances qu'il preside
    perdrait de vue celles dont son service doit deposer le compte rendu.
    """
    base = Seance.objects.filter(invalide_le__isnull=True)
    if porte_une_structure(utilisateur):
        return restreindre(base, utilisateur, champ_structure="structure")
    return base.filter(structure__in=_structures_accessibles(utilisateur))


def _disponibilites_visibles(utilisateur: Utilisateur) -> QuerySet:
    """
    Les absences que l'utilisateur peut voir, bornees par la structure de
    l'absent.

    Ici `champ_agent` existe et vaut l'absent lui-meme : en portee `propre`, un
    agent voit ses propres absences. C'est le minimum utile — les siennes le
    concernent, celles de son directeur ne le regardent pas.
    """
    return restreindre(
        Disponibilite.objects.filter(invalide_le__isnull=True),
        utilisateur,
        champ_structure="utilisateur__structure",
        champ_agent="utilisateur_id",
    )


def _etats(engagements: Iterable[Engagement]) -> dict[int, VueEngagementEtat]:
    """
    L'etat affiche de chaque engagement, en **une seule requete**.

    Sur un registre de deux cents lignes, interroger la vue ligne a ligne ferait
    deux cents allers-retours pour une information que la base sait donner d'un
    coup.
    """
    identifiants = [e.pk for e in engagements]
    return {v.pk: v for v in VueEngagementEtat.objects.filter(pk__in=identifiants)}


def _feu_engagement(etat: str, avancement: float) -> str:
    """
    Un engagement suspendu sort en « inconnu » et non en vert.

    Son avancement est fige : le peindre en vert dirait qu'il va bien, le peindre
    en rouge dirait qu'on est en faute. Ni l'un ni l'autre — il est a l'arret sur
    decision.
    """
    if etat == "suspendu":
        return "inconnu"
    if etat == "en_retard":
        return "rouge"
    return feu(avancement)


# =====================================================================
#  Engagements — le registre des decisions
# =====================================================================


def _libelle_origine(engagement: Engagement) -> tuple[str, str, int | None]:
    """
    Le triplet `(type, libelle, id)` que la fiche affiche en provenance.

    Une decision sans seance rattachee est une **instruction verbale** : le DG
    decide en reunion de coordination et la DSR consigne. Le §17 en fait un cas
    ordinaire, pas une anomalie a corriger.
    """
    if engagement.seance is not None:
        seance = engagement.seance
        return (
            ORIGINES_AFFICHEES.get(seance.type_seance, "Réunion"),
            f"{seance.intitule} du {_en_toutes_lettres(seance.date_seance)}",
            seance.pk,
        )
    if engagement.organe_gestion is not None:
        organe = engagement.organe_gestion
        return (
            "Session",
            f"{ORGANES_VERS_FRONT[organe.organe]} — {organe.entite_externe.sigle}",
            organe.pk,
        )
    if engagement.organisation_externe is not None:
        organisation = engagement.organisation_externe
        return ("Réunion", organisation.libelle, organisation.pk)
    return (
        "Instruction verbale",
        f"Instruction du {_en_toutes_lettres(engagement.date_engagement)}",
        None,
    )


def _en_toutes_lettres(jour: date) -> str:
    """« 26 juin 2026 ». La forme vit dans `noyau/calendrier.py` depuis que le
    pilotage l'emploie aussi."""
    return en_toutes_lettres(jour)


def _structures_chargees(engagement: Engagement) -> list[dict]:
    return [
        {
            "id": charge.structure_id,
            "sigle": charge.structure.code,
            "libelle": charge.structure.libelle,
            "pilote": charge.pilote,
            "avancement": float(charge.avancement),
        }
        for charge in engagement.structures.select_related("structure").order_by("rang")
    ]


def composer_engagement(engagement: Engagement, etat: VueEngagementEtat | None) -> dict:
    """Une ligne du registre des decisions."""
    code_etat = etat.etat_affiche if etat else "a_lancer"
    avancement = float(etat.avancement if etat else engagement.avancement)
    _, libelle_origine, _identifiant = _libelle_origine(engagement)

    return {
        "id": engagement.pk,
        "reference": engagement.reference or "",
        "instance": INSTANCES_VERS_FRONT.get(engagement.instance or "", ""),
        "seance": libelle_origine,
        "objet": engagement.objet,
        "dateDecision": engagement.date_engagement.isoformat(),
        "echeance": engagement.echeance.isoformat() if engagement.echeance else None,
        "etat": ETATS_VERS_FRONT[code_etat],
        "avancement": avancement,
        "feu": _feu_engagement(code_etat, avancement),
        "structures": _structures_chargees(engagement),
        "relances": etat.relances if etat else 0,
    }


def _enrichis(requete: QuerySet) -> QuerySet:
    return requete.select_related(
        "seance",
        "organe_gestion__entite_externe",
        "organisation_externe",
    ).prefetch_related("structures__structure")


def registre_decisions(utilisateur: Utilisateur, *, instance: str = "", etat: str = "") -> dict:
    """
    Le registre des decisions d'instance — origine `instance` seulement.

    Prescriptions de filiales et recommandations externes partagent la table
    (ADR 006) mais **pas cet ecran** : le front les affiche sur les leurs, avec
    leurs propres colonnes. Une seule table ne veut pas dire un seul registre.

    L'ordre compte : le perimetre borne, les filtres affinent. L'inverse
    laisserait un filtre vide montrer plus que le perimetre.
    """
    requete = _enrichis(
        _engagements_visibles(utilisateur).filter(origine=Engagement.INSTANCE)
    ).order_by("-date_engagement")

    if not est_tout(instance):
        requete = requete.filter(instance=_code_instance(instance))

    engagements = list(requete)
    etats = _etats(engagements)
    lignes = [composer_engagement(e, etats.get(e.pk)) for e in engagements]

    if not est_tout(etat):
        lignes = [ligne for ligne in lignes if ligne["etat"] == etat]

    return {
        "decisions": lignes,
        "compteurs": _compteurs_decisions(lignes),
        "total": len(lignes),
    }


def _code_instance(libelle: str) -> str:
    """
    Le front filtre par libelle affiche. Un libelle inconnu ne renvoie rien
    plutot que tout : c'est la regle 3 du perimetre appliquee a un filtre.
    """
    for code, affiche in INSTANCES_VERS_FRONT.items():
        if affiche == libelle:
            return code
    return "__inconnue__"


def _compteurs_decisions(lignes: list[dict]) -> list[dict]:
    total = len(lignes)
    en_retard = sum(1 for ligne in lignes if ligne["etat"] == "En retard")
    executees = sum(1 for ligne in lignes if ligne["etat"] == "Exécutée")
    relancees = sum(1 for ligne in lignes if ligne["relances"] >= 2)
    taux = round(100 * executees / total, 2) if total else None

    return [
        {
            "libelle": "Décisions suivies",
            "valeur": total,
            "note": "dans votre périmètre",
            "feu": "inconnu",
        },
        {
            "libelle": "En retard",
            "valeur": en_retard,
            "note": "échéance dépassée",
            "feu": "rouge" if en_retard else "vert",
        },
        {
            "libelle": "Relancées deux fois",
            "valeur": relancees,
            "note": "sans effet constaté",
            "feu": "rouge" if relancees else "vert",
        },
        {
            "libelle": "Taux d'exécution",
            "valeur": int(taux or 0),
            "note": "décisions exécutées",
            "feu": feu(taux),
        },
    ]


def fiche_decision(utilisateur: Utilisateur, engagement_id: int) -> dict:
    """
    La fiche complete d'une decision.

    **404 et non 403** hors perimetre : repondre « interdit » confirmerait son
    existence — decision D5.
    """
    engagement = _enrichis(_engagements_visibles(utilisateur)).filter(pk=engagement_id).first()
    if engagement is None:
        raise HorsPerimetre("Decision introuvable.")

    etat = VueEngagementEtat.objects.filter(pk=engagement.pk).first()
    detail = composer_engagement(engagement, etat)
    type_origine, libelle_origine, identifiant = _libelle_origine(engagement)
    detail.update(
        {
            "contexte": engagement.contexte or engagement.texte or "",
            "origine": {"type": type_origine, "libelle": libelle_origine, "id": identifiant},
            "jalons": _jalons(engagement),
            "observations": _observations(engagement),
            "retombees": _retombees(engagement),
        }
    )
    return detail


def _jalons(engagement: Engagement) -> list[dict]:
    return [
        {
            "id": jalon.pk,
            "libelle": jalon.libelle,
            "echeance": jalon.echeance.isoformat(),
            "fait": jalon.fait_le is not None,
            "dateRealisation": jalon.fait_le.isoformat() if jalon.fait_le else None,
            "structure": jalon.structure.code if jalon.structure else "",
        }
        for jalon in engagement.jalons.filter(invalide_le__isnull=True)
        .select_related("structure")
        .order_by("ordre")
    ]


def _observations(engagement: Engagement) -> list[dict]:
    """
    Le fil de suivi.

    Une relance automatique n'a **pas d'auteur** et sort en « Traitement
    automatique », comme dans la fiche de vie d'une activite : elle reste dans le
    meme fil, dans l'ordre, parce que c'est ainsi qu'on relit un suivi.
    """
    return [
        {
            "id": observation.pk,
            "auteur": observation.auteur.nom_complet
            if observation.auteur
            else "Traitement automatique",
            "initiales": observation.auteur.initiales if observation.auteur else "—",
            "poste": observation.auteur.poste.libelle
            if observation.auteur and observation.auteur.poste
            else "",
            "date": observation.cree_le.date().isoformat(),
            "texte": observation.texte,
            "relance": observation.relance,
        }
        for observation in engagement.observations.select_related("auteur__poste")
    ]


def _retombees(engagement: Engagement) -> list[dict]:
    """
    Ce que la decision a produit : les activites qu'elle a suspendues, les
    instructions qu'elle porte.

    **Le lien avec le courrier reste lache**, et c'est voulu : une decision
    verbale du DG n'a pas de courrier, et en fabriquer un fictif pour tenir une
    jointure aurait pollue le registre du courrier.
    """
    from activite.modeles import ActiviteSuspension, InstructionActivite

    retombees = []
    for instruction in InstructionActivite.objects.filter(
        decision_reunion=engagement, invalide_le__isnull=True
    ).select_related("activite"):
        retombees.append(
            {
                "type": "Activité",
                "libelle": instruction.activite.intitule,
                "reference": instruction.activite.code,
                "chemin": None,
            }
        )
    for suspension in ActiviteSuspension.objects.filter(
        decision_reunion=engagement, repris_le__isnull=True
    ).select_related("activite"):
        retombees.append(
            {
                "type": "Suspension",
                "libelle": f"Activité suspendue : {suspension.activite.intitule}",
                "reference": suspension.activite.code,
                "chemin": None,
            }
        )
    return retombees


# =====================================================================
#  Seances
# =====================================================================


def _etat_depot(seance: Seance, aujourd_hui: date) -> tuple[str, str | None]:
    """
    L'etat du depot du compte rendu, et sa date.

    Ne se stocke pas : `echeance_depot` et la date constatee suffisent. Le
    stocker imposerait de reecrire toutes les lignes chaque nuit pour un
    resultat que la date donne deja — meme arbitrage que pour le retard.

    Un depot **hors delai reste hors delai** une fois fait : c'est la ponctualite
    qui se mesure, pas la presence du document.
    """
    compte_rendu = next(
        (
            document
            for document in seance.documents.all()
            if document.nature in ("compte_rendu", "proces_verbal")
        ),
        None,
    )
    if compte_rendu is None or compte_rendu.depose_le is None:
        return ("Hors délai" if seance.echeance_depot < aujourd_hui else "En attente", None)
    if compte_rendu.depose_le > seance.echeance_depot:
        return ("Hors délai", compte_rendu.depose_le.isoformat())
    return ("Déposé", compte_rendu.depose_le.isoformat())


def composer_seance(seance: Seance, aujourd_hui: date) -> dict:
    etat, date_depot = _etat_depot(seance, aujourd_hui)
    return {
        "id": seance.pk,
        "reference": seance.reference,
        "type": TYPES_SEANCE_VERS_FRONT[seance.type_seance],
        "intitule": seance.intitule,
        "date": seance.date_seance.isoformat(),
        "president": seance.president.nom_complet if seance.president else "",
        "participants": getattr(seance, "_participants", 0),
        "depot": etat,
        "dateDepot": date_depot,
        "echeanceDepot": seance.echeance_depot.isoformat(),
        "decisionsIssues": getattr(seance, "_decisions", 0),
        "structure": seance.structure.code,
    }


def _seances_enrichies(requete: QuerySet) -> QuerySet:
    return (
        requete.select_related("president", "structure")
        .prefetch_related("documents")
        .annotate(
            _participants=Count("participants", distinct=True),
            _decisions=Count(
                "engagements",
                filter=Q(engagements__invalide_le__isnull=True),
                distinct=True,
            ),
        )
    )


def registre_seances(utilisateur: Utilisateur, *, type_seance: str = "") -> dict:
    """Le registre des reunions et rapports dont la DSR tient le secretariat."""
    aujourd_hui = date.today()
    requete = _seances_enrichies(_seances_visibles(utilisateur)).order_by("-date_seance")

    if not est_tout(type_seance):
        requete = requete.filter(type_seance=_code_type_seance(type_seance))

    lignes = [composer_seance(seance, aujourd_hui) for seance in requete]
    return {
        "seances": lignes,
        "compteurs": _compteurs_seances(lignes),
        "total": len(lignes),
    }


def _code_type_seance(libelle: str) -> str:
    for code, affiche in TYPES_SEANCE_VERS_FRONT.items():
        if affiche == libelle:
            return code
    return "__inconnu__"


def _compteurs_seances(lignes: list[dict]) -> list[dict]:
    hors_delai = sum(1 for ligne in lignes if ligne["depot"] == "Hors délai")
    attendus = sum(1 for ligne in lignes if ligne["depot"] == "En attente")
    decisions = sum(ligne["decisionsIssues"] for ligne in lignes)
    return [
        {
            "libelle": "Séances tenues",
            "valeur": len(lignes),
            "note": "dans votre périmètre",
            "feu": "inconnu",
        },
        {
            "libelle": "Comptes rendus attendus",
            "valeur": attendus,
            "note": "délai non échu",
            "feu": "orange" if attendus else "vert",
        },
        {
            "libelle": "Hors délai",
            "valeur": hors_delai,
            "note": "échéance de dépôt dépassée",
            "feu": "rouge" if hors_delai else "vert",
        },
        {
            "libelle": "Décisions issues",
            "valeur": decisions,
            "note": "à suivre jusqu'à exécution",
            "feu": "inconnu",
        },
    ]


def fiche_seance(utilisateur: Utilisateur, seance_id: int) -> dict:
    """La fiche complete d'une seance. **404 hors perimetre** — decision D5."""
    aujourd_hui = date.today()
    seance = _seances_enrichies(_seances_visibles(utilisateur)).filter(pk=seance_id).first()
    if seance is None:
        raise HorsPerimetre("Seance introuvable.")

    engagements = list(_enrichis(seance.engagements.filter(invalide_le__isnull=True)))
    etats = _etats(engagements)

    detail = composer_seance(seance, aujourd_hui)
    detail.update(
        {
            "ordreDuJour": [
                {
                    "id": point.pk,
                    "rang": point.rang,
                    "point": point.point,
                    "rapporteur": point.rapporteur.nom_complet if point.rapporteur else "",
                }
                for point in seance.points.select_related("rapporteur").order_by("rang")
            ],
            "documents": _documents(seance),
            "presents": [
                {
                    "nom": participant.utilisateur.nom_complet,
                    "initiales": participant.utilisateur.initiales,
                    "poste": participant.utilisateur.poste.libelle
                    if participant.utilisateur.poste
                    else "",
                    "present": participant.present,
                }
                for participant in seance.participants.select_related("utilisateur__poste")
            ],
            "decisions": [
                {
                    "id": engagement.pk,
                    "reference": engagement.reference or "",
                    "objet": engagement.objet,
                    "etat": ETATS_VERS_FRONT[
                        etats[engagement.pk].etat_affiche if engagement.pk in etats else "a_lancer"
                    ],
                }
                for engagement in engagements
            ],
        }
    )
    return detail


def _documents(seance: Seance) -> list[dict]:
    return [
        {
            "id": document.pk,
            "nature": NATURES_DOCUMENT_VERS_FRONT[document.nature],
            "libelle": document.libelle,
            "depose": document.depose_le is not None,
            "dateDepot": document.depose_le.isoformat() if document.depose_le else None,
            "poids": _poids(document.piece_jointe.taille_octets) if document.piece_jointe else None,
            "deposePar": document.depose_par.nom_complet if document.depose_par else None,
        }
        for document in seance.documents.select_related("piece_jointe", "depose_par")
    ]


def _poids(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo"


# =====================================================================
#  Disponibilite
# =====================================================================


def composer_disponibilite(
    absence: Disponibilite, aujourd_hui: date, *, par_tete: bool = False
) -> dict:
    """
    Une ligne du registre des absences.

    **Le feu ne juge pas l'absence, il juge la suppleance.** Une mission de trois
    semaines avec interimaire designe est verte ; deux jours sans interimaire,
    en cours, sont rouges — c'est ce qui arrete les dossiers d'une direction.
    """
    en_cours = absence.du <= aujourd_hui <= absence.au
    sans_interim = absence.interimaire is None
    return {
        "id": absence.pk,
        "responsable": absence.utilisateur.nom_complet,
        "initiales": absence.utilisateur.initiales,
        "poste": absence.utilisateur.poste.libelle if absence.utilisateur.poste else "",
        # La tete de structure pour qui consolide, le service pour un
        # directeur : au-dessus d'un directeur, la sous-structure n'existe pas,
        # mais lui doit retrouver le sien. Voir `noyau/organisation/tete.py`.
        "structure": _structure_affichee(absence.utilisateur, par_tete=par_tete),
        "type": TYPES_ABSENCE_VERS_FRONT[absence.type_absence],
        "du": absence.du.isoformat(),
        "au": absence.au.isoformat(),
        # Bornes comprises : du lundi au vendredi fait cinq jours, pas quatre.
        "jours": (absence.au - absence.du).days + 1,
        "interimaire": absence.interimaire.nom_complet if absence.interimaire else None,
        "interimaireInitiales": absence.interimaire.initiales if absence.interimaire else None,
        "feu": ("rouge" if en_cours else "orange") if sans_interim else "vert",
        "enCours": en_cours,
        "saisiPar": absence.saisi_par.nom_complet,
    }


def _structure_affichee(agent: Utilisateur, *, par_tete: bool) -> str:
    """
    Le code de structure porte par une ligne de tableau.

    Un seul point de passage : recopie a la main, la regle serait oubliee au
    prochain ecran, et le Directeur general y verrait reapparaitre les
    quarante-six cellules du Port.
    """
    if agent.structure is None:
        return ""
    if not par_tete:
        return agent.structure.code
    tete = tete_de(agent.structure)
    return tete.code if tete is not None else agent.structure.code


def bilan_disponibilite(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict | None:
    """
    Combien d'agents sont a leur poste aujourd'hui, et pourquoi les autres n'y
    sont pas.

    Le registre repond « qui est absent, du quand au quand » ; ce bilan-ci
    repond « quelle part de l'effectif manque ce matin ». C'est la question
    d'une vue d'ensemble, et elle ne se lit pas dans une liste de deux cents
    lignes.

    **Les presents font une part comme les autres.** Un anneau qui ne montrerait
    que les absents dirait la meme chose quel que soit l'effectif : trois
    absences pesent autrement sur une cellule de cinq agents que sur une
    direction de quatre-vingts.

    `None` quand le perimetre ne rend aucun agent — la session n'a rien a lire,
    et un bilan a zero ferait croire a un Port desert (ADR 011).
    """
    jour = aujourd_hui or date.today()

    effectif = restreindre(
        Utilisateur.objects.actifs(),
        utilisateur,
        champ_structure="structure",
        champ_agent="id",
    ).count()
    if not effectif:
        return None

    absences = _disponibilites_visibles(utilisateur).filter(du__lte=jour, au__gte=jour)
    par_motif: dict[str, int] = {}
    sans_interim = 0
    absents = 0
    for absence in absences:
        absents += 1
        libelle = TYPES_ABSENCE_VERS_FRONT[absence.type_absence]
        par_motif[libelle] = par_motif.get(libelle, 0) + 1
        if absence.interimaire_id is None:
            sans_interim += 1

    # Un agent absent deux fois le meme jour compterait deux fois : le socle ne
    # l'interdit pas, et l'effectif present deviendrait negatif. On borne.
    presents = max(effectif - absents, 0)

    return {
        "aLaDate": jour.isoformat(),
        "effectif": effectif,
        "absents": absents,
        "presents": presents,
        "tauxPresence": round(presents / effectif * 100, 1),
        "sansInterim": sans_interim,
        "parts": [
            {"libelle": "Présents", "valeur": presents},
            *(
                {"libelle": libelle, "valeur": nombre}
                for libelle, nombre in sorted(par_motif.items(), key=lambda part: -part[1])
            ),
        ],
    }


def registre_disponibilites(
    utilisateur: Utilisateur, *, filtre: str = "", structure: str = ""
) -> dict:
    """
    Le registre des absences, borne au perimetre, filtre par libelle affiche.

    Le filtre arrive dans le vocabulaire de l'ecran — « Sans interim », « Congé
    annuel » — comme pour les instances et les types de seance. Traduire ici
    plutot que dans le front garde le vocabulaire metier d'un seul cote.

    `structure` filtre par **tete** pour qui consolide — le code d'une
    direction, jamais d'un service. Le Directeur general lit son Port par
    directions ; lui offrir un filtre sur les quarante-six cellules serait lui
    rendre la distinction qu'on vient de lui retirer.
    """
    aujourd_hui = date.today()
    par_tete = consolide(utilisateur)
    requete = _disponibilites_visibles(utilisateur).select_related(
        "utilisateur__poste", "utilisateur__structure__tete", "interimaire", "saisi_par"
    )
    if structure:
        champ = "utilisateur__structure__tete__code" if par_tete else "utilisateur__structure__code"
        requete = requete.filter(**{champ: structure})
    lignes = [
        composer_disponibilite(absence, aujourd_hui, par_tete=par_tete) for absence in requete
    ]

    sans_interim = sum(1 for ligne in lignes if ligne["enCours"] and ligne["interimaire"] is None)

    if not est_tout(filtre):
        lignes = _filtrer_disponibilites(lignes, filtre, aujourd_hui)

    en_cours = sum(1 for ligne in lignes if ligne["enCours"])
    return {
        "disponibilites": lignes,
        "compteurs": [
            {
                "libelle": "Absences en cours",
                "valeur": en_cours,
                "note": "à la date du jour",
                "feu": "orange" if en_cours else "vert",
            },
            {
                "libelle": "Sans intérimaire",
                "valeur": sans_interim,
                "note": "les dossiers s'arrêtent",
                "feu": "rouge" if sans_interim else "vert",
            },
            {
                "libelle": "Absences suivies",
                "valeur": len(lignes),
                "note": "dans votre périmètre",
                "feu": "inconnu",
            },
        ],
        "sansInterim": sans_interim,
    }


def _filtrer_disponibilites(lignes: list[dict], libelle: str, aujourd_hui: date) -> list[dict]:
    """
    Deux familles de filtres derriere une seule barre.

    « En cours » et « Sans interim » portent sur l'etat de la suppleance ; les
    autres libelles sont des types d'absence (`TYPES_ABSENCE_VERS_FRONT`), que
    la ligne composee porte deja dans sa cle `type`. Un libelle inconnu ne
    renvoie rien plutot que tout — meme regle que `_code_instance()`.
    """
    if libelle == "En cours":
        return [ligne for ligne in lignes if ligne["enCours"]]
    if libelle == "Sans intérim":
        # Toutes les absences sans suppleant, pas seulement celles en cours :
        # une mission qui commence lundi sans interimaire se prepare avant.
        return [ligne for ligne in lignes if ligne["interimaire"] is None]
    if libelle == "À venir":
        return [ligne for ligne in lignes if ligne["du"] > aujourd_hui.isoformat()]
    if libelle in TYPES_ABSENCE_VERS_FRONT.values():
        return [ligne for ligne in lignes if ligne["type"] == libelle]
    return []


# =====================================================================
#  Filiales et succursales
# =====================================================================


def suivi_filiales(utilisateur: Utilisateur) -> dict:
    """
    Les deux moities de l'ecran : l'amont — le dossier est-il pret — et l'aval
    — la prescription est-elle suivie d'effet.

    Les organes de gestion ne sont **pas restreints au perimetre** : le
    referentiel des filiales du PAD n'est pas une donnee de structure, et le
    masquer par direction n'aurait protege rien. Les prescriptions, elles, le
    sont : elles chargent des structures internes.
    """
    prescriptions_par_organe = _prescriptions_par_organe(utilisateur)

    organes = []
    for organe in OrganeGestion.objects.select_related("entite_externe").order_by(
        "entite_externe__sigle", "organe"
    ):
        compte = prescriptions_par_organe.get(organe.pk, {"total": 0, "executees": 0, "retard": 0})
        organes.append(
            {
                "id": organe.pk,
                "entite": organe.entite_externe.libelle,
                "sigle": organe.entite_externe.sigle,
                "nature": NATURES_ENTITE_VERS_FRONT[organe.entite_externe.nature],
                "organe": ORGANES_VERS_FRONT[organe.organe],
                "prochaineSession": organe.prochaine_session.isoformat()
                if organe.prochaine_session
                else "",
                "etatPreparation": PREPARATIONS_VERS_FRONT[organe.etat_preparation],
                "documentsAttendus": organe.documents_attendus,
                "documentsRecus": organe.documents_recus,
                "feu": _feu_preparation(organe),
                "prescriptionsTotal": compte["total"],
                "prescriptionsExecutees": compte["executees"],
                "prescriptionsEnRetard": compte["retard"],
            }
        )

    engagements = list(
        _enrichis(
            _engagements_visibles(utilisateur).filter(origine=Engagement.ORGANE_FILIALE)
        ).order_by("-date_engagement")
    )
    etats = _etats(engagements)
    prescriptions = [_composer_prescription(e, etats.get(e.pk)) for e in engagements]

    en_retard = sum(1 for ligne in prescriptions if ligne["etat"] == "En retard")
    dossiers = sum(1 for ligne in organes if ligne["etatPreparation"] != "Tenue")
    return {
        "organes": organes,
        "prescriptions": prescriptions,
        "compteurs": [
            {
                "libelle": "Sessions à préparer",
                "valeur": dossiers,
                "note": "dossiers non transmis ou en cours",
                "feu": "orange" if dossiers else "vert",
            },
            {
                "libelle": "Prescriptions suivies",
                "valeur": len(prescriptions),
                "note": "dans votre périmètre",
                "feu": "inconnu",
            },
            {
                "libelle": "En retard",
                "valeur": en_retard,
                "note": "échéance dépassée",
                "feu": "rouge" if en_retard else "vert",
            },
        ],
    }


def _feu_preparation(organe: OrganeGestion) -> str:
    """
    La preparation se juge sur les pieces reunies, pas sur l'etat declare : un
    dossier annonce « en cours » sans aucun document n'est pas commence.
    """
    if organe.etat_preparation == "tenue":
        return "vert"
    if organe.documents_attendus == 0:
        return "inconnu"
    return feu(100 * organe.documents_recus / organe.documents_attendus)


def _prescriptions_par_organe(utilisateur: Utilisateur) -> dict[int, dict[str, int]]:
    engagements = list(
        _engagements_visibles(utilisateur)
        .filter(origine=Engagement.ORGANE_FILIALE, organe_gestion__isnull=False)
        .only("id", "organe_gestion_id")
    )
    etats = _etats(engagements)
    comptes: dict[int, dict[str, int]] = {}
    for engagement in engagements:
        assert engagement.organe_gestion_id is not None
        compte = comptes.setdefault(
            engagement.organe_gestion_id, {"total": 0, "executees": 0, "retard": 0}
        )
        compte["total"] += 1
        etat = etats.get(engagement.pk)
        if etat and etat.etat_affiche == "execute":
            compte["executees"] += 1
        if etat and etat.etat_affiche == "en_retard":
            compte["retard"] += 1
    return comptes


def _composer_prescription(engagement: Engagement, etat: VueEngagementEtat | None) -> dict:
    code_etat = etat.etat_affiche if etat else "a_lancer"
    avancement = float(etat.avancement if etat else engagement.avancement)
    organe = engagement.organe_gestion
    return {
        "id": engagement.pk,
        "reference": engagement.reference or "",
        "entite": organe.entite_externe.sigle if organe else "",
        "objet": engagement.objet,
        "sessionOrigine": f"{ORGANES_VERS_FRONT[organe.organe]} du "
        f"{_en_toutes_lettres(engagement.date_engagement)}"
        if organe
        else "",
        "echeance": engagement.echeance.isoformat() if engagement.echeance else "",
        "avancement": avancement,
        "etat": ETATS_VERS_FRONT[code_etat],
        "feu": _feu_engagement(code_etat, avancement),
    }


# =====================================================================
#  Representations exterieures
# =====================================================================


def suivi_representations(utilisateur: Utilisateur) -> dict:
    """
    Deux objets distincts : le **mandat** — qui nous represente, jusqu'a quand,
    avec quelle assiduite — et la **recommandation**, qui engage une structure
    interne exactement comme une decision d'instance.
    """
    aujourd_hui = date.today()
    representations = [
        _composer_representation(mandat, aujourd_hui)
        for mandat in Representation.objects.filter(invalide_le__isnull=True)
        .select_related("organisation_externe", "representant", "suppleant")
        .order_by("organisation_externe__sigle")
    ]

    engagements = list(
        _enrichis(
            _engagements_visibles(utilisateur).filter(origine=Engagement.ORGANISATION_EXTERNE)
        ).order_by("-date_engagement")
    )
    etats = _etats(engagements)
    recommandations = [_composer_recommandation(e, etats.get(e.pk)) for e in engagements]

    expirants = sum(1 for ligne in representations if ligne["feu"] == "rouge")
    en_retard = sum(1 for ligne in recommandations if ligne["etat"] == "En retard")
    return {
        "representations": representations,
        "recommandations": recommandations,
        "compteurs": [
            {
                "libelle": "Mandats en cours",
                "valeur": len(representations),
                "note": "organisations où le PAD siège",
                "feu": "inconnu",
            },
            {
                "libelle": "Assiduité faible",
                "valeur": expirants,
                "note": "moins de 60 % de participation",
                "feu": "rouge" if expirants else "vert",
            },
            {
                "libelle": "Recommandations en retard",
                "valeur": en_retard,
                "note": "échéance dépassée",
                "feu": "rouge" if en_retard else "vert",
            },
        ],
    }


def _composer_representation(mandat: Representation, aujourd_hui: date) -> dict:
    """
    Le taux de participation vaut `None` tant qu'aucune reunion n'a ete tenue.

    Zero sur zero n'est pas zero pour cent : afficher 0 % ferait paraitre
    defaillant un mandat qui vient d'etre confie.
    """
    taux = (
        round(100 * mandat.reunions_participees / mandat.reunions_tenues, 2)
        if mandat.reunions_tenues
        else None
    )
    return {
        "id": mandat.pk,
        "organisation": mandat.organisation_externe.libelle,
        "sigle": mandat.organisation_externe.sigle,
        "nature": NATURES_ORGANISATION_VERS_FRONT[mandat.organisation_externe.nature],
        "representant": mandat.representant.nom_complet,
        "initiales": mandat.representant.initiales,
        "suppleant": mandat.suppleant.nom_complet if mandat.suppleant else None,
        "mandatDu": mandat.mandat_du.isoformat(),
        "mandatAu": mandat.mandat_au.isoformat(),
        "reunionsTenues": mandat.reunions_tenues,
        "reunionsParticipees": mandat.reunions_participees,
        "tauxParticipation": taux or 0.0,
        # Un mandat expire est rouge quel que soit le taux : nul ne represente
        # plus le PAD, et c'est plus grave qu'une assiduite mediocre.
        "feu": "rouge" if mandat.mandat_au < aujourd_hui else feu(taux),
        "apport": mandat.apport,
    }


def _composer_recommandation(engagement: Engagement, etat: VueEngagementEtat | None) -> dict:
    code_etat = etat.etat_affiche if etat else "a_lancer"
    avancement = float(etat.avancement if etat else engagement.avancement)
    pilote = next(
        (c for c in engagement.structures.all() if c.pilote),
        None,
    )
    return {
        "id": engagement.pk,
        "reference": engagement.reference or "",
        "organisation": engagement.organisation_externe.sigle
        if engagement.organisation_externe
        else "",
        "objet": engagement.objet,
        "emiseLe": engagement.date_engagement.isoformat(),
        "echeance": engagement.echeance.isoformat() if engagement.echeance else None,
        "structurePilote": pilote.structure.code if pilote else "",
        "avancement": avancement,
        "etat": ETATS_VERS_FRONT[code_etat],
        "feu": _feu_engagement(code_etat, avancement),
    }


# =====================================================================
#  Planning des conges
# =====================================================================


def planning_conges(utilisateur: Utilisateur, *, annee: int) -> dict:
    """
    Le projet de planning annuel — §3.3.

    **A ne pas confondre avec le registre de disponibilite** : celui-ci
    enregistre une absence decidee, celui-la arbitre des souhaits avant qu'ils
    ne le deviennent.

    Le conflit est ce que l'ecran sert a voir : deux responsables d'une meme
    structure absents en meme temps privent la direction de sa ligne
    hierarchique. Il se calcule ici et ne se stocke pas — il change des qu'une
    periode bouge.
    """
    droits = (
        restreindre(
            CongeDroit.objects.filter(annee=annee),
            utilisateur,
            champ_structure="utilisateur__structure",
            champ_agent="utilisateur_id",
        )
        .select_related("utilisateur__poste", "utilisateur__structure__tete")
        .prefetch_related("periodes")
        .order_by("utilisateur__nom")
    )

    lignes = [_composer_ligne_conges(droit) for droit in droits]
    sans_planning = sum(1 for ligne in lignes if not ligne["periodes"])
    conflits = _conflits(droits)
    return {
        "annee": annee,
        "lignes": lignes,
        "conflits": conflits,
        "compteurs": [
            {
                "libelle": "Agents suivis",
                "valeur": len(lignes),
                "note": f"exercice {annee}",
                "feu": "inconnu",
            },
            {
                "libelle": "Sans planning",
                "valeur": sans_planning,
                "note": "aucune période déclarée",
                "feu": "orange" if sans_planning else "vert",
            },
            {
                "libelle": "Conflits détectés",
                "valeur": len(conflits),
                "note": "même direction, mêmes dates",
                "feu": "rouge" if conflits else "vert",
            },
        ],
    }


def _composer_ligne_conges(droit: CongeDroit) -> dict:
    """
    Le solde ne compte que les periodes **validees ou arbitrees**.

    Un souhait n'entame pas un droit : le decompter ferait paraitre epuise un
    solde que rien n'a encore engage, et un report le rendrait faux dans l'autre
    sens.
    """
    periodes = list(droit.periodes.all())
    planifies = sum(
        (periode.au - periode.du).days + 1
        for periode in periodes
        if periode.etat in ("arbitre", "valide")
    )
    solde = droit.droits_jours - planifies
    return {
        "id": droit.pk,
        "responsable": droit.utilisateur.nom_complet,
        "initiales": droit.utilisateur.initiales,
        "poste": droit.utilisateur.poste.libelle if droit.utilisateur.poste else "",
        "structure": droit.utilisateur.structure.code if droit.utilisateur.structure else "",
        "droits": droit.droits_jours,
        "planifies": planifies,
        "solde": solde,
        "periodes": [
            {
                "id": periode.pk,
                "du": periode.du.isoformat(),
                "au": periode.au.isoformat(),
                "jours": (periode.au - periode.du).days + 1,
                "etat": ETATS_CONGE_VERS_FRONT[periode.etat],
            }
            for periode in sorted(periodes, key=lambda p: p.du)
        ],
        # Un solde negatif est une erreur d'arbitrage, pas une alerte de gestion.
        "feu": "rouge" if solde < 0 else ("orange" if not periodes else "vert"),
    }


def _conflits(droits: QuerySet) -> list[dict]:
    """
    Deux agents d'une meme **tete de structure** absents sur des periodes qui
    se recoupent.

    Le regroupement s'est elargi de la structure a sa tete le 31 aout 2026 : a
    structure strictement egale, deux chefs de departements freres partant la
    meme semaine ne declenchaient rien, alors que leur direction se retrouve
    sans encadrement. C'est exactement ce que l'ecran sert a voir.

    Les souhaits sont inclus : c'est **avant** l'arbitrage que le conflit doit
    se voir, sinon l'ecran ne sert qu'a constater.

    Se calcule, ne se stocke pas : il change des qu'une periode bouge.
    """
    par_tete: dict[str, list[tuple[str, date, date]]] = {}
    for droit in droits:
        structure = droit.utilisateur.structure
        tete = tete_de(structure) if structure is not None else None
        # Un agent sans structure — ou hors de la ligne hierarchique — ne peut
        # entrer en conflit avec personne : le regrouper sous une clef vide
        # produirait un faux conflit entre tous les comptes hors organigramme.
        if tete is None:
            continue
        for periode in droit.periodes.all():
            if periode.etat == "reporte":
                continue
            par_tete.setdefault(tete.code, []).append(
                (droit.utilisateur.nom_complet, periode.du, periode.au)
            )

    conflits = []
    for structure, absences in par_tete.items():
        for i, (nom_a, du_a, au_a) in enumerate(absences):
            for nom_b, du_b, au_b in absences[i + 1 :]:
                if nom_a == nom_b or du_a > au_b or du_b > au_a:
                    continue
                debut, fin = max(du_a, du_b), min(au_a, au_b)
                conflits.append(
                    {
                        "periode": f"du {_en_toutes_lettres(debut)} au {_en_toutes_lettres(fin)}",
                        "structure": structure,
                        "responsables": sorted({nom_a, nom_b}),
                    }
                )
    return conflits


# =====================================================================
#  Tableau de bord
# =====================================================================


def tableau_de_bord(utilisateur: Utilisateur) -> dict:
    """
    Les trois registres en une seule vue : ce qui est en retard, ce qui manque,
    qui est absent sans suppleance.

    **Il agrege a la volee et non depuis `agregat_gouvernance_jour`.** L'agregat
    sert l'historique et les courbes ; cet ecran doit refleter la relance partie
    il y a dix minutes. Les deux ne se contredisent pas : ils repondent a deux
    questions, « ou en est-on aujourd'hui » et « comment cela a-t-il evolue ».
    """
    aujourd_hui = date.today()

    engagements = list(_enrichis(_engagements_visibles(utilisateur)))
    etats = _etats(engagements)
    lignes = [
        composer_engagement(e, etats.get(e.pk))
        for e in engagements
        if e.origine == Engagement.INSTANCE
    ]

    a_relancer = sorted(
        # « En retard ni relancée » : une decision deja relancee mais encore dans
        # les temps appelle une action, meme si son echeance n'est pas passee.
        # C'est ce que la carte annonce, et c'est le sens de la relance.
        (ligne for ligne in lignes if ligne["etat"] == "En retard" or ligne["relances"] > 0),
        # Les retards d'abord ; puis les moins avancees, puis les plus relancees :
        # une decision a 10 % relancee trois fois est le vrai signal, pas celle a 95 %.
        key=lambda ligne: (
            0 if ligne["etat"] == "En retard" else 1,
            ligne["avancement"],
            -ligne["relances"],
        ),
    )

    seances = _seances_enrichies(_seances_visibles(utilisateur))
    depots = [
        composer_seance(seance, aujourd_hui)
        for seance in seances
        if _etat_depot(seance, aujourd_hui)[0] != "Déposé"
    ]

    absences = [
        composer_disponibilite(absence, aujourd_hui, par_tete=consolide(utilisateur))
        for absence in _disponibilites_visibles(utilisateur).select_related(
            "utilisateur__poste", "utilisateur__structure__tete", "interimaire", "saisi_par"
        )
    ]
    sans_interim = [
        ligne for ligne in absences if ligne["enCours"] and ligne["interimaire"] is None
    ]

    # Le compteur compte les retards, pas la liste : « aRelancer » y ajoute les
    # decisions relancees encore dans les temps, qui ne sont pas en retard.
    en_retard = sum(1 for ligne in lignes if ligne["etat"] == "En retard")
    hors_delai = sum(1 for ligne in depots if ligne["depot"] == "Hors délai")
    return {
        "compteurs": [
            {
                "libelle": "Décisions à suivre",
                "valeur": len(lignes),
                "note": "dans votre périmètre",
                "feu": "inconnu",
            },
            {
                "libelle": "En retard",
                "valeur": en_retard,
                "note": "échéance dépassée",
                "feu": "rouge" if en_retard else "vert",
            },
            {
                "libelle": "Dépôts hors délai",
                "valeur": hors_delai,
                "note": "comptes rendus attendus",
                "feu": "rouge" if hors_delai else "vert",
            },
            {
                "libelle": "Absences sans intérim",
                "valeur": len(sans_interim),
                "note": "les dossiers s'arrêtent",
                "feu": "rouge" if sans_interim else "vert",
            },
        ],
        "aRelancer": a_relancer,
        "depotsEnSouffrance": depots,
        "absencesSansInterim": sans_interim,
        "parInstance": _par_instance(lignes),
    }


def _par_instance(lignes: list[dict]) -> list[dict]:
    """
    La repartition de la barre du haut.

    Les quatre instances sont **toujours renvoyees**, meme a zero : une barre
    dont les segments apparaissent et disparaissent selon les donnees se relit
    mal d'un jour sur l'autre.
    """
    return [
        {
            "instance": libelle,
            "total": sum(1 for ligne in lignes if ligne["instance"] == libelle),
            "enRetard": sum(
                1
                for ligne in lignes
                if ligne["instance"] == libelle and ligne["etat"] == "En retard"
            ),
        }
        for libelle in INSTANCES_VERS_FRONT.values()
    ]

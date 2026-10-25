"""
Ce qui se lit du pilier activites.

**Toute requete part de `_visibles()`.** Aucune vue ne construit son filtre :
un filtre recopie a la main est un filtre qui sera oublie au prochain endpoint,
et l'oubli ne produit aucune erreur — il montre a un agent le plan du voisin.

La structure porteuse d'une activite vient du plan (`plan__structure`), jamais
d'une colonne de l'activite : la dupliquer ferait exister deux verites, et c'est
la visibilite qui en depend.

`champ_agent` vaut `responsable_id` : en portee `propre`, un agent ne voit que
les activites dont il est responsable. L'omettre degraderait silencieusement la
restriction au niveau de la structure — `restreindre()` leve plutot que de
laisser passer.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Count, F, Prefetch, Q, QuerySet

from activite import regles
from activite.modeles import Activite, ActiviteStructure, Obligation, PlanActions
from noyau.feu import feu
from noyau.filtres import est_tout
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.perimetre.portee import porte_une_structure, restreindre, structures_visibles

#: Codes de base vers libelles du front. Traduits **une seule fois**, ici.
ETATS_VERS_FRONT = {
    regles.PROGRAMMEE: "Programmée",
    regles.EN_COURS: "En cours",
    regles.REALISEE: "Réalisée",
    regles.EN_RETARD: "En retard",
    regles.SUSPENDUE: "Suspendue",
}

STATUTS_PLAN_VERS_FRONT = {
    PlanActions.BROUILLON: "Brouillon",
    PlanActions.SOUMIS: "Soumis au contrôle de gestion",
    PlanActions.VALIDE: "Validé",
    PlanActions.RETOURNE: "Retourné",
}

NATURES_VERS_FRONT = {
    "rapport_mensuel": "Rapport mensuel d'activité",
    "proces_verbal": "Procès-verbal de réunion",
    "rapport_sectoriel": "Rapport sectoriel",
}


def _visibles(utilisateur: Utilisateur) -> QuerySet:
    """
    Les activites que l'utilisateur peut voir. Le point de passage unique.

    **Deux chemins de structure et non un** : la porteuse, qui tient l'activite
    a son plan, et les structures associees, qui en repondent sans l'inscrire
    au leur (ADR 047). Une co-responsabilite invisible au registre de la
    structure co-responsable n'aurait aucun effet.

    Le rattachement retire (`invalide_le`) ne donne plus rien a voir : la
    structure qui n'en repond plus n'a pas a garder l'acces.
    """
    return restreindre(
        Activite.objects.filter(invalide_le__isnull=True),
        utilisateur,
        champ_structure=(
            "plan__structure",
            (
                "structures_associees__structure",
                {"structures_associees__invalide_le__isnull": True},
            ),
        ),
        champ_agent="responsable_id",
    )


def _enrichies(requete: QuerySet) -> QuerySet:
    """Les jointures et comptages dont chaque ligne du registre a besoin."""
    return (
        requete.select_related("plan__structure", "axe_strategique", "responsable")
        .prefetch_related(
            Prefetch(
                "structures_associees",
                queryset=ActiviteStructure.objects.filter(invalide_le__isnull=True)
                .select_related("structure")
                .order_by("structure__code"),
                to_attr="_associees",
            )
        )
        .annotate(
            _taches_total=Count(
                "taches", filter=Q(taches__invalide_le__isnull=True), distinct=True
            ),
            # Faite = sa valeur retenue atteint sa part (ADR 049). Retenue et
            # non declaree : une tache que la DSR conteste n'est pas faite.
            _taches_faites=Count(
                "taches",
                filter=Q(
                    taches__invalide_le__isnull=True,
                    taches__valeur_retenue__gte=F("taches__valeur_prevue"),
                ),
                distinct=True,
            ),
            _instructions=Count(
                "instructions",
                filter=Q(
                    instructions__invalide_le__isnull=True, instructions__levee_le__isnull=True
                ),
                distinct=True,
            ),
        )
    )


def est_critique(activite, *, aujourd_hui: date | None = None) -> bool:
    """
    §20. En retard **et** portant une contrainte echue — instruction non levee
    ou tache non realisee dont le dernier mois est passe (ADR 049 : la fin de
    la periode d'une tache tient lieu d'echeance). Meme definition que la vue
    `v_activite_etat`.

    Le retard seul ne suffit pas : sans cette seconde condition la moitie du
    plan serait critique et le mot ne trierait plus rien. La regle est une
    hypothese (`activite.criticite_exige_contrainte`, A3) ; ce qui est acte,
    c'est la definition du retard qu'elle utilise.
    """
    jour = aujourd_hui or date.today()
    if not regles.est_en_retard(activite, aujourd_hui=jour):
        return False
    return (
        activite.instructions.filter(
            levee_le__isnull=True, invalide_le__isnull=True, echeance__lt=jour
        ).exists()
        or activite.taches.filter(
            invalide_le__isnull=True,
            date_fin__lt=jour,
            valeur_retenue__lt=F("valeur_prevue"),
        ).exists()
    )


def composer_ligne(activite, *, aujourd_hui: date | None = None) -> dict:
    """
    Une ligne de registre.

    Les comptages viennent des annotations quand elles existent — sur un
    registre de deux cents activites, les recompter ligne a ligne ferait six
    cents requetes.
    """
    jour = aujourd_hui or date.today()
    structure = activite.plan.structure
    attendu = regles.avancement_attendu(activite, aujourd_hui=jour) or Decimal(0)
    # Le taux **retenu**, jamais le declare : quand la DSR a recalibre, c'est
    # elle qui fait foi (ADR 030). La colonne est generee par le moteur.
    avancement = float(activite.avancement_retenu)

    # Le point focal est facultatif depuis l'ADR 047 : ce qui repond de
    # l'activite, ce sont les structures.
    focal = activite.responsable

    return {
        "id": activite.pk,
        "reference": activite.code,
        "intitule": activite.intitule,
        "axe": activite.axe_strategique.libelle_court,
        "structureSigle": structure.code,
        "structureLibelle": structure.libelle,
        "structuresAssociees": _structures_associees(activite),
        "responsable": focal.nom_complet if focal else None,
        "responsableId": activite.responsable_id,
        "initiales": focal.initiales if focal else None,
        "debut": activite.date_debut.isoformat(),
        "fin": activite.date_fin.isoformat(),
        "etat": ETATS_VERS_FRONT[regles.etat_affiche(activite, aujourd_hui=jour)],
        "avancement": avancement,
        "avancementAttendu": float(attendu),
        "feu": feu(avancement),
        "tachesFaites": getattr(activite, "_taches_faites", None)
        if hasattr(activite, "_taches_faites")
        else activite.taches.filter(
            invalide_le__isnull=True, valeur_retenue__gte=F("valeur_prevue")
        ).count(),
        "tachesTotal": getattr(activite, "_taches_total", None)
        if hasattr(activite, "_taches_total")
        else activite.taches.filter(invalide_le__isnull=True).count(),
        "instructions": getattr(activite, "_instructions", None)
        if hasattr(activite, "_instructions")
        else activite.instructions.filter(invalide_le__isnull=True, levee_le__isnull=True).count(),
        "critique": est_critique(activite, aujourd_hui=jour),
    }


def _structures_associees(activite) -> list[dict]:
    """
    Les structures qui repondent de l'activite en sus de la porteuse — ADR 047.

    Le prefetch de `_enrichies()` evite une requete par ligne de registre ;
    faute de lui — une activite chargee seule —, on interroge la table.
    """
    rattachements = getattr(activite, "_associees", None)
    if rattachements is None:
        rattachements = list(
            activite.structures_associees.filter(invalide_le__isnull=True)
            .select_related("structure")
            .order_by("structure__code")
        )
    return [{"sigle": r.structure.code, "libelle": r.structure.libelle} for r in rattachements]


def registre(utilisateur: Utilisateur, *, structure: str = "", etat: str = "") -> dict:
    """
    Le registre des activites, filtre au perimetre puis aux criteres de l'agent.

    L'ordre compte : le perimetre borne, les filtres affinent. L'inverse
    laisserait un filtre vide montrer plus que le perimetre.
    """
    requete = _enrichies(_visibles(utilisateur))
    if not est_tout(structure):
        # Porteuse **ou** associee : le filtre du registre suit la meme
        # definition que la visibilite, sinon choisir sa propre structure
        # masquerait les activites dont on est co-responsable (ADR 047).
        requete = requete.filter(
            Q(plan__structure__code=structure)
            | Q(
                structures_associees__structure__code=structure,
                structures_associees__invalide_le__isnull=True,
            )
        ).distinct()

    lignes = [composer_ligne(a) for a in requete]

    if not est_tout(etat):
        lignes = [ligne for ligne in lignes if ligne["etat"] == etat]

    return {
        "activites": lignes,
        "compteurs": _compteurs_registre(lignes),
        "total": len(lignes),
        # Les structures de ce que l'agent voit, pas toutes celles qui
        # existent : le selecteur ne doit pas reveler l'organigramme. Les
        # associees y figurent — sans elles, filtrer sur sa propre structure
        # serait impossible a qui n'en porte aucune au plan.
        "structures": sorted(
            {ligne["structureSigle"] for ligne in lignes}
            | {s["sigle"] for ligne in lignes for s in ligne["structuresAssociees"]}
        ),
    }


def _compteurs_registre(lignes: list[dict]) -> list[dict]:
    total = len(lignes)
    en_retard = sum(1 for ligne in lignes if ligne["etat"] == "En retard")
    critiques = sum(1 for ligne in lignes if ligne["critique"])
    realisees = sum(1 for ligne in lignes if ligne["etat"] == "Réalisée")
    taux = round(100 * realisees / total, 2) if total else None

    return [
        {
            "libelle": "Activités suivies",
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
            "libelle": "Critiques",
            "valeur": critiques,
            "note": "retard et contrainte échue",
            "feu": "rouge" if critiques else "vert",
        },
        {
            "libelle": "Taux de réalisation",
            "valeur": int(taux or 0),
            "note": "activités réalisées",
            "feu": feu(taux),
        },
    ]


def fiche(utilisateur: Utilisateur, activite_id: int) -> dict:
    """
    La fiche complete.

    **404 et non 403** quand l'activite est hors perimetre : repondre
    « interdit » confirmerait son existence — decision D5.
    """
    from noyau.erreurs import HorsPerimetre

    activite = _enrichies(_visibles(utilisateur)).filter(pk=activite_id).first()
    if activite is None:
        raise HorsPerimetre("Activite introuvable.")

    detail = composer_ligne(activite)
    detail.update(
        {
            "objectif": activite.objectif or "",
            "etatReferenceGeneral": activite.etat_reference or "",
            "resultatsAttendus": activite.resultats_attendus or "",
            "budgetValide": float(activite.budget_valide) if activite.budget_valide else None,
            "recalibrage": _recalibrage(activite),
            "indicateurs": _indicateurs(activite),
            "taches": _taches(activite),
            "vie": _fiche_de_vie(activite),
            "instructionsRattachees": _instructions(activite),
            "suspension": _suspension(activite),
            "derniereRelance": activite.derniere_relance_le.date().isoformat()
            if activite.derniere_relance_le
            else None,
        }
    )
    return detail


def _recalibrage(activite) -> dict | None:
    """
    Le desaccord, quand il y en a un — ADR 030.

    `None` tant que la DSR n'a pas contredit la structure, et c'est le cas
    ordinaire : la fiche ne doit pas porter une mention de recalibrage la ou il
    n'y a rien a arbitrer.

    Le taux **declare** part avec, sinon l'ecran ne peut pas montrer les deux —
    et montrer le seul taux retenu reviendrait a effacer ce que la structure
    avait dit, c'est-a-dire ce que le recalibrage sert justement a discuter.

    **Une synthese depuis l'ADR 049** : la DSR recalibre des taches, le
    declencheur somme leurs valeurs retenues dans `avancement_recalibre`. Le
    motif et la date sont ceux du dernier recalibrage de tache en vigueur ; le
    detail est porte par chaque tache.
    """
    if activite.avancement_recalibre is None:
        return None

    dernier = (
        activite.taches.filter(invalide_le__isnull=True, valeur_recalibree__isnull=False)
        .order_by("-recalibre_le")
        .first()
    )
    return {
        "avancementDeclare": float(activite.avancement_calcule),
        "avancementRetenu": float(activite.avancement_retenu),
        "motif": (dernier.recalibrage_motif or "") if dernier else "",
        "le": dernier.recalibre_le.date().isoformat() if dernier and dernier.recalibre_le else None,
    }


def _indicateurs(activite) -> list[dict]:
    resultat = []
    for indicateur in activite.indicateurs.filter(invalide_le__isnull=True).prefetch_related(
        "mesures"
    ):
        mesures = sorted(indicateur.mesures.all(), key=lambda m: m.date_mesure)
        derniere = mesures[-1] if mesures else None
        resultat.append(
            {
                "id": indicateur.pk,
                "libelle": indicateur.libelle,
                "unite": indicateur.unite or "",
                "etatReference": _nombre(indicateur.valeur_reference),
                "cible": _nombre(indicateur.valeur_cible),
                "realise": _nombre(derniere.valeur_atteinte) if derniere else None,
                "taux": _taux_atteinte(indicateur, derniere),
                "releveLe": derniere.date_mesure.isoformat() if derniere else None,
            }
        )
    return resultat


def _taux_atteinte(indicateur, derniere) -> float | None:
    """
    Progression de la reference vers la cible.

    **La formule n'est pas arbitree** — `activite.mode_taux_indicateur`, A4. Le
    sens decroissant est traite : sans lui, le taux d'un delai a reduire serait
    faux sans que rien ne le signale.
    """
    if derniere is None:
        return None

    reference = indicateur.valeur_reference or Decimal(0)
    portee = indicateur.valeur_cible - reference
    if portee == 0:
        return 100.0 if derniere.valeur_atteinte == indicateur.valeur_cible else 0.0

    progression = (derniere.valeur_atteinte - reference) / portee
    return float(round(max(Decimal(0), min(Decimal(1), progression)) * 100, 2))


def _nombre(valeur) -> str:
    """Les chiffres sortent en texte : le front les affiche, il ne calcule pas."""
    if valeur is None:
        return ""
    return format(valeur.normalize(), "f")


def _taches(activite) -> list[dict]:
    """
    Les taches et leur part de l'activite — ADR 049.

    `fait` se lit sur la valeur **retenue** : c'est elle qui compte dans
    l'avancement affiche et dans la criticite. La date de realisation reste
    celle de la declaration, et ne sort que si la tache est faite.

    `responsable` ne sort plus que pour les taches d'avant le 10/09/2026 : rien
    ne l'ecrit depuis (ADR 048), et aucun ecran ne l'affiche. Le champ est
    conserve tant que la colonne l'est.
    """
    resultat = []
    for tache in activite.taches.filter(invalide_le__isnull=True).select_related("responsable"):
        fait = tache.valeur_retenue >= tache.valeur_prevue
        resultat.append(
            {
                "id": tache.pk,
                "libelle": tache.intitule,
                "moisDebut": f"{tache.date_debut:%Y-%m}",
                "moisFin": f"{tache.date_fin:%Y-%m}",
                "valeurPrevue": float(tache.valeur_prevue),
                "valeurObtenue": float(tache.valeur_obtenue),
                "valeurRetenue": float(tache.valeur_retenue),
                # Point 2 de la demande : obtenue / prevue x 100, a l'echelle de
                # la tache. La valeur prevue est strictement positive au moteur.
                "avancementPropre": float(
                    round(tache.valeur_retenue * 100 / tache.valeur_prevue, 2)
                ),
                "fait": fait,
                "dateRealisation": tache.fait_le.isoformat() if fait and tache.fait_le else None,
                "recalibrage": {
                    "valeurDeclaree": float(tache.valeur_obtenue),
                    "valeurRetenue": float(tache.valeur_recalibree),
                    "motif": tache.recalibrage_motif or "",
                    "le": tache.recalibre_le.date().isoformat() if tache.recalibre_le else None,
                }
                if tache.valeur_recalibree is not None
                else None,
                "responsable": tache.responsable.nom_complet if tache.responsable else "",
            }
        )
    return resultat


#: Types d'evenement en base vers les huit libelles que le front sait afficher.
TYPES_VIE = {
    "activite_creee": "Création",
    "activite_modifiee": "Modification",
    "activite_taches_modifiees": "Modification",
    "avancement_declare": "Modification",
    #: Le desaccord a son propre libelle : le confondre avec une modification
    #: ordinaire rendrait invisible, dans la fiche de vie, le seul geste ou une
    #: autorite exterieure contredit la structure (ADR 030).
    "avancement_recalibre": "Recalibrage",
    "avancement_recalibrage_leve": "Recalibrage",
    "instruction_rattachee": "Instruction verbale",
    "instruction_levee": "Décision du DG",
    "decision_appliquee": "Décision du DG",
    "observation": "Observation",
    "relance_emise": "Relance",
    "plan_valide": "Validation",
    "piece_versee": "Pièce jointe",
    "activite_suspendue": "Décision du DG",
    "activite_reprise": "Décision du DG",
}


def _fiche_de_vie(activite) -> list[dict]:
    """
    §18. Ce n'est **pas une table** : ce sont les evenements de l'objet.

    Un type inconnu sort en « Observation » plutot que de faire disparaitre la
    ligne : une fiche de vie a trous est pire qu'une fiche imprecise.
    """
    from noyau.journal.modeles import Evenement
    from noyau.pieces.modeles import PieceJointe

    evenements = Evenement.objects.filter(objet_type="activite", objet_id=activite.pk).order_by(
        "survenu_le"
    )
    acteurs = {
        u.pk: u
        for u in Utilisateur.objects.filter(
            pk__in={e.acteur_id for e in evenements if e.acteur_id}
        ).select_related("poste")
    }
    # Les pieces pendent a l'**activite** et non a l'evenement : c'est ce qui
    # les rend visibles dans `GET /pieces?objetType=activite`. Le lien au geste
    # qui les a versees passe par les donnees de l'evenement.
    #
    # Le `uid` et non la cle primaire : c'est ce que le journal porte, et un
    # journal ne doit pas dependre d'un identifiant technique qui pourrait etre
    # reattribue.
    #
    # **Deux cles lues, et non une.** `pieceUid` est la cle canonique ; `uid`
    # est celle que `noyau.pieces.services.deposer` inscrivait avant le
    # 17 aout 2026. Un evenement ne se recrit pas — c'est la regle du journal —
    # donc les fiches de vie deja ecrites portent encore l'ancienne. Accepter
    # les deux ici est le prix de cette immuabilite ; le supprimer un jour
    # reviendrait a vider la chronologie des activites d'avant cette date.
    uids = {
        str(cle): e.pk
        for e in evenements
        if isinstance(e.donnees, dict)
        for cle in [e.donnees.get("pieceUid") or e.donnees.get("uid")]
        if cle
    }
    pieces: dict[int, list[PieceJointe]] = {}
    if uids:
        for piece in PieceJointe.objects.filter(uid__in=uids, invalide_le__isnull=True):
            pieces.setdefault(uids[str(piece.uid)], []).append(piece)

    resultat = []
    for evenement in evenements:
        auteur = acteurs.get(evenement.acteur_id) if evenement.acteur_id else None
        resultat.append(
            {
                "id": evenement.pk,
                "type": TYPES_VIE.get(evenement.type_evenement, "Observation"),
                "date": evenement.survenu_le.date().isoformat(),
                "auteur": auteur.nom_complet if auteur else "Traitement automatique",
                "initiales": auteur.initiales if auteur else "—",
                "poste": auteur.poste.libelle if auteur and auteur.poste else "",
                "texte": evenement.detail or evenement.libelle,
                "pieces": [
                    {"id": p.pk, "nom": p.nom_original, "poids": _poids(p.taille_octets)}
                    for p in pieces.get(evenement.pk, [])
                ],
            }
        )
    return resultat


def _poids(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo"


ORIGINES_VERS_FRONT = {
    "instruction_verbale": "Instruction verbale",
    "decision_dg": "Décision du DG",
}


def _instructions(activite) -> list[dict]:
    return [
        {
            "id": instruction.pk,
            "origine": ORIGINES_VERS_FRONT[instruction.origine],
            "reference": instruction.decision_reunion.reference
            if instruction.decision_reunion
            else None,
            "texte": instruction.texte,
            "date": instruction.date_instruction.isoformat(),
            "auteur": instruction.donnee_par.nom_complet if instruction.donnee_par else "",
            "responsable": instruction.responsable.nom_complet,
            "echeance": instruction.echeance.isoformat(),
            "levee": instruction.levee_le is not None,
            "dateLevee": instruction.levee_le.date().isoformat() if instruction.levee_le else None,
        }
        for instruction in activite.instructions.filter(invalide_le__isnull=True).select_related(
            "decision_reunion", "responsable", "donnee_par"
        )
    ]


def _suspension(activite) -> dict | None:
    """Renseignee seulement tant que la suspension est ouverte."""
    suspension = (
        activite.suspensions.filter(repris_le__isnull=True)
        .select_related("decision_reunion", "suspendu_par")
        .first()
    )
    if suspension is None:
        return None
    return {
        "motif": suspension.motif,
        "reference": suspension.decision_reunion.reference if suspension.decision_reunion else None,
        "decidePar": suspension.suspendu_par.nom_complet,
        "date": suspension.suspendu_le.date().isoformat(),
    }


# =====================================================================
#  Plan d'actions
# =====================================================================


def plan(utilisateur: Utilisateur, *, annee: int, structure: str = "") -> dict:
    """
    Le plan d'une structure pour un exercice.

    `structuresAccessibles` peuple un selecteur. **Ce n'est pas une
    protection** : `_visibles()` l'est. Un agent qui forcerait un sigle absent
    de la liste obtiendrait un plan vide, pas celui du voisin.
    """
    from noyau.erreurs import HorsPerimetre

    accessibles = _structures_accessibles(utilisateur)
    if not accessibles:
        raise HorsPerimetre("Aucune structure accessible.")

    sigles = [s.code for s in accessibles]
    sigle = structure if structure in sigles else sigles[0]
    porteuse = next(s for s in accessibles if s.code == sigle)

    plan_ = (
        PlanActions.objects.filter(
            structure=porteuse, exercice__annee=annee, invalide_le__isnull=True
        )
        .select_related("structure")
        .first()
    )

    activites = (
        [composer_ligne(a) for a in _enrichies(_visibles(utilisateur).filter(plan=plan_))]
        if plan_
        else []
    )

    return {
        "annee": annee,
        "structureSigle": porteuse.code,
        "structureLibelle": porteuse.libelle,
        # Un exercice sans plan n'est pas une erreur : c'est un plan a ecrire.
        "etat": STATUTS_PLAN_VERS_FRONT[plan_.statut] if plan_ else "Brouillon",
        "soumisLe": plan_.soumis_le.date().isoformat() if plan_ and plan_.soumis_le else None,
        "valideLe": plan_.valide_le.date().isoformat() if plan_ and plan_.valide_le else None,
        "validePar": _nom(plan_.valide_par) if plan_ else None,
        "motifRetour": plan_.motif_retour if plan_ else None,
        "activites": activites,
        "avancementGlobal": _avancement_global(activites),
        "budgetTotal": _budget_total(plan_) if plan_ else None,
        "structuresAccessibles": [{"sigle": s.code, "libelle": s.libelle} for s in accessibles],
    }


def _structures_accessibles(utilisateur: Utilisateur) -> list[Structure]:
    """
    Les structures dont l'agent peut ouvrir le plan.

    Portee `toutes` : toutes les structures en vigueur. Portee bornee : celles
    que `structures_visibles()` renvoie. Portee `propre` : sa seule structure de
    rattachement — un agent qui ne voit que ses activites n'ouvre pas le plan de
    son service.
    """
    visibles = structures_visibles(utilisateur)
    if visibles is None:
        return list(Structure.objects.filter(valide_au__isnull=True).order_by("code"))
    return list(visibles.filter(valide_au__isnull=True).order_by("code"))


def _avancement_global(lignes: list[dict]) -> float:
    """Moyenne simple. Ponderer par le budget serait une invention de plus."""
    if not lignes:
        return 0.0
    return round(sum(ligne["avancement"] for ligne in lignes) / len(lignes), 2)


def _budget_total(plan_) -> float | None:
    montants = [
        a.budget_valide
        for a in plan_.activites.filter(invalide_le__isnull=True)
        if a.budget_valide is not None
    ]
    return float(sum(montants)) if montants else None


def _nom(utilisateur_id: int | None) -> str | None:
    if utilisateur_id is None:
        return None
    agent = Utilisateur.objects.filter(pk=utilisateur_id).first()
    return agent.nom_complet if agent else None


def corbeille_plans(utilisateur: Utilisateur, *, annee: int) -> dict:
    """
    Ce que le controle de gestion attend — §15.

    Un validateur qui devrait ouvrir douze ecrans pour savoir lesquels
    l'attendent ne validerait rien : la liste est la porte d'entree du geste.
    """
    accessibles = _structures_accessibles(utilisateur)
    plans = (
        PlanActions.objects.filter(
            exercice__annee=annee, structure__in=accessibles, invalide_le__isnull=True
        )
        .select_related("structure")
        .annotate(_activites=Count("activites", filter=Q(activites__invalide_le__isnull=True)))
        .order_by("structure__code")
    )

    lignes = []
    for plan_ in plans:
        avancements = list(
            plan_.activites.filter(invalide_le__isnull=True).values_list(
                "avancement_retenu", flat=True
            )
        )
        lignes.append(
            {
                "structureSigle": plan_.structure.code,
                "structureLibelle": plan_.structure.libelle,
                "annee": annee,
                "etat": STATUTS_PLAN_VERS_FRONT[plan_.statut],
                "activites": plan_._activites,
                "avancementGlobal": round(float(sum(avancements) / len(avancements)), 2)
                if avancements
                else 0.0,
                "budgetTotal": _budget_total(plan_),
                "soumisLe": plan_.soumis_le.date().isoformat() if plan_.soumis_le else None,
            }
        )

    a_valider = sum(1 for ligne in lignes if ligne["etat"] == "Soumis au contrôle de gestion")
    valides = sum(1 for ligne in lignes if ligne["etat"] == "Validé")
    return {
        "plans": lignes,
        "compteurs": [
            {
                "libelle": "En attente de validation",
                "valeur": a_valider,
                "note": "soumis par les structures",
                "feu": "orange" if a_valider else "vert",
            },
            {"libelle": "Validés", "valeur": valides, "note": f"exercice {annee}", "feu": "vert"},
            {
                "libelle": "Plans suivis",
                "valeur": len(lignes),
                "note": "dans votre périmètre",
                "feu": "inconnu",
            },
        ],
    }


# =====================================================================
#  Obligations
# =====================================================================


def registre_obligations(utilisateur: Utilisateur, *, filtre: str = "") -> dict:
    """
    Ce que la structure doit deposer — descriptif fonctionnel §3.3.

    Le retard n'est pas stocke, par coherence avec l'arbitrage n° 2 : une
    obligation est en retard quand son echeance est passee et qu'elle n'a pas
    ete deposee.
    """
    aujourd_hui = date.today()
    requete = (
        restreindre(
            Obligation.objects.all(),
            utilisateur,
            champ_structure="structure",
            # Une obligation n'a pas de responsable : elle pese sur une structure.
            # En portee `propre`, l'agent voit celles de sa structure de
            # rattachement — sinon il ne verrait rien et ne deposerait jamais.
            champ_agent=None,
        )
        if porte_une_structure(utilisateur)
        else Obligation.objects.filter(structure__in=_structures_accessibles(utilisateur))
    )
    requete = requete.select_related("structure", "calendrier_production")

    lignes = [_composer_obligation(o, aujourd_hui) for o in requete]
    lignes = _filtrer_obligations(lignes, filtre)

    return {
        "obligations": lignes,
        "compteurs": _compteurs_obligations(lignes),
        "ponctualite": _ponctualite(requete, aujourd_hui),
    }


#: Ce que le selecteur de l'ecran propose, et ce que chacune de ses entrees
#: filtre. Les cles sont les **libelles du front** (`Obligations.tsx`), parce
#: que ce sont eux qui circulent dans l'URL.
#:
#: Ce tableau n'existait pas : le service comprenait `en_retard`, `deposees` et
#: `attendues`, trois codes que le front n'a jamais envoyes. Aucune des six
#: entrees du selecteur ne correspondait, donc aucune ne filtrait rien — les six
#: rendaient la meme liste, sans erreur. Voir docs/pieges.md.
_PREDICATS_OBLIGATION = {
    "À déposer": lambda ligne: not ligne["depose"],
    "En retard": lambda ligne: ligne["retardJours"] is not None,
    # Les anciens codes restent acceptes : ils sont peut-etre appeles ailleurs,
    # et les retirer sans le verifier remplacerait un filtre inerte par un 500.
    "attendues": lambda ligne: not ligne["depose"],
    "en_retard": lambda ligne: ligne["retardJours"] is not None,
    "deposees": lambda ligne: ligne["depose"],
}


def _filtrer_obligations(lignes: list[dict], filtre: str) -> list[dict]:
    """
    Applique le filtre du selecteur.

    Trois familles d'entrees, dans cet ordre : « Toutes » ne filtre rien, un
    etat filtre sur l'etat, et tout le reste est lu comme une **nature** de
    document — c'est ce que sont les trois dernieres entrees du selecteur
    (« Rapport mensuel d'activite »…).

    Une valeur inconnue rend une liste **vide** et non la liste entiere. C'est
    le choix inverse de celui qui vivait ici : rendre tout faisait passer un
    filtre casse pour un filtre neutre, et c'est precisement ce qui a permis au
    defaut de survivre. Un ecran vide se remarque.
    """
    if est_tout(filtre):
        return lignes

    predicat = _PREDICATS_OBLIGATION.get(filtre)
    if predicat is not None:
        return [ligne for ligne in lignes if predicat(ligne)]

    return [ligne for ligne in lignes if ligne["nature"] == filtre]


def _composer_obligation(obligation, aujourd_hui: date) -> dict:
    retard = (
        (aujourd_hui - obligation.echeance).days
        if obligation.depose_le is None and obligation.echeance < aujourd_hui
        else None
    )
    return {
        "id": obligation.pk,
        "intitule": obligation.intitule,
        "nature": NATURES_VERS_FRONT[obligation.calendrier_production.nature],
        "periode": obligation.periode_libelle,
        "echeance": obligation.echeance.isoformat(),
        "depose": obligation.depose_le is not None,
        "dateDepot": obligation.depose_le.isoformat() if obligation.depose_le else None,
        "feu": "vert" if obligation.depose_le else ("rouge" if retard else "orange"),
        "retardJours": retard,
        "structureSigle": obligation.structure.code,
        "ligneCalendrierId": obligation.calendrier_production_id,
    }


def _compteurs_obligations(lignes: list[dict]) -> list[dict]:
    attendues = sum(1 for ligne in lignes if not ligne["depose"])
    en_retard = sum(1 for ligne in lignes if ligne["retardJours"])
    return [
        {
            "libelle": "Attendues",
            "valeur": attendues,
            "note": "non encore déposées",
            "feu": "orange" if attendues else "vert",
        },
        {
            "libelle": "En retard",
            "valeur": en_retard,
            "note": "échéance dépassée",
            "feu": "rouge" if en_retard else "vert",
        },
        {
            "libelle": "Suivies",
            "valeur": len(lignes),
            "note": "dans votre périmètre",
            "feu": "inconnu",
        },
    ]


def _ponctualite(requete: QuerySet, aujourd_hui: date) -> float:
    """
    Part des obligations deposees dans les delais sur douze mois.

    Les obligations non echues sont exclues : les compter comme en retard
    ferait chuter le taux au seul passage du temps.
    """
    depuis = date(aujourd_hui.year - 1, aujourd_hui.month, 1)
    echues = [o for o in requete if o.echeance >= depuis and o.echeance <= aujourd_hui]
    if not echues:
        return 100.0
    a_lheure = sum(1 for o in echues if o.depose_le and o.depose_le <= o.echeance)
    return round(100 * a_lheure / len(echues), 2)

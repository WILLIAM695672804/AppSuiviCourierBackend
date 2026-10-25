"""
Le tableau de bord d'une structure — niveaux 2 et 3 du §4.

Le descriptif distingue ces deux niveaux par le **perimetre**, pas par le
contenu : le point focal voit sa seule structure (§3.5, niveau 3), le
responsable voit sa branche et la DSR toutes (§3.4, niveau 2). C'est donc un
seul ecran, dont le selecteur de structure n'apparait qu'a qui peut en changer —
et c'est le serveur qui le dit, en renvoyant les structures accessibles.

**Le sigle demande est verifie contre le perimetre.** Un sigle hors perimetre
rend 404 et non 403 : la decision D5 le pose pour le courrier confidentiel, et
la raison vaut ici — repondre « vous n'avez pas le droit » confirme l'existence
de la structure et de ses chiffres a qui n'a pas a les connaitre.

Trois blocs, parce que ce sont les trois criteres de la matrice : la structure
retrouve ici, en detail, ce qui fait sa note. Le bloc courrier est servi **vide
avec sa raison** plutot qu'omis : un ecran a deux blocs chez l'un et trois chez
l'autre se lit comme une panne, quand l'absence est la meme pour tout le monde.
"""

from datetime import date

from activite.modeles import Obligation
from dossier.lecture import instruction_dans_le_delai
from noyau.calendrier import libelle_mois, mois_precedent
from noyau.erreurs import HorsPerimetre
from noyau.feu import feu
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.perimetre.portee import structures_visibles
from performance import matrice as calcul
from pilotage import mesures


def tableau_structure(
    utilisateur: Utilisateur, sigle: str = "", aujourd_hui: date | None = None
) -> dict:
    """
    Le tableau de bord d'une structure du perimetre.

    Sans sigle, celle de rattachement de l'agent : c'est l'ecran d'accueil du
    point focal et du responsable, et leur demander de choisir leur propre
    structure chaque matin n'aurait servi a rien.
    """
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)

    accessibles = structures_accessibles(utilisateur)
    cible = structure_cible(utilisateur, accessibles, sigle)

    rang, score, total = _place_au_classement(utilisateur, cible, annee, mois)

    return {
        "structureSigle": cible.code,
        "structureLibelle": cible.libelle,
        "structuresAccessibles": [
            {"sigle": structure.code, "libelle": structure.libelle} for structure in accessibles
        ],
        "periode": libelle_mois(annee, mois),
        "rang": rang,
        "totalStructures": total,
        "scoreGlobal": score,
        "feu": feu(score),
        "activites": _bloc_activites([cible], jour),
        "courrier": _bloc_courrier([cible], annee, mois),
        "rituels": _bloc_rituels([cible], jour),
        "aTraiter": _a_traiter(cible, jour),
    }


def structures_accessibles(utilisateur: Utilisateur) -> list[Structure]:
    """
    Les structures que le perimetre autorise a consulter.

    `structures_visibles()` rend `None` en portee « toutes » ; l'ecran a besoin
    de la liste pour son selecteur, elle est donc developpee ici — et nulle
    part ailleurs.

    Publique, avec `structure_cible()`, parce que les rapports periodiques
    resolvent le meme perimetre de la meme facon : deux ecrans qui repondraient
    differemment au meme sigle donneraient deux verites sur la meme structure.
    """
    visibles = structures_visibles(utilisateur)
    if visibles is None:
        return list(Structure.objects.en_vigueur().order_by("code"))
    return list(visibles.order_by("code"))


def structure_cible(
    utilisateur: Utilisateur, accessibles: list[Structure], sigle: str
) -> Structure:
    if sigle:
        for structure in accessibles:
            if structure.code == sigle:
                return structure
        raise HorsPerimetre("Structure introuvable.")

    if utilisateur.structure_id is not None:
        for structure in accessibles:
            if structure.pk == utilisateur.structure_id:
                return structure

    if accessibles:
        return accessibles[0]

    raise HorsPerimetre("Structure introuvable.")


def _place_au_classement(
    utilisateur: Utilisateur, structure: Structure, annee: int, mois: int
) -> tuple[int | None, float | None, int]:
    """
    Le rang et le score de la structure au dernier mois clos.

    `None` quand elle n'est pas classee : toutes ne le sont pas — seules celles
    dont le niveau hierarchique porte `ligne_statistiques`, et, pour qui
    consolide, seules les tetes de structure. Un rang invente pour un service
    qui ne figure a aucun tableau statistique aurait ete lu comme un rang reel.
    """
    lignes = calcul.matrice(utilisateur, annee, mois)["lignes"]
    for ligne in lignes:
        if ligne["structureSigle"] == structure.code:
            return ligne["rang"], ligne["scoreGlobal"], len(lignes)
    return None, None, len(lignes)


# =====================================================================
#  Les trois blocs
# =====================================================================


def _bloc_activites(structures: list[Structure], jour: date) -> list[dict]:
    a_l_heure, total = mesures.activites_a_l_heure(structures, a_la_date=jour)
    avancement = mesures.execution_activites(structures, a_la_date=jour)
    critiques = mesures.activites_critiques(structures)

    taux = round(a_l_heure / total * 100, 1) if total else None

    return [
        {
            "libelle": "Activités menées à l'heure",
            "valeur": f"{a_l_heure} / {total}" if total else "Aucune",
            "note": "activités commencées, hors retard" if total else "aucune activité commencée",
            "feu": feu(taux),
        },
        {
            "libelle": "Avancement moyen du plan",
            "valeur": f"{avancement} %" if avancement is not None else "Non mesuré",
            "note": "moyenne des avancements calculés",
            "feu": feu(avancement),
        },
        {
            "libelle": "Activités critiques",
            "valeur": str(critiques),
            "note": "en retard et portant une contrainte échue (§20)",
            # Un comptage d'anomalies : zero est vert, une seule est rouge.
            # Passer par `feu()` aurait exige d'en faire un taux, qui n'a
            # aucun sens ici.
            "feu": "vert" if critiques == 0 else "rouge",
        },
    ]


def _bloc_courrier(structures: list[Structure], annee: int, mois: int) -> list[dict]:
    """
    Le bloc courrier et dossiers — deux lignes qui disent enfin la meme chose.

    Le **courrier** se mesure depuis la mise en service de la cloture
    (27 aout 2026). Jusque-la cette ligne sortait a « Non mesuré » avec la
    mention « le pilier courrier n'est pas en service » : c'etait exact, aucun
    geste ne refermait un courrier, donc aucun delai ne s'arretait.

    Le « Non mesuré » qui subsiste ne dit plus « pas d'outil » mais « pas encore
    de matiere » — ni pour le courrier, ni pour les dossiers. Les deux ne se
    corrigent pas de la meme facon, et c'est ce que la note distingue.
    """
    debut, fin = calcul.bornes(annee, mois)
    taux, dans_le_delai_courrier, clos_courrier = mesures.courrier_dans_le_delai(
        debut, fin, structures
    )

    instruction = mesures.instruction_dossiers(structures)
    dans_le_delai, clos = instruction_dans_le_delai(structures)

    return [
        {
            "libelle": "Courriers traités dans le délai",
            "valeur": f"{taux} %" if taux is not None else "Non mesuré",
            "note": (
                f"{dans_le_delai_courrier} sur {clos_courrier} courrier(s) clôturé(s)"
                if clos_courrier
                else mesures.SANS_COURRIER_CLOS
            ),
            "feu": feu(taux),
        },
        {
            "libelle": "Dossiers instruits dans le délai",
            "valeur": f"{instruction} %" if instruction is not None else "Non mesuré",
            "note": (
                f"{dans_le_delai} sur {clos} dossier(s) clos"
                if clos
                else mesures.SANS_DOSSIERS_CLOS
            ),
            "feu": feu(instruction),
        },
    ]


def _bloc_rituels(structures: list[Structure], jour: date) -> list[dict]:
    a_temps, echues = mesures.ponctualite_obligations(structures)
    taux = round(a_temps / echues * 100, 1) if echues else None

    prochaine = (
        Obligation.objects.filter(
            structure__in=structures, depose_le__isnull=True, echeance__gte=jour
        )
        .order_by("echeance")
        .first()
    )
    en_retard = Obligation.objects.filter(
        structure__in=structures, depose_le__isnull=True, echeance__lt=jour
    ).count()

    return [
        {
            "libelle": "Productions déposées à l'échéance",
            "valeur": f"{a_temps} / {echues}" if echues else "Aucune échue",
            "note": "obligations échues du calendrier officiel",
            "feu": feu(taux),
        },
        {
            "libelle": "Productions en retard",
            "valeur": str(en_retard),
            "note": "échéance passée, aucun dépôt",
            "feu": "vert" if en_retard == 0 else "rouge",
        },
        {
            "libelle": "Prochaine échéance",
            "valeur": prochaine.echeance.isoformat() if prochaine else "Aucune",
            "note": prochaine.intitule if prochaine else "rien d'attendu à ce jour",
            "feu": "inconnu",
        },
    ]


def _a_traiter(structure: Structure, jour: date) -> list[dict]:
    """
    Ce qui appelle une action dans cette structure, tous piliers confondus.

    Une ligne par objet nomme, comme au cockpit : « 3 obligations en retard »
    n'appelle aucun geste, « Rapport mensuel de juillet, échéance dépassée »
    en appelle un.
    """
    lignes: list[dict] = []

    for obligation in Obligation.objects.filter(
        structure=structure, depose_le__isnull=True, echeance__lt=jour
    ).order_by("echeance")[:5]:
        retard = (jour - obligation.echeance).days
        lignes.append(
            {
                "libelle": f"{obligation.intitule} — {obligation.periode_libelle}",
                "precision": f"Échéance dépassée de {retard} jour{'s' if retard > 1 else ''}",
                "feu": "rouge",
                "chemin": "/activites/obligations",
            }
        )

    engagements = mesures.engagements_vivants([structure])
    etats = mesures.etats_engagements(engagements)
    for engagement in engagements.filter(
        pk__in=[identifiant for identifiant, etat in etats.items() if etat == "en_retard"]
    ).order_by("echeance")[:5]:
        lignes.append(
            {
                "libelle": f"{engagement.reference or 'Décision'} — {engagement.objet}",
                "precision": "Décision d'instance dont l'échéance est dépassée",
                "feu": "rouge",
                "chemin": f"/gouvernance/decisions/{engagement.pk}",
            }
        )

    critiques = mesures.activites_critiques([structure])
    if critiques:
        lignes.append(
            {
                "libelle": f"{critiques} activité{'s' if critiques > 1 else ''} critique"
                + ("s" if critiques > 1 else ""),
                "precision": "En retard et portant une contrainte échue (§20)",
                "feu": "rouge",
                "chemin": "/activites",
            }
        )

    return lignes

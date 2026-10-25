"""
Le tableau de bord et ses trois perimetres — §3.4, §3.5 et ADR 009.

« Le perimetre n'est pas un filtre d'affichage, c'est une question posee au
serveur » : *ce que je vois quand je regarde l'institution*, *ma structure et
ses filles*, *mes dossiers*. Le front demande, le serveur repond ce que
l'habilitation autorise — et **dit ce qu'il a applique**.

Un perimetre demande plus large que la portee n'est pas une erreur : c'est le
cas ordinaire d'un lien partage ou d'un onglet reste ouvert apres un changement
d'habilitation. Le repondre en 403 aurait casse l'ecran d'un agent qui n'a rien
fait de mal ; le serveur ramene donc le perimetre a ce que la portee permet, le
renvoie dans `perimetreApplique`, et le front l'affiche. La garde reste large,
le contenu est filtre (ADR 009).

`mesDossiers` merite une precision : ce depot n'a **pas** de pilier courrier ni
de pilier dossiers. Le perimetre existe neanmoins, parce qu'un agent porte des
activites et des obligations dont il est responsable ; ce qu'il ne porte pas est
dit « non mesuré » comme partout ailleurs (ADR 011).
"""

from datetime import date

from activite.modeles import Obligation
from dossier.lecture import dossiers_de_l_agent
from noyau.calendrier import MOIS_COURTS, libelle_mois, mois_precedent
from noyau.feu import feu
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.perimetre.modeles import PORTEE_PROPRE, PORTEE_TOUTES
from noyau.perimetre.portee import perimetre_en_vigueur, structures_visibles
from performance import matrice
from pilotage import mesures
from pilotage.analyses import seuil_respect

INSTITUTION = "institution"
STRUCTURE = "structure"
MES_DOSSIERS = "mesDossiers"

#: Le nombre de mois que porte la serie, par periode demandee. La periode ne
#: change pas ce qui est mesure, seulement l'amplitude de la courbe : c'est ce
#: qui permet de comparer deux ecrans sans se demander lequel dit vrai.
AMPLITUDES = {"mois": 1, "trimestre": 3, "semestre": 6, "annee": 12}

#: Au-dela, l'ecran defile. Meme raison qu'au cockpit.
PLAFOND_RETARDS = 15


def tableau_de_bord(
    utilisateur: Utilisateur,
    *,
    perimetre: str = INSTITUTION,
    periode: str = "mois",
    aujourd_hui: date | None = None,
) -> dict:
    """Le tableau de bord du perimetre demande, borne a ce que la portee permet."""
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)
    amplitude = AMPLITUDES.get(periode, 1)

    applique = _perimetre_applique(utilisateur, perimetre)
    structures = _structures(utilisateur, applique)

    return {
        "perimetreDemande": perimetre,
        "perimetreApplique": applique,
        "perimetreLibelle": _libelle_perimetre(utilisateur, applique),
        "periode": libelle_mois(annee, mois),
        "indicateurs": _indicateurs(utilisateur, structures, applique, annee, mois, jour),
        "serie": _serie(structures, annee, mois, amplitude),
        "retards": _retards(utilisateur, structures, applique, jour),
        "tauxRespect": _taux_respect(structures),
        "objectifRespect": seuil_respect(),
        # Le courrier est sorti de cette liste le 27 aout 2026 : il se mesure,
        # et il a sa ligne parmi les indicateurs. La liste reste — ce qui n'est
        # pas mesure doit continuer de se dire.
        "nonMesure": [],
    }


# =====================================================================
#  Le perimetre
# =====================================================================


def _perimetre_applique(utilisateur: Utilisateur, demande: str) -> str:
    """
    Ce que la portee laisse voir, du perimetre demande.

    Une portee `propre` ramene tout a `mesDossiers` ; une portee bornee ramene
    `institution` a `structure`. Une portee `toutes` ne ramene rien : elle voit
    ce qu'elle demande.
    """
    portee = perimetre_en_vigueur(utilisateur)
    if portee is None:
        return MES_DOSSIERS

    if portee.portee == PORTEE_PROPRE:
        return MES_DOSSIERS

    if demande == INSTITUTION and portee.portee != PORTEE_TOUTES:
        return STRUCTURE

    if demande not in (INSTITUTION, STRUCTURE, MES_DOSSIERS):
        # Un perimetre inconnu vaut le plus restreint, jamais le plus large :
        # une faute de frappe dans une adresse ne doit pas ouvrir l'institution.
        return MES_DOSSIERS

    return demande


def _structures(utilisateur: Utilisateur, applique: str) -> list[Structure] | None:
    """
    Les structures sur lesquelles portent les mesures. `None` = toutes.

    `None` traverse jusqu'aux fonctions de `mesures.py`, qui ne posent alors
    aucun filtre — c'est la convention de `structures_visibles()`, tenue de bout
    en bout pour eviter un `IN` de plusieurs centaines d'identifiants.
    """
    if applique == INSTITUTION:
        return None

    visibles = structures_visibles(utilisateur)
    if visibles is None:
        # Portee `toutes` demandant sa propre structure : c'est celle de
        # rattachement, pas l'institution entiere.
        if utilisateur.structure_id is None:
            return None
        return list(Structure.objects.filter(pk=utilisateur.structure_id))

    return list(visibles)


def _libelle_perimetre(utilisateur: Utilisateur, applique: str) -> str:
    if applique == INSTITUTION:
        return "Port autonome de Douala"
    if applique == MES_DOSSIERS:
        return f"{utilisateur.prenom} {utilisateur.nom}"
    return utilisateur.structure.libelle if utilisateur.structure else "Votre structure"


# =====================================================================
#  Les indicateurs
# =====================================================================


def _indicateurs(
    utilisateur: Utilisateur,
    structures: list[Structure] | None,
    applique: str,
    annee: int,
    mois: int,
    jour: date,
) -> list[dict]:
    """
    Quatre chiffres et leur evolution reelle.

    `variation` sort a `null` quand l'une des deux mesures manque : afficher
    une fleche contre une absence de mesure aurait invente une progression
    (ADR 011).
    """
    execution = mesures.execution_activites(structures, a_la_date=jour)
    annee_avant, mois_avant = mois_precedent(annee, mois)
    execution_avant = mesures.execution_mensuelle(annee_avant, mois_avant)

    a_l_heure, commencees = mesures.activites_a_l_heure(structures, a_la_date=jour)
    a_temps, echues = mesures.ponctualite_obligations(structures)
    executees = mesures.decisions_executees(annee, mois, structures)
    executees_avant = mesures.decisions_executees(annee_avant, mois_avant, structures)

    respect = round(a_temps / echues * 100, 1) if echues else None

    debut, fin = matrice.bornes(annee, mois)
    debut_avant, fin_avant = matrice.bornes(annee_avant, mois_avant)
    courrier, dans_le_delai, clos = mesures.courrier_dans_le_delai(debut, fin, structures)
    courrier_avant, _, _ = mesures.courrier_dans_le_delai(debut_avant, fin_avant, structures)

    indicateurs = [
        {
            "libelle": "Exécution des activités",
            "valeur": f"{execution} %" if execution is not None else "Non mesuré",
            "variation": mesures.variation(execution, execution_avant),
            "note": "moyenne des avancements calculés",
            "feu": feu(execution),
        },
        {
            "libelle": "Activités menées à l'heure",
            "valeur": f"{a_l_heure} / {commencees}" if commencees else "Aucune",
            "variation": None,
            "note": "activités commencées, hors retard",
            "feu": feu(round(a_l_heure / commencees * 100, 1) if commencees else None),
        },
        {
            "libelle": "Productions déposées à l'échéance",
            "valeur": f"{respect} %" if respect is not None else "Non mesuré",
            "variation": None,
            "note": f"seuil attendu {seuil_respect()} %",
            "feu": feu(respect),
        },
        {
            "libelle": "Décisions exécutées dans le mois",
            "valeur": str(executees),
            "variation": mesures.variation(float(executees), float(executees_avant)),
            "note": "engagements portés au registre des décisions",
            "feu": "inconnu",
        },
        {
            # La ligne que cet ecran promettait sans pouvoir la tenir : le
            # courrier se cloture depuis le 27 aout 2026, donc son delai
            # s'arrete quelque part et se mesure.
            "libelle": "Courriers traités dans le délai",
            "valeur": f"{courrier} %" if courrier is not None else "Non mesuré",
            "variation": mesures.variation(courrier, courrier_avant),
            "note": (
                f"{dans_le_delai} sur {clos} courrier(s) clôturé(s)"
                if clos
                else mesures.SANS_COURRIER_CLOS
            ),
            "feu": feu(courrier),
        },
    ]

    if applique == MES_DOSSIERS:
        # En perimetre personnel, la ligne porte enfin sur l'agent lui-meme et
        # non sur sa structure : « votre service en a trente » et « vous en avez
        # quatre » n'appellent pas le meme geste. Le pilier dossiers est le seul
        # a porter un objet nominatif (`instructeur`) ; tant qu'il n'existait
        # pas, cette ligne sortait a « Non mesuré ».
        hors_delai, ouverts = dossiers_de_l_agent(utilisateur, a_la_date=jour)
        indicateurs.append(
            {
                "libelle": "Dossiers dont vous êtes responsable",
                "valeur": str(ouverts),
                "variation": None,
                "note": (
                    f"dont {hors_delai} hors délai"
                    if ouverts
                    else "aucun dossier ne vous est nommément confié"
                ),
                # Un comptage d'anomalies : zero est vert, un seul est rouge.
                # Le passer par `feu()` aurait exige d'en faire un taux, qui
                # n'a pas de sens sur quatre dossiers.
                "feu": "inconnu" if not ouverts else ("rouge" if hors_delai else "vert"),
            }
        )

    return indicateurs


# =====================================================================
#  La serie et les retards
# =====================================================================


def _serie(structures: list[Structure] | None, annee: int, mois: int, amplitude: int) -> list[dict]:
    """Ce qui est du et ce qui est fait, mois par mois, sur l'amplitude demandee."""
    serie = []
    for annee_serie, mois_serie in mesures.mois_glissants(annee, mois, amplitude):
        obligations = Obligation.objects.filter(
            echeance__year=annee_serie, echeance__month=mois_serie
        )
        if structures is not None:
            obligations = obligations.filter(structure__in=structures)

        serie.append(
            {
                "periode": MOIS_COURTS[mois_serie - 1],
                "attendues": obligations.count(),
                "deposees": obligations.filter(depose_le__isnull=False).count(),
                "decisionsExecutees": mesures.decisions_executees(
                    annee_serie, mois_serie, structures
                ),
            }
        )
    return serie


def _retards(
    utilisateur: Utilisateur,
    structures: list[Structure] | None,
    applique: str,
    jour: date,
) -> list[dict]:
    """
    Ce qui est en retard, nomme.

    Comme au cockpit : une ligne par objet. « 7 productions en retard » ne
    designe personne et ne se traite pas.
    """
    lignes: list[dict] = []

    obligations = Obligation.objects.filter(depose_le__isnull=True, echeance__lt=jour)
    if structures is not None:
        obligations = obligations.filter(structure__in=structures)
    if applique == MES_DOSSIERS and utilisateur.structure_id is not None:
        obligations = obligations.filter(structure_id=utilisateur.structure_id)

    for obligation in obligations.select_related("structure").order_by("echeance")[
        :PLAFOND_RETARDS
    ]:
        lignes.append(
            {
                "id": obligation.pk,
                "reference": obligation.periode_libelle,
                "objet": obligation.intitule,
                "structure": obligation.structure.code if obligation.structure else "—",
                "etape": "Production attendue",
                "retardJours": (jour - obligation.echeance).days,
                "chemin": "/activites/obligations",
            }
        )

    engagements = mesures.engagements_vivants(structures)
    etats = mesures.etats_engagements(engagements)
    en_retard = [identifiant for identifiant, etat in etats.items() if etat == "en_retard"]
    for engagement in engagements.filter(pk__in=en_retard).order_by("echeance")[:PLAFOND_RETARDS]:
        lignes.append(
            {
                "id": engagement.pk,
                "reference": engagement.reference or "—",
                "objet": engagement.objet,
                "structure": _sigle_pilote(engagement),
                "etape": "Décision d'instance",
                "retardJours": ((jour - engagement.echeance).days if engagement.echeance else 0),
                "chemin": f"/gouvernance/decisions/{engagement.pk}",
            }
        )

    lignes.sort(key=lambda ligne: ligne["retardJours"], reverse=True)
    return lignes[:PLAFOND_RETARDS]


def _sigle_pilote(engagement) -> str:
    charge = engagement.structures.filter(rang=1).select_related("structure").first()
    return charge.structure.code if charge else "—"


def _taux_respect(structures: list[Structure] | None) -> float | None:
    a_temps, echues = mesures.ponctualite_obligations(structures)
    return round(a_temps / echues * 100, 1) if echues else None

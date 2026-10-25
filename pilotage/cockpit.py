"""
Le cockpit executif et la note de synthese — niveau 1 du §4.

« Vue unique tenant sur un seul ecran, agregeant automatiquement le taux global
d'execution des activites, le nombre de decisions en retard, les structures a
risque, la disponibilite des hauts responsables et les alertes actives classees
par criticite » (§3.1).

**La contrainte « un seul ecran » est une contrainte de serveur avant d'etre
une contrainte de mise en page.** Si la reponse porte quarante alertes, l'ecran
defile quoi qu'en dise le CSS. Le serveur borne donc ce qu'il envoie, et il le
borne par la criticite : ce qui appelle un arbitrage passe devant ce qui appelle
une relance.

Rien n'entre ici qui n'appelle une decision. Un chiffre qui va bien occupe une
ligne ; un chiffre qui ne va pas porte le chemin de l'ecran ou l'on agit — et
`null` quand cet ecran n'existe pas encore, plutot qu'un lien mort.
"""

from datetime import date

from gouvernance.modeles import Disponibilite, Engagement
from noyau.calendrier import libelle_mois, mois_precedent
from noyau.feu import SEUIL_ORANGE, feu
from noyau.identite.modeles import Utilisateur
from performance import matrice as calcul
from pilotage import mesures

#: Les trois criticites du §3.1, dans l'ordre ou le front les classe.
CRITIQUE = "Critique"
ELEVEE = "Élevée"
MODEREE = "Modérée"

#: Au-dela, l'ecran defile — et un cockpit qui defile n'est plus un cockpit.
#: Les alertes retirees sont les moins critiques : celles qui restent sont
#: celles qu'on ne peut pas remettre a demain.
PLAFOND_ALERTES = 12

#: Les engagements que le Directeur general suit personnellement. Les autres
#: instances existent (CODIR, assemblee generale) mais ne relevent pas de son
#: arbitrage direct : les afficher ici aurait noye les siennes.
INSTANCES_DU_COCKPIT = ["directeur_general", "conseil_administration"]

LIBELLES_ORIGINE = {
    "directeur_general": "Instruction du Directeur général",
    "conseil_administration": "Résolution du Conseil d'administration",
}


def cockpit(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict:
    """
    Tout le cockpit en une reponse.

    Le classement est celui du **dernier mois clos** : un classement du mois en
    cours n'est pas comparable d'une structure a l'autre, et le cockpit
    n'affiche pas de chiffre dont il faudrait expliquer qu'il ne veut encore
    rien dire.
    """
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)

    classement = calcul.matrice(utilisateur, annee, mois)["lignes"]
    # « A risque » se dit d'une structure **mesurée** dont le score est bas. Une
    # structure dont aucun critere n'est renseigne a un score de zero par
    # construction ; l'alerter reviendrait a signaler une absence de saisie
    # comme une defaillance, et a noyer les vraies alertes (ADR 011).
    a_risque = [
        ligne
        for ligne in mesures.lignes_mesurees(classement)
        if ligne["scoreGlobal"] < SEUIL_ORANGE
    ]

    execution = mesures.execution_activites()
    critiques = mesures.activites_critiques()
    en_retard = mesures.decisions_en_retard()
    sans_interim = mesures.absences_sans_interim(jour)

    return {
        "periode": libelle_mois(annee, mois),
        # Zero et non `null` : ces quatre chiffres sont des **comptages**, pas
        # des taux. « Aucune decision en retard » est une mesure, pas une
        # absence de mesure. Seule l'execution peut manquer, faute d'activites.
        "executionActivites": execution if execution is not None else 0,
        "decisionsEnRetard": en_retard,
        "structuresARisque": len(a_risque),
        "absencesSansInterim": sans_interim,
        "activitesCritiques": critiques,
        "alertes": _alertes(jour, a_risque, critiques),
        "engagements": _engagements_du_dg(jour),
        "indicateurs": _indicateurs(annee, mois, execution),
        "meilleures": _extremes(classement, debut=True),
        "fragiles": _extremes(classement, debut=False),
    }


# =====================================================================
#  Les alertes
# =====================================================================


def _alertes(jour: date, a_risque: list[dict], critiques: int) -> list[dict]:
    """
    Ce qui appelle un arbitrage, du plus grave au moins grave.

    Une alerte par **objet nomme**, jamais par famille : « 4 décisions en
    retard » n'appelle aucune action, « DEC-2026-0007, échéance dépassée de 12
    jours » en appelle une. C'est la difference entre un tableau de bord et un
    cockpit.
    """
    alertes: list[dict] = []

    # Les decisions dont l'echeance est passee. Le jalon echu fait la
    # difference entre une decision qui prend du retard et une qu'on a oubliee.
    engagements = mesures.engagements_vivants().select_related()
    etats = mesures.etats_engagements(engagements)
    for engagement in engagements.filter(
        pk__in=[identifiant for identifiant, etat in etats.items() if etat == "en_retard"]
    ).order_by("echeance")[:PLAFOND_ALERTES]:
        retard = (jour - engagement.echeance).days if engagement.echeance else 0
        alertes.append(
            {
                "id": engagement.pk,
                "criticite": CRITIQUE if retard > 30 else ELEVEE,
                "libelle": f"{engagement.reference or 'Décision'} — {engagement.objet}",
                "precision": f"Échéance dépassée de {retard} jour{'s' if retard > 1 else ''}",
                "chemin": f"/gouvernance/decisions/{engagement.pk}",
                "structure": _pilote(engagement),
            }
        )

    # Les structures dont le score passe sous le seuil d'alerte. Une par ligne :
    # c'est un directeur qu'on nomme, pas un compteur.
    for ligne in a_risque:
        alertes.append(
            {
                "id": -ligne["rang"],
                "criticite": ELEVEE,
                "libelle": f"{ligne['structureSigle']} sous le seuil d'alerte",
                "precision": (
                    f"Score de {ligne['scoreGlobal']} sur 100 au dernier mois clos, "
                    f"rang {ligne['rang']}"
                ),
                "chemin": f"/performance/classement/{ligne['structureSigle']}",
                "structure": ligne["structureSigle"],
            }
        )

    # Les absences sans interimaire : les dossiers de la structure s'arretent.
    absences = (
        Disponibilite.objects.filter(
            invalide_le__isnull=True, interimaire__isnull=True, du__lte=jour, au__gte=jour
        )
        .select_related("utilisateur", "utilisateur__structure")
        .order_by("au")
    )
    for absence in absences:
        agent = f"{absence.utilisateur.prenom} {absence.utilisateur.nom}"
        alertes.append(
            {
                "id": absence.pk,
                "criticite": MODEREE,
                "libelle": f"{agent} absent sans intérim",
                "precision": f"Jusqu'au {absence.au.isoformat()} — aucun suppléant désigné",
                "chemin": "/gouvernance/disponibilites",
                "structure": (
                    absence.utilisateur.structure.code if absence.utilisateur.structure else None
                ),
            }
        )

    if critiques:
        alertes.append(
            {
                "id": 0,
                "criticite": CRITIQUE,
                "libelle": f"{critiques} activité{'s' if critiques > 1 else ''} critique"
                + ("s" if critiques > 1 else ""),
                "precision": "En retard et portant une contrainte échue (§20)",
                "chemin": "/activites",
                "structure": None,
            }
        )

    rang = {CRITIQUE: 0, ELEVEE: 1, MODEREE: 2}
    alertes.sort(key=lambda alerte: rang[alerte["criticite"]])
    return alertes[:PLAFOND_ALERTES]


def _pilote(engagement: Engagement) -> str | None:
    """Le sigle de la structure pilote — celle qui rend compte (rang 1)."""
    charge = engagement.structures.filter(rang=1).select_related("structure").first()
    return charge.structure.code if charge else None


# =====================================================================
#  Les engagements du Directeur general
# =====================================================================


def _engagements_du_dg(jour: date) -> list[dict]:
    """
    Ce que le Directeur general a decide, et ce que le Conseil lui a prescrit.

    Les engagements executes sortent de la liste : le cockpit montre ce qui
    reste a faire. L'historique se lit au registre des decisions, qui est fait
    pour cela.
    """
    engagements = Engagement.objects.filter(
        invalide_le__isnull=True,
        origine=Engagement.INSTANCE,
        instance__in=INSTANCES_DU_COCKPIT,
        execute_le__isnull=True,
    ).order_by("echeance")[:8]

    lignes = []
    for engagement in engagements:
        avancement = float(engagement.avancement)
        en_retard = engagement.echeance is not None and engagement.echeance < jour
        lignes.append(
            {
                "id": engagement.pk,
                "reference": engagement.reference or "—",
                "objet": engagement.objet,
                "origine": LIBELLES_ORIGINE.get(
                    engagement.instance or "", "Instruction du Directeur général"
                ),
                "echeance": engagement.echeance.isoformat() if engagement.echeance else None,
                "avancement": avancement,
                # Un engagement en retard est rouge quel que soit son
                # avancement : 80 % apres l'echeance reste un engagement non
                # tenu, et le colorer en vert aurait rassure a tort.
                "feu": "rouge" if en_retard else feu(avancement),
                "enRetard": en_retard,
            }
        )
    return lignes


# =====================================================================
#  Les indicateurs et les extremes du classement
# =====================================================================


def _indicateurs(annee: int, mois: int, execution: float | None) -> list[dict]:
    """
    Trois chiffres avec leur evolution — et `null` quand l'evolution ne se
    calcule pas.

    Une variation contre une mesure absente serait un chiffre invente : elle
    sort a `null`, et le front n'affiche alors aucune fleche (ADR 011).
    """
    annee_avant, mois_avant = mois_precedent(annee, mois)

    execution_avant = mesures.execution_mensuelle(annee_avant, mois_avant)
    executees = mesures.decisions_executees(annee, mois)
    executees_avant = mesures.decisions_executees(annee_avant, mois_avant)

    a_temps, echues = mesures.ponctualite_obligations()
    ponctualite = round(a_temps / echues * 100, 1) if echues else None

    return [
        {
            "libelle": "Exécution des activités",
            "valeur": f"{execution} %" if execution is not None else "Non mesuré",
            "variation": mesures.variation(execution, execution_avant),
            "favorable": (
                None
                if execution is None or execution_avant is None
                else execution >= execution_avant
            ),
        },
        {
            "libelle": "Décisions exécutées dans le mois",
            "valeur": str(executees),
            "variation": mesures.variation(float(executees), float(executees_avant)),
            "favorable": executees >= executees_avant,
        },
        {
            "libelle": "Productions déposées à l'échéance",
            "valeur": f"{ponctualite} %" if ponctualite is not None else "Non mesuré",
            "variation": None,
            "favorable": None if ponctualite is None else ponctualite >= 85,
        },
        {
            "libelle": "Traitement du courrier",
            "valeur": "Non mesuré",
            "variation": None,
            "favorable": None,
        },
    ]


def _extremes(classement: list[dict], *, debut: bool) -> list[dict]:
    """
    Les trois premieres ou les trois dernieres du classement.

    Trois et non cinq : sur un ecran qui ne defile pas, la quatrieme ligne
    chasse une alerte — et une alerte vaut mieux qu'un rang de plus.
    """
    lignes = classement if debut else list(reversed(classement))
    return [
        {"sigle": ligne["structureSigle"], "score": ligne["scoreGlobal"], "feu": ligne["feu"]}
        for ligne in lignes[:3]
    ]

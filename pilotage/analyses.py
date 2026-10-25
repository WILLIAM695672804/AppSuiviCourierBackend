"""
Statistiques annuelles et analyses croisees — §3.11.

« Exploiter l'entrepot de donnees consolide pour produire des analyses croisees
entre execution des activites, traitement du courrier, avancement des dossiers
et respect des delais. »

**Trois des quatre mesures existent.** Le pilier dossiers est en service ;
seul le courrier ne l'est pas, et sa mesure sort a `null` — l'ecran affiche
« non mesuré ». **La dispersion et les moyennes ne portent que sur les mesures
disponibles** — c'est la meme renormalisation que la matrice applique a ses
poids (ADR 010), et pour la meme raison : un zero de plus aurait rendu toute
l'institution mediocre, avec un ecart-type rassurant et faux.

Le controleur de gestion ne cherche pas un chiffre, il cherche un lien. D'ou une
ligne par structure portant les mesures ensemble, plutot que quatre ecrans qui
obligeraient a les rapprocher de tete — et des **constats** rediges par le
serveur : ce qu'on voit, jamais pourquoi.
"""

from datetime import date

from activite.modeles import Obligation
from noyau.calendrier import MOIS_COURTS, libelle_mois, mois_precedent
from noyau.feu import feu
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.organisation.tete import regrouper
from noyau.parametres.service import valeur as parametre
from noyau.perimetre.portee import structures_visibles
from performance.matrice import structures_classees
from pilotage import mesures

#: Seuil de respect des echeances attendu par l'institution, en pourcentage.
#: **Aucune source** : le front affichait 80 % en dur, il est desormais
#: administre. Voir A31 et la table `parametre`.
CLE_SEUIL_RESPECT = "pilotage.seuil_respect_echeances"
SEUIL_RESPECT_DEFAUT = 80


def seuil_respect() -> int:
    return int(parametre(CLE_SEUIL_RESPECT, SEUIL_RESPECT_DEFAUT))


# =====================================================================
#  Analyses croisees
# =====================================================================


def analyses(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict:
    """
    Les mesures des structures classees, cote a cote.

    Le perimetre ne filtre pas : comme le classement, l'analyse croisee n'a de
    sens que sur l'ensemble — comparer sa structure a elle-meme n'apprend rien.
    La derogation tient parce que la reponse n'expose que des agregats de
    structure, jamais un objet nominatif.
    """
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)

    lignes = [
        _ligne_croisee(porteuse, membres, jour)
        for porteuse, membres in regrouper(utilisateur, structures_classees())
    ]

    return {
        "periode": libelle_mois(annee, mois),
        "lignes": lignes,
        "moyennes": {
            "activites": _moyenne(lignes, "activites"),
            "courrier": _moyenne(lignes, "courrier"),
            "dossiers": _moyenne(lignes, "dossiers"),
            "delais": _moyenne(lignes, "delais"),
        },
        "constats": _constats(lignes),
    }


def _ligne_croisee(structure: Structure, perimetre: list[Structure], jour: date) -> dict:
    """
    Une ligne de l'analyse croisee.

    `structure` la nomme, `perimetre` la mesure : pour qui consolide, les
    chiffres d'une direction couvrent tout son sous-arbre. Ce sont des ratios
    de comptages — ils s'agregent, contrairement a un score.
    """
    a_l_heure, total = mesures.activites_a_l_heure(perimetre, a_la_date=jour)
    activites = round(a_l_heure / total * 100, 1) if total else None

    a_temps, echues = mesures.ponctualite_obligations(perimetre)
    delais = round(a_temps / echues * 100, 1) if echues else None

    courrier = mesures.traitement_courrier(perimetre)
    dossiers = mesures.instruction_dossiers(perimetre)

    disponibles = [m for m in (activites, courrier, dossiers, delais) if m is not None]

    return {
        "sigle": structure.code,
        "libelle": structure.libelle,
        "activites": activites,
        "courrier": courrier,
        "dossiers": dossiers,
        "delais": delais,
        # Le feu porte sur la moyenne des mesures disponibles : une structure
        # dont on ne mesure qu'un axe ne doit pas paraitre plus sure qu'une
        # autre dont on en mesure quatre — mais elle ne doit pas non plus
        # paraitre en alerte pour ce qu'on ne sait pas.
        "feu": feu(round(sum(disponibles) / len(disponibles), 1) if disponibles else None),
        # L'ecart entre la meilleure et la moins bonne des mesures
        # **disponibles**. Zero quand il n'en reste qu'une : il n'y a alors
        # aucune dispersion a constater, et non une dispersion nulle.
        "dispersion": round(max(disponibles) - min(disponibles), 1) if len(disponibles) > 1 else 0,
    }


def _moyenne(lignes: list[dict], champ: str) -> float | None:
    valeurs = [ligne[champ] for ligne in lignes if ligne[champ] is not None]
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else None


def _constats(lignes: list[dict]) -> list[dict]:
    """
    Ce que les donnees montrent, formule par le serveur.

    Les constats **decrivent**, ils n'expliquent pas : « DSI est la seule
    structure dont les deux mesures divergent de plus de trente points » est un
    constat ; « la DSI privilegie ses activites au detriment de ses rituels »
    est une interpretation, et elle ne revient pas a un programme.
    """
    constats: list[dict] = []
    mesurees = [ligne for ligne in lignes if ligne["activites"] is not None]

    if not mesurees:
        return [
            {
                "texte": (
                    "Aucune structure ne porte de mesure exploitable sur la période : "
                    "les plans d'actions n'ont pas d'activité commencée."
                ),
                "feu": "inconnu",
            }
        ]

    faibles = [ligne for ligne in mesurees if ligne["activites"] < 60]
    if faibles:
        constats.append(
            {
                "texte": (
                    ", ".join(ligne["sigle"] for ligne in faibles)
                    + f" {'mènent' if len(faibles) > 1 else 'mène'} moins de 60 % "
                    "de leurs activités à l'heure."
                ),
                "feu": "rouge",
            }
        )

    disperses = [ligne for ligne in lignes if ligne["dispersion"] >= 30]
    if disperses:
        constats.append(
            {
                "texte": (
                    ", ".join(ligne["sigle"] for ligne in disperses)
                    + f" {'présentent' if len(disperses) > 1 else 'présente'} plus de "
                    "30 points d'écart entre leurs mesures : la performance y est "
                    "inégale d'un axe à l'autre."
                ),
                "feu": "orange",
            }
        )

    retard_rituels = [
        ligne
        for ligne in lignes
        if ligne["delais"] is not None and ligne["delais"] < seuil_respect()
    ]
    if retard_rituels:
        constats.append(
            {
                "texte": (
                    f"{len(retard_rituels)} structure{'s' if len(retard_rituels) > 1 else ''} "
                    f"{'restent' if len(retard_rituels) > 1 else 'reste'} sous le seuil de "
                    f"{seuil_respect()} % de dépôts à l'échéance."
                ),
                "feu": "orange",
            }
        )

    sans_dossiers = [ligne for ligne in lignes if ligne["dossiers"] is None]
    if sans_dossiers:
        constats.append(
            {
                "texte": (
                    f"{len(sans_dossiers)} structure(s) n'ont clos aucun dossier sur la "
                    "période : leur taux d'instruction n'est pas mesuré, ce qui n'est pas "
                    "un taux de zéro."
                ),
                "feu": "inconnu",
            }
        )

    constats.append(
        {
            "texte": (
                "Le traitement du courrier n'est pas mesuré : les analyses croisées "
                "portent sur trois axes au lieu de quatre."
            ),
            "feu": "inconnu",
        }
    )
    return constats


# =====================================================================
#  Statistiques annuelles
# =====================================================================


def statistiques(
    utilisateur: Utilisateur,
    *,
    annee: int | None = None,
    structure: str = "",
    aujourd_hui: date | None = None,
) -> dict:
    """
    La tendance de l'annee, structure par structure.

    Le tableau de bord montre l'etat du jour ; les statistiques montrent la
    tendance. Le tableau « respect des echeances par structure » est celui qui
    sera lu en reunion de direction : chaque ligne engage un responsable, d'ou
    la comparaison au seuil attendu plutot qu'un chiffre nu.

    **Filtre au perimetre**, contrairement aux analyses croisees : les
    statistiques descendent au detail d'une structure, et le §3.5 interdit au
    point focal de voir celles des autres.
    """
    jour = aujourd_hui or date.today()
    exercice = annee or jour.year

    accessibles = _structures_du_perimetre(utilisateur)
    if structure:
        accessibles = [s for s in accessibles if s.code == structure or str(s.pk) == structure]

    return {
        "annee": exercice,
        "seuilAttendu": seuil_respect(),
        "indicateurs": _indicateurs_annuels(accessibles, exercice, jour),
        "parMois": _par_mois(accessibles, exercice),
        "parStructure": [
            _ligne_structure(porteuse, membres, exercice)
            for porteuse, membres in regrouper(utilisateur, accessibles)
        ],
        # Les deux lignes courrier ont quitte cette liste le 27 aout 2026 : le
        # volume et le delai moyen se mesurent, et ils ont leur indicateur.
        "nonMesure": [],
    }


def _structures_du_perimetre(utilisateur: Utilisateur) -> list[Structure]:
    visibles = structures_visibles(utilisateur)
    if visibles is None:
        return list(Structure.objects.en_vigueur().order_by("code"))
    return list(visibles.order_by("code"))


def _indicateurs_annuels(structures: list[Structure], annee: int, jour: date) -> list[dict]:
    """
    Les quatre chiffres qui ouvrent l'ecran, avec leur evolution reelle.

    L'evolution est calculee contre l'annee precedente, et sort a `null` quand
    celle-ci n'a pas de mesure. La page affichait jusqu'ici « ▲ 11,2 % » ecrit
    en dur : un chiffre invente qu'aucune donnee ne soutenait.
    """
    execution = mesures.execution_activites(structures, a_la_date=jour)
    a_temps, echues = mesures.ponctualite_obligations(structures)
    respect = round(a_temps / echues * 100, 1) if echues else None
    ecart = _ecart_moyen_depot(structures, annee)
    executees = sum(mesures.decisions_executees(annee, mois, structures) for mois in range(1, 13))

    premier, dernier = date(annee, 1, 1), date(annee, 12, 31)
    enregistres = mesures.courriers_enregistres(premier, dernier, structures)
    delai = mesures.delai_moyen_courrier(premier, dernier, structures)

    return [
        {
            "libelle": "Exécution des activités",
            "valeur": f"{execution} %" if execution is not None else "Non mesuré",
            "note": "moyenne des avancements calculés",
            "feu": feu(execution),
        },
        {
            # Le volume de l'exercice entier, du 1er janvier au 31 decembre :
            # ces statistiques sont annuelles, contrairement au tableau de bord.
            "libelle": "Courriers enregistrés",
            "valeur": str(enregistres),
            "note": (
                f"délai moyen de traitement : {delai} jour(s)"
                if delai is not None
                else f"sur l'exercice {annee}"
            ),
            "feu": "inconnu",
        },
        {
            "libelle": "Respect des échéances",
            "valeur": f"{respect} %" if respect is not None else "Non mesuré",
            "note": f"seuil attendu {seuil_respect()} %",
            "feu": feu(respect),
        },
        {
            "libelle": "Avance moyenne au dépôt",
            "valeur": f"{ecart} j" if ecart is not None else "Non mesuré",
            "note": "jours entre le dépôt et l'échéance ; négatif = en retard",
            "feu": "inconnu" if ecart is None else "vert" if ecart >= 0 else "rouge",
        },
        {
            "libelle": "Décisions exécutées",
            "valeur": str(executees),
            "note": f"sur l'exercice {annee}",
            "feu": "inconnu",
        },
    ]


def _ecart_moyen_depot(structures: list[Structure], annee: int) -> float | None:
    """
    Jours moyens entre le depot et l'echeance. Positif : en avance.

    Ne porte que sur les obligations **deposees** : une obligation jamais
    deposee n'a pas de delai, elle a un manquement, et le compter comme un
    retard de N jours aurait fait dependre le chiffre de la date de lecture.
    """
    deposees = Obligation.objects.filter(
        structure__in=structures, echeance__year=annee, depose_le__isnull=False
    ).values_list("depose_le", "echeance")

    # `depose_le` est filtre non nul juste au-dessus ; le test est ici pour le
    # verificateur de types, qui ne lit pas le filtre.
    ecarts = [
        (echeance - depose_le).days for depose_le, echeance in deposees if depose_le is not None
    ]
    return round(sum(ecarts) / len(ecarts), 1) if ecarts else None


def _par_mois(structures: list[Structure], annee: int) -> list[dict]:
    """
    Deux series mensuelles : ce qui est du et ce qui est fait.

    Les « arrivés / départs » du courrier n'existent pas ; ce qui les remplace
    est ce que l'application mesure vraiment — les productions attendues et les
    decisions executees.
    """
    serie = []
    for mois in range(1, 13):
        obligations = Obligation.objects.filter(
            structure__in=structures, echeance__year=annee, echeance__month=mois
        )
        serie.append(
            {
                "mois": MOIS_COURTS[mois - 1],
                "attendues": obligations.count(),
                "deposees": obligations.filter(depose_le__isnull=False).count(),
                "decisionsExecutees": mesures.decisions_executees(annee, mois, structures),
            }
        )
    return serie


def _ligne_structure(structure: Structure, perimetre: list[Structure], annee: int) -> dict:
    """
    `structure` nomme la ligne, `perimetre` la mesure — voir `_ligne_croisee`.
    """
    obligations = Obligation.objects.filter(structure__in=perimetre, echeance__year=annee)
    echues = obligations.filter(echeance__lte=date.today())
    total = echues.count()
    a_temps = sum(
        1
        for depose_le, echeance in echues.values_list("depose_le", "echeance")
        if depose_le is not None and depose_le <= echeance
    )
    respect = round(a_temps / total * 100, 1) if total else None

    return {
        "structure": structure.libelle,
        "sigle": structure.code,
        "volume": obligations.count(),
        "ecartMoyen": _ecart_moyen_depot(perimetre, annee),
        "respect": respect,
        "feu": feu(respect),
    }

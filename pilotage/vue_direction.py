"""
La vue d'ensemble du Directeur general — §3.1.

Le cockpit repond a « qu'est-ce qui appelle une decision ce matin ? ». Cet
ecran-ci repond a « ou en est l'institution ce trimestre ? ». D'ou **cinq
graphiques, aucun tableau, aucune action** : ce qui se decide se decide au
cockpit, ce qui se comprend se comprend ici. Melanger les deux aurait produit un
ecran qu'on ne sait plus quand ouvrir.

La cote du chenal n'y figure plus : elle disait l'etat d'un ouvrage, pas celui
de l'institution, et elle se lit entiere dans `/exploitation`. La place revient
au bilan de disponibilite — les activites en retard et les decisions non
executees ont souvent la meme cause, et elle tient en une ligne : le
responsable n'etait pas la, et personne ne le remplacait.

Trois blocs viennent d'ailleurs que des piliers de suivi : les recouvrements,
la cote du chenal, et la disponibilite des agents. Ils sont **nullables**, et
pour deux raisons distinctes qui se ressemblent a l'ecran :

 * la session ne porte pas la permission qui les ouvre — `EXP_LEC` pour les
   deux premiers, `DISPO` pour le troisieme ;
 * rien n'a ete saisi — il n'y a rien a lire.

Dans les deux cas le bloc sort a `null` plutot qu'a zero. Une cote a zero
signifierait que le chenal est comble ; un taux de recouvrement a zero
signifierait que rien n'a ete encaisse. Ni l'un ni l'autre n'est ce qu'on veut
dire (ADR 011).
"""

from datetime import date

from django.utils import timezone

from activite.modeles import Obligation
from exploitation import lecture as exploitation
from exploitation.modeles import PointChenal, SecteurRecouvrement
from gouvernance import lecture as gouvernance
from noyau.calendrier import MOIS_COURTS, libelle_mois, mois_precedent
from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from performance import matrice as calcul
from performance.matrice import structures_classees
from pilotage import mesures

INSTITUTION = "Port autonome de Douala"

#: Cinq lignes au plus dans un histogramme de repartition. Au-dela, les barres
#: deviennent illisibles et le lecteur ne retient rien.
PLAFOND_PARTS = 5


def vue_ensemble(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict:
    """L'ecran entier du Directeur general."""
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)
    serie = mesures.mois_glissants(annee, mois, 12)

    return {
        "institution": INSTITUTION,
        # ISO, et non « 16 aout 2026 » : le front applique `formaterDateHeure`
        # a ce champ, et `new Date("16 aout 2026")` rend une date invalide qui
        # fait tomber l'ecran entier. Un mois ecrit en toutes lettres n'est pas
        # une donnee, c'est un affichage — et l'affichage appartient au front.
        # Voir docs/pieges.md.
        "actualiseLe": timezone.now().isoformat(),
        "exercice": f"Exercice {jour.year}",
        "reperes": _reperes(utilisateur, jour, annee, mois),
        "ecartExecution": _ecart_execution(serie),
        "executionParStructure": _execution_par_structure(jour),
        "retardsParStructure": _retards_par_structure(jour),
        "respectDelais": _respect_delais(serie),
        "decisionsExecutees": _decisions_executees(serie),
        "disponibilite": _disponibilite(utilisateur, jour),
        "chenal": _chenal(utilisateur),
        "recouvrements": _recouvrements(utilisateur, annee, mois),
    }


# =====================================================================
#  La bande haute
# =====================================================================


def _reperes(utilisateur: Utilisateur, jour: date, annee: int, mois: int) -> list[dict]:
    """
    Sept reperes au plus : au-dela, on ne lit plus.

    « Non mesuré » occupe une ligne entiere plutot que de disparaitre : le
    Directeur general doit savoir ce que son tableau de bord ne lui dit pas.
    """
    execution = mesures.execution_activites(a_la_date=jour)
    a_temps, echues = mesures.ponctualite_obligations()
    respect = round(a_temps / echues * 100, 1) if echues else None
    classement = calcul.matrice(utilisateur, annee, mois)["lignes"]

    debut, fin = calcul.bornes(annee, mois)
    courrier, dans_le_delai, clos = mesures.courrier_dans_le_delai(debut, fin)
    moyenne = (
        round(sum(ligne["scoreGlobal"] for ligne in classement) / len(classement), 1)
        if classement
        else None
    )

    return [
        {
            "libelle": "Exécution des activités",
            "valeur": f"{execution} %" if execution is not None else "Non mesuré",
            "note": "moyenne des avancements calculés",
        },
        {
            "libelle": "Score moyen des structures",
            "valeur": f"{moyenne} / 100" if moyenne is not None else "Non mesuré",
            "note": libelle_mois(annee, mois),
        },
        {
            "libelle": "Productions à l'échéance",
            "valeur": f"{respect} %" if respect is not None else "Non mesuré",
            "note": f"{a_temps} sur {echues} échues" if echues else "aucune échéance passée",
        },
        {
            "libelle": "Décisions en retard",
            "valeur": str(mesures.decisions_en_retard()),
            "note": "échéance dépassée, décision non exécutée",
        },
        {
            "libelle": "Activités critiques",
            "valeur": str(mesures.activites_critiques()),
            "note": "en retard et sous contrainte échue (§20)",
        },
        {
            "libelle": "Responsables absents sans intérim",
            "valeur": str(mesures.absences_sans_interim(jour)),
            "note": "les dossiers de leur structure n'avancent pas",
        },
        {
            # Mesure depuis le 27 aout 2026. Ce repere affichait « Non mesuré »
            # depuis l'origine : le courrier n'avait pas de cloture, donc pas de
            # fin, donc pas de delai a comparer.
            "libelle": "Courriers traités dans le délai",
            "valeur": f"{courrier} %" if courrier is not None else "Non mesuré",
            "note": (
                f"{dans_le_delai} sur {clos} courrier(s) clôturé(s) en {libelle_mois(annee, mois)}"
                if clos
                else mesures.SANS_COURRIER_CLOS
            ),
        },
    ]


# =====================================================================
#  Les cinq graphiques
# =====================================================================


def _ecart_execution(serie: list[tuple[int, int]]) -> list[dict]:
    """
    La variation mensuelle du taux d'execution, en points.

    Le seul graphique de l'ecran dont l'axe traverse le zero : une variation se
    lit par rapport a rien, pas par rapport a zero pour cent. Un mois dont la
    mesure ou celle du mois precedent manque ne produit **aucun point** — le
    tracer a zero aurait dessine une stabilite qu'on n'a pas constatee.
    """
    points: list[dict] = []
    for annee, mois in serie:
        avant_annee, avant_mois = mois_precedent(annee, mois)
        courant = mesures.execution_mensuelle(annee, mois)
        avant = mesures.execution_mensuelle(avant_annee, avant_mois)
        if courant is None or avant is None:
            continue
        points.append({"mois": MOIS_COURTS[mois - 1], "valeur": round(courant - avant, 1)})
    return points


def _execution_par_structure(jour: date) -> list[dict]:
    """Les cinq structures dont l'execution est la plus forte."""
    lignes: list[dict[str, float | str]] = []
    for structure in structures_classees():
        execution = mesures.execution_activites([structure], a_la_date=jour)
        if execution is not None:
            lignes.append({"libelle": structure.code, "valeur": execution})

    lignes.sort(key=lambda ligne: float(ligne["valeur"]), reverse=True)
    return lignes[:PLAFOND_PARTS]


def _retards_par_structure(jour: date) -> list[dict]:
    """
    Les cinq structures qui portent le plus de productions en retard.

    Les structures sans retard sont absentes de l'histogramme, et non a zero :
    un histogramme de retards ne se lit que par ce qu'il montre.
    """
    lignes: list[dict[str, float | str]] = []
    for structure in structures_classees():
        retards = Obligation.objects.filter(
            structure=structure, depose_le__isnull=True, echeance__lt=jour
        ).count()
        if retards:
            lignes.append({"libelle": structure.code, "valeur": retards})

    lignes.sort(key=lambda ligne: float(ligne["valeur"]), reverse=True)
    return lignes[:PLAFOND_PARTS]


def _respect_delais(serie: list[tuple[int, int]]) -> list[dict]:
    """
    Part des productions du mois deposees a l'echeance.

    Un mois sans obligation echue ne produit pas de point : zero pour cent
    aurait dit que rien n'a ete depose, quand rien n'etait attendu.
    """
    points = []
    for annee, mois in serie:
        a_temps, echues = mesures.ponctualite_obligations(annee=annee, mois=mois)
        if echues:
            points.append(
                {"mois": MOIS_COURTS[mois - 1], "valeur": round(a_temps / echues * 100, 1)}
            )
    return points


def _decisions_executees(serie: list[tuple[int, int]]) -> list[dict]:
    """
    Les decisions d'instance executees dans le mois.

    Ici zero est une mesure : « aucune decision executee en juin » se constate,
    et c'est meme le constat qui compte.
    """
    return [
        {"mois": MOIS_COURTS[mois - 1], "valeur": mesures.decisions_executees(annee, mois)}
        for annee, mois in serie
    ]


# =====================================================================
#  L'etat du port
# =====================================================================


def _disponibilite(utilisateur: Utilisateur, jour: date) -> dict | None:
    """
    L'effectif reellement disponible ce matin.

    Le Directeur general lit ici ce qu'aucun autre bloc ne dit : les activites
    en retard et les decisions non executees ont souvent la meme cause, et elle
    tient en une ligne — le responsable n'etait pas la, et personne ne le
    remplacait.

    La garde est `DISPO` et non `VUE_DG` : la route entiere exige deja `VUE_DG`,
    mais le nom des absents releve d'une autre permission. Un bloc absent ne
    fuit pas ; un bloc masque a l'affichage, si.
    """
    if not possede(utilisateur, PERM.DISPO):
        return None
    return gouvernance.bilan_disponibilite(utilisateur, jour)


def _chenal(utilisateur: Utilisateur) -> dict | None:
    """
    La cote du point critique, celle qui borne l'acces au port.

    Le point critique et non la moyenne des points : un navire passe par le
    moins profond, pas par le moyen.
    """
    if not possede(utilisateur, PERM.EXP_LEC):
        return None

    etat = exploitation.etat_chenal(PointChenal.objects.filter(actif=True))
    if not etat["releves"]:
        return None

    critique = min(etat["releves"], key=lambda ligne: ligne["ecart"])
    return {
        "point": critique["point"],
        "cote": critique["cote"],
        "garantie": critique["garantie"],
        "ecart": critique["ecart"],
        "feu": critique["feu"],
        "releveLe": critique["releveLe"],
        "evolution": etat["evolution"],
    }


def _recouvrements(utilisateur: Utilisateur, annee: int, mois: int) -> dict | None:
    """Ce qui a ete encaisse dans le mois, avec la coupure exploitation / reste."""
    if not possede(utilisateur, PERM.EXP_LEC):
        return None

    etat = exploitation.etat_recouvrements(
        SecteurRecouvrement.objects.filter(actif=True), annee, mois
    )
    if not etat["lignes"]:
        return None

    return {
        "periode": etat["periode"],
        "tauxGlobal": etat["tauxGlobal"],
        "totalRecouvre": etat["totalRecouvre"],
        "totalExploitation": etat["totalExploitation"],
        "totalAutresRecettes": etat["totalAutresRecettes"],
        "parSecteur": [
            {"libelle": ligne["secteurCode"], "valeur": ligne["taux"]}
            for ligne in etat["lignes"][:PLAFOND_PARTS]
        ],
    }

"""
Le suivi des indicateurs cibles du programme — §3.11 et §9 du BRD.

« Suivre les indicateurs cibles du programme et leur evolution N vs N-1. »

Chaque ligne porte trois valeurs : l'annee en cours, l'annee passee, et la
cible. Sans l'annee passee, une valeur ne dit pas si l'on progresse ; sans la
cible, elle ne dit pas si cela suffit.

**Deux origines pour une valeur, dans cet ordre :**

 1. une mesure **rapportee** (`MesureProgramme`), si elle existe pour l'annee ;
 2. sinon, une mesure **calculee** par l'application, quand elle sait la
    calculer.

La mesure rapportee prime, et c'est deliberé : c'est le rapporteur qui engage sa
signature devant l'instance, pas le serveur. Le jour ou les deux divergent,
c'est un ecart a expliquer, pas un bug a corriger en silence.

Un indicateur que personne ne rapporte et que l'application ne sait pas calculer
sort a `null` — « non mesuré », jamais zero. C'est la distinction que le §3.11
demande de tenir entre « nous n'avons pas atteint la cible » et « nous ne savons
pas ou nous en sommes ».
"""

from collections.abc import Callable
from datetime import date

from pilotage import mesures
from pilotage.modeles import IndicateurProgramme, MesureProgramme


def _execution_activites(annee: int) -> float | None:
    """Sur l'exercice : l'etat au 31 decembre, ou aujourd'hui si l'annee court."""
    return mesures.execution_activites(a_la_date=_fin_exercice(annee))


def _ponctualite(annee: int) -> float | None:
    """Les obligations de l'exercice deposees a l'echeance, en pourcentage."""
    a_temps, echues = mesures.ponctualite_obligations(annee=annee)
    # Aucune obligation echue dans l'exercice : rien a mesurer, et surtout pas
    # zero pour cent.
    return round(a_temps / echues * 100, 1) if echues else None


def _decisions_executees(annee: int) -> float | None:
    """
    Les decisions executees dans l'exercice — un decompte, pas un taux.

    Zero est ici une mesure legitime : « aucune decision executee » se constate,
    contrairement a une moyenne sur zero ligne.
    """
    return float(sum(mesures.decisions_executees(annee, mois) for mois in range(1, 13)))


def _fin_exercice(annee: int) -> date:
    """Le 31 decembre, ou aujourd'hui quand l'exercice n'est pas termine."""
    aujourd_hui = date.today()
    return aujourd_hui if annee >= aujourd_hui.year else date(annee, 12, 31)


#: Les indicateurs que l'application sait calculer, par code. Ceux qui n'y
#: figurent pas attendent une mesure rapportee — et disent « non mesuré » tant
#: qu'elle n'est pas venue.
CALCULS: dict[str, Callable[[int], float | None]] = {
    "PROG-ACT": _execution_activites,
    "PROG-RIT": _ponctualite,
    "PROG-DEC": _decisions_executees,
}


def programme(annee: int | None = None) -> dict:
    """Les indicateurs du programme pour l'exercice, avec l'annee precedente."""
    exercice = annee or date.today().year
    indicateurs = list(IndicateurProgramme.objects.filter(actif=True))
    rapportees = _mesures_rapportees(indicateurs, exercice)

    lignes = [_ligne(indicateur, exercice, rapportees) for indicateur in indicateurs]

    return {
        "annee": exercice,
        "indicateurs": lignes,
        "compteurs": _compteurs(lignes),
    }


def _mesures_rapportees(
    indicateurs: list[IndicateurProgramme], exercice: int
) -> dict[tuple[int, int], float]:
    """Les valeurs saisies pour l'exercice et le precedent, en une requete."""
    lignes = MesureProgramme.objects.filter(
        indicateur__in=indicateurs, annee__in=[exercice, exercice - 1]
    )
    return {(ligne.indicateur_id, ligne.annee): float(ligne.valeur) for ligne in lignes}


def _valeur(
    indicateur: IndicateurProgramme, annee: int, rapportees: dict[tuple[int, int], float]
) -> float | None:
    rapportee = rapportees.get((indicateur.pk, annee))
    if rapportee is not None:
        return rapportee

    calcul = CALCULS.get(indicateur.code)
    return calcul(annee) if calcul else None


def _ligne(
    indicateur: IndicateurProgramme, exercice: int, rapportees: dict[tuple[int, int], float]
) -> dict:
    valeur_n = _valeur(indicateur, exercice, rapportees)
    valeur_n1 = _valeur(indicateur, exercice - 1, rapportees)
    cible = float(indicateur.cible) if indicateur.cible is not None else None

    return {
        "code": indicateur.code,
        "libelle": indicateur.libelle,
        "modeCalcul": indicateur.mode_calcul,
        "source": indicateur.source,
        "unite": indicateur.unite,
        "valeurN": valeur_n,
        "valeurN1": valeur_n1,
        "cible": cible,
        "cibleMaximum": indicateur.cible_maximum,
        "echeance": indicateur.echeance,
        "feu": _feu(valeur_n, cible, indicateur.cible_maximum),
    }


def _feu(valeur: float | None, cible: float | None, maximum: bool) -> str:
    """
    La couleur d'un indicateur du programme.

    « Inconnu » dans deux cas distincts et volontairement confondus a l'ecran :
    aucune valeur, ou aucune cible. Une valeur sans cible ne se juge pas — c'est
    le sens meme d'un indicateur **cible**, et la colorer en vert parce qu'elle
    parait bonne aurait invente l'engagement que le programme n'a pas fixe.

    Le seuil de 90 % de la cible pour l'orange n'a pas de source : il est le
    meme dans les deux sens, et il est le seul choix arbitraire de cette
    fonction. Voir A32.
    """
    if valeur is None or cible is None or cible == 0:
        return "inconnu"

    part = valeur / cible * 100
    if maximum:
        # La cible est un plafond : plus on est bas, mieux c'est.
        if valeur <= cible:
            return "vert"
        return "orange" if part <= 110 else "rouge"

    if valeur >= cible:
        return "vert"
    return "orange" if part >= 90 else "rouge"


def _compteurs(lignes: list[dict]) -> list[dict]:
    """
    Ce que la liste dit d'elle-meme.

    Le compteur des indicateurs non mesures est le premier, et c'est voulu : un
    tableau de bord du programme ou la moitie des lignes est vide doit
    l'annoncer avant d'annoncer ses reussites.
    """
    non_mesures = [ligne for ligne in lignes if ligne["valeurN"] is None]
    sans_cible = [ligne for ligne in lignes if ligne["cible"] is None]
    atteints = [ligne for ligne in lignes if ligne["feu"] == "vert"]

    return [
        {
            "libelle": "Indicateurs non mesurés",
            "valeur": len(non_mesures),
            "note": "aucune valeur rapportée ni calculable",
            "feu": "inconnu" if non_mesures else "vert",
        },
        {
            "libelle": "Indicateurs sans cible",
            "valeur": len(sans_cible),
            "note": "la cible n'a pas été fixée",
            "feu": "inconnu" if sans_cible else "vert",
        },
        {
            "libelle": "Cibles atteintes",
            "valeur": len(atteints),
            "note": f"sur {len(lignes)} indicateurs du programme",
            "feu": "vert" if atteints else "inconnu",
        },
    ]

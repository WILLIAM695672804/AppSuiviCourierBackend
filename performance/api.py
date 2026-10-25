"""
Routes de la performance — `/api/performance/*`.

Quatre lectures et deux ecritures, avec deux gardes distinctes :

 * `SCORE` en lecture. Le classement est une information de pilotage : un
   directeur doit voir ou se situe sa structure, sinon la matrice ne corrige
   rien.
 * `SCORE_ADM` en ecriture. Definir un indicateur ou inscrire une production,
   c'est changer la **regle de mesure** de tout le monde. Ce n'est pas le meme
   geste, donc pas la meme permission.

`restreindre()` n'est pas appele : le classement porte sur toutes les
structures classees, et c'est le point. Un classement filtre au
perimetre ne serait pas un classement — chacun se verrait premier. Cette
derogation tient parce que la matrice n'expose que des agregats de structure,
jamais un objet nominatif.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from datetime import date

from ninja import Router

from noyau.erreurs import HorsPerimetre
from noyau.habilitation.dependances import PERM, exige
from performance import lecture, services
from performance import matrice as calcul
from performance.schemas import (
    Calendrier,
    Creation,
    Dictionnaire,
    FicheStructure,
    Matrice,
    SaisieIndicateur,
    SaisieProduction,
)

routeur = Router()


def _mois_par_defaut(annee: int | None, mois: int | None) -> tuple[int, int]:
    """
    La periode demandee, ou le mois courant.

    Le defaut est le mois **en cours** et non le dernier mois clos : la DSR
    ouvre l'ecran pour voir venir, et la reponse porte `provisoire` pour dire
    que le classement n'est pas encore comparable.
    """
    aujourd_hui = date.today()
    return (annee or aujourd_hui.year, mois or aujourd_hui.month)


@routeur.get("/matrice", response=Matrice, auth=exige(PERM.SCORE))
def matrice(request, annee: int | None = None, mois: int | None = None):
    """
    Le classement mensuel des structures — §2.

    Recalcule a chaque appel (ADR 010). Hors periode close, la reponse est
    annoncee `provisoire`.
    """
    annee, mois = _mois_par_defaut(annee, mois)
    return calcul.matrice(request.auth, annee, mois)


@routeur.get("/matrice/{sigle}", response=FicheStructure, auth=exige(PERM.SCORE))
def fiche_structure(request, sigle: str, annee: int | None = None, mois: int | None = None):
    """
    La decomposition du score d'une structure, critere par sous-indicateur.

    404 sur un sigle inconnu — pas de reponse vide qui se lirait comme un score
    de zero.
    """
    annee, mois = _mois_par_defaut(annee, mois)
    fiche = calcul.fiche(request.auth, sigle, annee, mois)
    if fiche is None:
        raise HorsPerimetre("Structure introuvable ou non classée.")
    return fiche


@routeur.get("/dictionnaire", response=Dictionnaire, auth=exige(PERM.SCORE))
def dictionnaire(request):
    """Definition, formule, source, periodicite, responsable — §3.3."""
    return lecture.dictionnaire()


@routeur.get("/calendrier", response=Calendrier, auth=exige(PERM.SCORE))
def calendrier(request):
    """Qui alimente quoi, a quelle frequence, et ce qui est arrive au dernier
    cycle clos — §3.3."""
    return lecture.calendrier()


@routeur.post("/indicateurs", response={201: Creation}, auth=exige(PERM.SCORE_ADM))
def creer_indicateur(request, saisie: SaisieIndicateur):
    """Ajoute une entree au dictionnaire. Le code doit etre libre."""
    indicateur = services.creer_indicateur(
        request.auth,
        code=saisie.code,
        libelle=saisie.libelle,
        definition=saisie.definition,
        formule=saisie.formule,
        source=saisie.source,
        periodicite=saisie.periodicite,
        responsable=saisie.responsable,
        unite=saisie.unite,
        seuil_vert=saisie.seuilVert,
        seuil_orange=saisie.seuilOrange,
        critere=saisie.critere,
    )
    return 201, {"id": indicateur.pk}


@routeur.post("/calendrier", response={201: Creation}, auth=exige(PERM.SCORE_ADM))
def ajouter_production(request, saisie: SaisieProduction):
    """
    Inscrit une production au calendrier officiel.

    Une ligne est ouverte **par structure classee** : ni le nombre de
    structures ni le responsable ne se saisissent, ils decoulent du
    referentiel. Voir `services.ajouter_production`.
    """
    ligne = services.ajouter_production(
        request.auth,
        production=saisie.production,
        nature=saisie.nature,
        periodicite=saisie.periodicite,
        echeance=saisie.echeance,
        relance_automatique=saisie.relanceAutomatique,
        jours_avant_relance=saisie.joursAvantRelance,
    )
    return 201, {"id": ligne.pk}

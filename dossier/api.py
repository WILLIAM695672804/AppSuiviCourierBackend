"""
Routes des dossiers a instruire — `/api/dossiers/*`.

Trois gardes, et la coupure n'est pas celle qu'on attend :

 * `DOS_LEC` en lecture. Le registre et la fiche.
 * `DOS_INS` pour l'ouverture, le complement et la fusion — les gestes de
   l'instruction.
 * `DOS_INS` **ou** `DOS_VAL` pour le retour a une etape anterieure. Le §3.7
   confie explicitement ce geste a l'agent instructeur ; le reserver au
   validateur laissait l'instructeur sans recours devant un dossier mal
   oriente — il ne pouvait que le garder ou le clore. Le motif obligatoire et
   la trace s'appliquent aux deux de la meme maniere.

**La garde ne filtre pas le contenu.** Elle dit qui entre ; ce que chacun voit
est decide par `restreindre()` dans `lecture.py`, avec `champ_agent` pour la
portee `propre`. L'oubli de `restreindre()` ne produit aucune erreur — juste
une fuite.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from dossier import lecture, services
from dossier.schemas import (
    Bibliotheque,
    CourrierFusionne,
    Creation,
    DossierDetail,
    RegistreDossiers,
    SaisieComplement,
    SaisieDossier,
    SaisieFusion,
    SaisieRetour,
)
from noyau.habilitation.dependances import PERM, exige

routeur = Router()


# =====================================================================
#  Lectures
# =====================================================================


@routeur.get("", response=RegistreDossiers, auth=exige(PERM.DOS_LEC))
def registre(request, etape: str = "", etat: str = ""):
    """
    Le registre des dossiers a instruire — §3.7.

    Les filtres arrivent avec les libelles de l'ecran. Un libelle inconnu ne
    filtre rien plutot que de vider la liste : un filtre mal orthographie qui
    vide l'ecran se lit comme une panne.
    """
    return lecture.registre(request.auth, etape=etape, etat=etat)


@routeur.get("/modeles", response=Bibliotheque, auth=exige(PERM.DOS_LEC))
def modeles(request):
    """
    La bibliotheque des courriers-type — RF-SUI-05.

    Declaree **avant** `/{identifiant}` : sans cela, django-ninja aurait tente
    de lire « modeles » comme un identifiant de dossier et rendu une erreur de
    validation la ou l'agent attend une liste.
    """
    return lecture.modeles()


@routeur.get("/{int:identifiant}", response=DossierDetail, auth=exige(PERM.DOS_LEC))
def fiche(request, identifiant: int):
    """
    La fiche d'instruction — circuit complet, regle d'affectation, versions.

    Un dossier hors perimetre rend **404** et non 403 : repondre « vous n'avez
    pas le droit » confirmerait son existence et celle de son demandeur a qui
    n'a pas a les connaitre (D5).
    """
    return lecture.fiche(request.auth, identifiant)


# =====================================================================
#  Ecritures
# =====================================================================


@routeur.post("", response={201: Creation}, auth=exige(PERM.DOS_INS))
def ouvrir(request, saisie: SaisieDossier):
    """
    Ouvre un dossier, depuis un courrier entrant ou en depot direct — §3.6.

    Le courrier d'origine n'est qu'une reference : il poursuit son propre
    circuit, ouvrir un dossier ne le clot pas.
    """
    dossier = services.ouvrir(
        request.auth,
        type_dossier=saisie.type,
        objet=saisie.objet,
        demandeur=saisie.demandeur,
        echeance=saisie.echeance,
        contexte=saisie.contexte,
        criticite=saisie.criticite,
        montant=saisie.montant,
        courrier_id=saisie.courrierId or None,
        courrier_reference=saisie.courrierReference,
    )
    return 201, {"id": dossier.pk}


@routeur.post("/{int:identifiant}/complements", response={201: Creation}, auth=exige(PERM.DOS_INS))
def demander_complement(request, identifiant: int, saisie: SaisieComplement):
    """
    Reclame une piece au demandeur — **sans repousser l'echeance du dossier**.

    L'echeance saisie est celle donnee au demandeur. Les confondre offrirait a
    l'instructeur un moyen simple de n'etre jamais en retard.
    """
    complement = services.demander_complement(
        request.auth,
        dossier_id=identifiant,
        objet=saisie.objet,
        echeance=saisie.echeance,
    )
    return 201, {"id": complement.pk}


@routeur.post(
    "/{int:identifiant}/complements/{int:complement_id}/reception",
    response={201: Creation},
    auth=exige(PERM.DOS_INS),
)
def enregistrer_complement(request, identifiant: int, complement_id: int):
    """Note qu'une piece reclamee est arrivee."""
    complement = services.enregistrer_complement(
        request.auth, dossier_id=identifiant, complement_id=complement_id
    )
    return 201, {"id": complement.pk}


@routeur.post(
    "/{int:identifiant}/retour",
    response={201: Creation},
    auth=exige(PERM.DOS_INS, PERM.DOS_VAL),
)
def retourner(request, identifiant: int, saisie: SaisieRetour):
    """
    Fait remonter le dossier a une etape anterieure — RF-BPM-06.

    Motif obligatoire, et rien ne se perd de l'historique : le journal garde
    l'etape d'ou l'on vient et celle ou l'on retourne.
    """
    dossier = services.retourner(
        request.auth,
        dossier_id=identifiant,
        etape_cible=saisie.etapeCible,
        motif=saisie.motif,
    )
    return 201, {"id": dossier.pk}


@routeur.post(
    "/{int:identifiant}/fusion", response={201: CourrierFusionne}, auth=exige(PERM.DOS_INS)
)
def fusionner(request, identifiant: int, saisie: SaisieFusion):
    """
    Produit un projet de courrier depuis un modele — RF-SUI-05.

    Une variable non fournie **arrete** la fusion : laisser `{demandeur}` en
    clair dans un courrier signe par l'institution est le genre d'incident
    qu'on ne repare pas.
    """
    return 201, services.fusionner(
        request.auth,
        dossier_id=identifiant,
        modele_id=saisie.modeleId,
        valeurs=saisie.valeurs,
    )

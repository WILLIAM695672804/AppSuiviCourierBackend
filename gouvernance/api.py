"""
Routes du pilier gouvernance — `/api/gouvernance/*`.

**Chaque route declare la permission qu'elle exige, et rien ne se lit sans
passer par le perimetre.** L'oubli de `restreindre()` ne produit aucune erreur :
il montre a un agent la decision qui contraint une autre direction. Ici, aucune
route ne construit son filtre : les services de `lecture.py` partent tous de
`_engagements_visibles()` ou de `_seances_visibles()`.

Trois permissions, et le partage n'est pas arbitraire :

 * `DEC` — tenir le registre des decisions. Lecture **et** ecriture des
   engagements, quelle que soit leur origine (ADR 006) : prescriptions de
   filiales et recommandations externes sont des engagements.
 * `INST` — tenir le registre des reunions. Les seances et leurs documents.
 * `DISPO` — renseigner la disponibilite. Absences, et **planification des
   conges** : le directeur de tete de structure ouvre les droits et arbitre
   les periodes de tout son sous-arbre. C'est `DISPO` plus la portee qui borne
   pour qui, et non une permission de plus — ADR 002.

**Consigner un avancement releve de `DEC` et non d'une permission de structure** :
c'est la DSR qui tient le registre, et le service verifie ensuite que l'agent
declare bien pour une structure chargee. La garde de route dit qui entre ; le
service dit pour qui l'on parle.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from gouvernance import lecture, services
from gouvernance.schemas import (
    DecisionDetail,
    Identifiant,
    PlanningConges,
    RegistreDecisions,
    RegistreDisponibilites,
    RegistreSeances,
    SaisieAbsence,
    SaisieArbitrageConges,
    SaisieAvancement,
    SaisieDecision,
    SaisieDocument,
    SaisieDroitConges,
    SaisiePeriodeConges,
    SaisieRelance,
    SaisieSeance,
    SeanceDetail,
    SuiviFiliales,
    SuiviRepresentations,
    TableauDeBordGouvernance,
)
from noyau.habilitation.dependances import PERM, exige

routeur = Router()


# =====================================================================
#  Tableau de bord
# =====================================================================


@routeur.get("/tableau-de-bord", response=TableauDeBordGouvernance, auth=exige(PERM.DEC))
def tableau_de_bord(request):
    """
    Les trois registres en une seule vue — l'ecran d'accueil de la DSR.

    Agrege a la volee et non depuis `agregat_gouvernance_jour` : cet ecran doit
    refleter la relance partie il y a dix minutes.
    """
    return lecture.tableau_de_bord(request.auth)


# =====================================================================
#  Decisions
# =====================================================================


@routeur.get("/decisions", response=RegistreDecisions, auth=exige(PERM.DEC))
def decisions(request, instance: str = "", etat: str = ""):
    """
    Le registre des decisions d'instance.

    Les filtres affinent ce que le perimetre a deja borne. L'inverse laisserait
    un filtre vide montrer plus que le perimetre.
    """
    return lecture.registre_decisions(request.auth, instance=instance, etat=etat)


@routeur.get("/seances", response=RegistreSeances, auth=exige(PERM.INST))
def seances(request, type: str = ""):
    """
    Le registre des reunions et rapports.

    Le parametre s'appelle `type` et non `type_seance` : c'est le nom que le
    front emet dans sa chaine de requete, et le renommer ici obligerait a le
    corriger cote client le jour du branchement.
    """
    return lecture.registre_seances(request.auth, type_seance=type)


@routeur.get("/disponibilites", response=RegistreDisponibilites, auth=exige(PERM.DISPO))
def disponibilites(request, filtre: str = "", structure: str = ""):
    """
    Les absences — §3.3.

    Nominatif, et non plus borne aux seuls hauts responsables : le Directeur
    general et les chefs de structure portent `DISPO` depuis la migration 0024,
    et c'est le perimetre qui dit de qui.

    `structure` filtre par **tete** pour qui consolide — le code d'une
    direction, jamais d'un service.
    """
    return lecture.registre_disponibilites(request.auth, filtre=filtre, structure=structure)


@routeur.get("/filiales", response=SuiviFiliales, auth=exige(PERM.DEC))
def filiales(request):
    """L'amont — le dossier est-il pret — et l'aval — la prescription est-elle
    suivie d'effet."""
    return lecture.suivi_filiales(request.auth)


@routeur.get("/representations", response=SuiviRepresentations, auth=exige(PERM.DEC))
def representations(request):
    """Ou le PAD siege, qui l'y represente, et ce qui a ete recommande."""
    return lecture.suivi_representations(request.auth)


@routeur.get("/conges", response=PlanningConges, auth=exige(PERM.DISPO))
def conges(request, annee: int):
    """
    Le projet de planning annuel — a ne pas confondre avec le registre des
    absences : celui-ci arbitre des souhaits avant qu'ils ne le deviennent.
    """
    return lecture.planning_conges(request.auth, annee=annee)


@routeur.get("/decisions/{engagement_id}", response=DecisionDetail, auth=exige(PERM.DEC))
def fiche_decision(request, engagement_id: int):
    """
    La fiche complete.

    Declaree **apres** les chemins fixes de ce routeur : un chemin variable
    place avant eux capturerait « tableau-de-bord » comme identifiant.
    """
    return lecture.fiche_decision(request.auth, engagement_id)


@routeur.get("/seances/{seance_id}", response=SeanceDetail, auth=exige(PERM.INST))
def fiche_seance(request, seance_id: int):
    """La fiche complete d'une seance : ordre du jour, presents, documents."""
    return lecture.fiche_seance(request.auth, seance_id)


# =====================================================================
#  Ecritures
# =====================================================================


@routeur.post("/decisions", response=Identifiant, auth=exige(PERM.DEC))
def creer_decision(request, saisie: SaisieDecision):
    """La DSR consigne ce que l'instance a decide — §17."""
    return {"id": services.creer_engagement(request.auth, saisie).pk}


@routeur.post("/decisions/{engagement_id}/avancement", response=Identifiant, auth=exige(PERM.DEC))
def consigner_avancement(request, engagement_id: int, saisie: SaisieAvancement):
    """
    L'avancement declare par une structure chargee.

    Celui de la decision n'est **pas ecrit** : le declencheur en fait la moyenne.
    """
    return {"id": services.consigner_avancement(request.auth, engagement_id, saisie).pk}


@routeur.post("/decisions/{engagement_id}/relance", response=Identifiant, auth=exige(PERM.REL))
def relancer(request, engagement_id: int, saisie: SaisieRelance):
    """
    `REL` et non `DEC` : c'est l'escalade humaine du §1.1, et personne ne se
    relance soi-meme. Meme regle que la relance d'une activite.
    """
    return {"id": services.relancer(request.auth, engagement_id, saisie).pk}


@routeur.post("/seances", response=Identifiant, auth=exige(PERM.INST))
def creer_seance(request, saisie: SaisieSeance):
    return {"id": services.creer_seance(request.auth, saisie).pk}


@routeur.post("/seances/{seance_id}/documents", response=Identifiant, auth=exige(PERM.INST))
def deposer_document(request, seance_id: int, saisie: SaisieDocument):
    """Le depot d'une piece de seance. Un depot ne s'ecrase pas."""
    return {"id": services.deposer_document(request.auth, seance_id, saisie).pk}


@routeur.post("/disponibilites", response=Identifiant, auth=exige(PERM.DISPO))
def declarer_absence(request, saisie: SaisieAbsence):
    return {"id": services.declarer_absence(request.auth, saisie).pk}


@routeur.post("/conges", response=Identifiant, auth=exige(PERM.DISPO))
def ouvrir_droit_conges(request, saisie: SaisieDroitConges):
    """
    Ouvre ou corrige le droit annuel d'un agent.

    Le perimetre borne : un directeur ouvre pour son sous-arbre, la DSR pour ce
    qu'elle suit, le Directeur general pour le Port entier. C'est `DISPO` plus
    la portee, et non une permission de plus — ADR 002.
    """
    return {"id": services.ouvrir_droit_conges(request.auth, saisie).pk}


@routeur.post("/conges/periodes", response=Identifiant, auth=exige(PERM.DISPO))
def planifier_conges(request, saisie: SaisiePeriodeConges):
    """Une periode souhaitee, avant tout arbitrage."""
    return {"id": services.planifier_conges(request.auth, saisie).pk}


@routeur.post(
    "/conges/periodes/{periode_id}/arbitrage", response=Identifiant, auth=exige(PERM.DISPO)
)
def arbitrer_conges(request, periode_id: int, saisie: SaisieArbitrageConges):
    """Arbitre, valide ou reporte. Un report exige son motif."""
    return {"id": services.arbitrer_conges(request.auth, periode_id, saisie).pk}

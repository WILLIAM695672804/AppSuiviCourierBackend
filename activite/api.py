"""
Routes du pilier activites — `/api/activites/*`.

**Chaque route declare la permission qu'elle exige, et rien ne se lit sans
passer par le perimetre.** L'oubli de `restreindre()` ne produit aucune erreur :
il montre a un agent le plan du voisin. Ici, aucune route ne construit son
filtre : les services de `lecture.py` partent tous de `_visibles()`.

Trois gestes ne relevent pas de la structure qui execute, et portent donc
d'autres permissions que `ACT_SAI` :

 * **suspendre** et **rattacher une instruction** relevent de `DEC` — §17 et
   §19. Le DG decide, la DSR consigne ; laisser la structure inscrire
   elle-meme l'instruction qui la contraint aurait vide le §17 de son objet ;
 * **relancer** releve de `REL` : c'est l'escalade humaine du descriptif §1.1,
   et personne ne se relance soi-meme ;
 * **recalibrer un avancement** releve de `ACT_REC`, que seule la DSR porte :
   la structure declare, la DSR retient (ADR 030). C'est le seul geste du
   pilier qu'un profil unique detienne ;
 * **valider** ou **retourner** un plan releve de `ACT_VAL`, jamais de qui l'a
   soumis.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from activite import lecture, services
from activite.schemas import (
    ActiviteDetail,
    CorbeillePlans,
    Identifiant,
    PlanActionsSortie,
    RegistreActivites,
    RegistreObligations,
    SaisieAvancement,
    SaisieCreationActivite,
    SaisieDepot,
    SaisieEtatPlan,
    SaisieIndicateur,
    SaisieInstruction,
    SaisieLevee,
    SaisieListeTaches,
    SaisieModificationActivite,
    SaisieRecalibrage,
    SaisieRelance,
    SaisieReleve,
    SaisieSuspension,
)
from noyau.habilitation.dependances import PERM, exige

routeur = Router()


# =====================================================================
#  Registre et fiche
# =====================================================================


@routeur.get("", response=RegistreActivites, auth=exige(PERM.ACT_LEC))
def registre(request, structure: str = "", etat: str = ""):
    """
    Le registre des activites du perimetre.

    Les filtres affinent ce que le perimetre a deja borne. L'inverse laisserait
    un filtre vide montrer plus que le perimetre.
    """
    return lecture.registre(request.auth, structure=structure, etat=etat)


@routeur.get("/plan", response=PlanActionsSortie, auth=exige(PERM.ACT_LEC))
def plan(request, annee: int, structure: str = ""):
    """Le plan d'une structure pour un exercice."""
    return lecture.plan(request.auth, annee=annee, structure=structure)


@routeur.get("/plans", response=CorbeillePlans, auth=exige(PERM.ACT_VAL))
def corbeille(request, annee: int):
    """La corbeille du controle de gestion — §15. `ACT_VAL`, pas `ACT_LEC`."""
    return lecture.corbeille_plans(request.auth, annee=annee)


@routeur.get("/obligations", response=RegistreObligations, auth=exige(PERM.ACT_LEC))
def obligations(request, filtre: str = ""):
    """Ce que la structure doit deposer — descriptif fonctionnel §3.3."""
    return lecture.registre_obligations(request.auth, filtre=filtre)


@routeur.get("/{activite_id}", response=ActiviteDetail, auth=exige(PERM.ACT_LEC))
def fiche(request, activite_id: int):
    """
    La fiche complete, fiche de vie comprise — §18.

    Declaree **apres** `/plan`, `/plans` et `/obligations` : un chemin variable
    place avant eux capturerait « plan » comme identifiant.
    """
    return lecture.fiche(request.auth, activite_id)


# =====================================================================
#  Ecritures de la structure — ACT_SAI
# =====================================================================


@routeur.post("", response=Identifiant, auth=exige(PERM.ACT_SAI))
def creer(request, saisie: SaisieCreationActivite):
    return {"id": services.creer_activite(request.auth, saisie).pk}


@routeur.post("/{activite_id}", response=Identifiant, auth=exige(PERM.ACT_SAI))
def modifier(request, activite_id: int, saisie: SaisieModificationActivite):
    """
    `POST` et non `PATCH` : c'est ce que le front emet (`useEcriture` poste
    tout). Corriger le verbe ici obligerait a corriger le client le jour du
    branchement, pour un gain nul.
    """
    return {"id": services.modifier_activite(request.auth, activite_id, saisie).pk}


@routeur.post("/{activite_id}/avancement", response=Identifiant, auth=exige(PERM.ACT_SAI))
def declarer_avancement(request, activite_id: int, saisie: SaisieAvancement):
    return {"id": services.declarer_avancement(request.auth, activite_id, saisie).pk}


@routeur.post("/{activite_id}/recalibrage", response=Identifiant, auth=exige(PERM.ACT_REC))
def recalibrer(request, activite_id: int, saisie: SaisieRecalibrage):
    """
    La DSR retient, sur une tache, une autre valeur que celle declaree — §15,
    ADR 030, ADR 049.

    `valeur` a `null` leve le recalibrage. Le motif reste exige dans les
    deux sens.
    """
    return {"id": services.recalibrer(request.auth, activite_id, saisie).pk}


@routeur.post("/{activite_id}/indicateurs", response=Identifiant, auth=exige(PERM.ACT_SAI))
def ajouter_indicateur(request, activite_id: int, saisie: SaisieIndicateur):
    return {"id": services.ajouter_indicateur(request.auth, activite_id, saisie).pk}


@routeur.post(
    "/{activite_id}/indicateurs/{indicateur_id}/releve",
    response=Identifiant,
    auth=exige(PERM.ACT_SAI),
)
def relever(request, activite_id: int, indicateur_id: int, saisie: SaisieReleve):
    mesure = services.relever_indicateur(request.auth, activite_id, indicateur_id, saisie)
    return {"id": mesure.pk}


@routeur.post("/{activite_id}/taches", response=Identifiant, auth=exige(PERM.ACT_SAI))
def remplacer_taches(request, activite_id: int, saisie: SaisieListeTaches):
    """
    La liste **entiere** des taches — ADR 049. Elle remplace l'ajout unitaire :
    la somme a 100 (RG-3) ne se controle que sur la liste.
    """
    return {"id": services.remplacer_taches(request.auth, activite_id, saisie).pk}


# Il y a eu ici un `POST /{activite_id}/pieces` — mention d'une piece dans la
# fiche de vie, **sans binaire**. Elle a ete retiree le 17 aout 2026 : une route
# qui inscrit un nom de fichier sans le fichier produit des lignes qu'aucun
# telechargement ne peut servir, et le message d'erreur qui en resultait accusait
# l'exploitation d'une perte qui n'avait pas eu lieu.
#
# La conserver « parce que les fiches de vie deja ecrites la citent » etait un
# raisonnement faux : ce sont les **lignes** qui sont en base, pas la route, et
# elles y restent. Ce qu'il fallait garder, c'est l'explication — elle est ici,
# dans `services.py` et dans `docs/pieges.md`.
#
# Le televersement d'une piece sur une activite passe par `POST /api/pieces`
# avec `objetType=activite` (ADR 017), et rien d'autre.


# =====================================================================
#  Gestes d'autorite — DEC et REL
# =====================================================================


@routeur.post("/{activite_id}/suspension", response=Identifiant, auth=exige(PERM.DEC))
def suspension(request, activite_id: int, saisie: SaisieSuspension):
    """`DEC` : une structure ne se suspend pas elle-meme — §19."""
    return {"id": services.basculer_suspension(request.auth, activite_id, saisie).pk}


@routeur.post("/{activite_id}/instructions", response=Identifiant, auth=exige(PERM.DEC))
def rattacher_instruction(request, activite_id: int, saisie: SaisieInstruction):
    """`DEC` : le DG decide, la DSR consigne — §17."""
    return {"id": services.rattacher_instruction(request.auth, activite_id, saisie).pk}


@routeur.post(
    "/{activite_id}/instructions/{instruction_id}/levee",
    response=Identifiant,
    auth=exige(PERM.DEC),
)
def lever_instruction(request, activite_id: int, instruction_id: int, saisie: SaisieLevee):
    instruction = services.lever_instruction(request.auth, activite_id, instruction_id, saisie)
    return {"id": instruction.pk}


@routeur.post("/{activite_id}/relance", response=Identifiant, auth=exige(PERM.REL))
def relancer(request, activite_id: int, saisie: SaisieRelance):
    """`REL` : l'escalade humaine du §1.1."""
    return {"id": services.relancer(request.auth, activite_id, saisie).pk}


# =====================================================================
#  Plan d'actions et obligations
# =====================================================================


@routeur.post("/plan/etat", response=Identifiant, auth=exige(PERM.ACT_SAI, PERM.ACT_VAL))
def changer_etat_plan(request, saisie: SaisieEtatPlan):
    """
    Soumettre, valider, retourner — une seule route, parce que c'est ce que le
    front emet.

    **La garde laisse passer les deux publics** : `exige()` demande « au moins
    une » des permissions citees. Le controleur de gestion ne porte pas
    `ACT_SAI` — il ne saisit aucune activite — et le point focal ne porte pas
    `ACT_VAL`. Exiger la seule `ACT_SAI` aurait ferme la route a qui doit
    valider.

    Le tri se fait donc ici, une fois le corps lu : une garde de route s'applique
    avant, et ne peut pas savoir si l'appel soumet ou valide.
    """
    if saisie.action in ("valider", "retourner"):
        _exiger(
            request,
            PERM.ACT_VAL,
            "Valider ou retourner un plan releve du controle de gestion.",
        )
    else:
        _exiger(request, PERM.ACT_SAI, "Soumettre un plan releve de la structure qui l'ecrit.")
    return {"id": services.changer_etat_plan(request.auth, saisie).pk}


def _exiger(request, permission: str, message: str) -> None:
    """
    Refus en **403 et non 401** : la session est valide, c'est le geste qui est
    hors de portee. Un 401 renverrait l'agent a l'ecran de connexion, ou il se
    reconnecterait pour rien.
    """
    from noyau.erreurs import ErreurMetier
    from noyau.habilitation.resolution import permissions_de

    if permission not in permissions_de(request.auth):
        raise ErreurMetier(message, code="permission_absente", statut=403)


@routeur.post("/obligations/{obligation_id}/depot", response=Identifiant, auth=exige(PERM.ACT_SAI))
def deposer(request, obligation_id: int, saisie: SaisieDepot):
    return {"id": services.deposer_obligation(request.auth, obligation_id, saisie).pk}

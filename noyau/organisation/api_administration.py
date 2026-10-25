"""
Administration de l'organigramme — `/api/organisation/*`.

**Deux routeurs pour trois tables, et ce n'est pas un doublon.** Le referentiel
(`/api/referentiels/*`) est lu par sept ecrans de quatre piliers sous une garde
volontairement large — un agent qui cote doit voir les structures qu'il ne lit
pas (ADR 007). Ici, on **ecrit** l'ossature, et la garde est nominative :
`ADM_ORG`, l'administrateur fonctionnel du §3.9.

Melanger les deux aurait ouvert l'ecriture de l'organigramme a toute session
authentifiee, ce que la derogation de l'ADR 007 n'a jamais dit.

Les **structures** en font partie depuis l'ADR 021. Elles s'ecrivaient sur
`/gouvernance`, sous une permission a part tenue par la DSR ; deux permissions
pour un seul organigramme laissaient l'administrateur creer des postes sans
pouvoir creer la structure qui les porte.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige
from noyau.organisation import services
from noyau.organisation.schemas_administration import (
    AffectationSortie,
    Identifiant,
    NiveauAdmin,
    PosteAdmin,
    SaisieAffectation,
    SaisieCloturePoste,
    SaisieFinAffectation,
    SaisieModificationNiveau,
    SaisieModificationPoste,
    SaisieNiveau,
    SaisiePoste,
    SaisieStructure,
)

routeur = Router()


@routeur.post("/structures", response={201: Identifiant}, auth=exige(PERM.ADM_ORG))
def creer_structure(request, saisie: SaisieStructure):
    """
    Inscrit une structure a l'organigramme — F-01.

    La route ecrit **deux** objets : la structure, et le poste responsable
    vacant qui la surmonte. C'est ce couple qui justifie qu'elle vive ici et
    non ailleurs : ouvrir un poste, c'est deja le metier de ce routeur, et
    pourvoir celui-la se fait dans l'onglet d'a cote (ADR 021).
    """
    return 201, {"id": services.creer_structure(request.auth, saisie).pk}


@routeur.get("/niveaux", response=list[NiveauAdmin], auth=exige(PERM.ADM_ORG))
def niveaux(request):
    """Les etages de l'organigramme, du sommet vers la base, avec leur poids."""
    return services.registre_niveaux()


@routeur.post("/niveaux", response={201: NiveauAdmin}, auth=exige(PERM.ADM_ORG))
def creer_niveau(request, saisie: SaisieNiveau):
    """
    Ouvre un etage.

    Le rang doit etre libre. Inserer entre deux etages existants suppose donc
    de renumeroter d'abord — le serveur ne decale pas trois niveaux a la place
    de l'administrateur, cela deplacerait toutes leurs structures.
    """
    niveau = services.creer_niveau(
        request.auth,
        code=saisie.code,
        libelle=saisie.libelle,
        rang=saisie.rang,
        niveau_parent_id=saisie.niveauParentId,
        peut_coter=saisie.peutCoter,
        peut_recevoir_cotation=saisie.peutRecevoirCotation,
        porte_signature=saisie.porteSignature,
        ligne_statistiques=saisie.ligneStatistiques,
    )
    return 201, _relire(niveau.pk)


@routeur.patch("/niveaux/{niveau_id}", response=NiveauAdmin, auth=exige(PERM.ADM_ORG))
def modifier_niveau(request, niveau_id: int, saisie: SaisieModificationNiveau):
    """
    Change le libelle, le rattachement ou ce que l'etage autorise.

    Le rang n'y figure pas : voir `services.modifier_niveau`.
    """
    services.modifier_niveau(
        request.auth,
        niveau_id,
        libelle=saisie.libelle,
        niveau_parent_id=saisie.niveauParentId,
        peut_coter=saisie.peutCoter,
        peut_recevoir_cotation=saisie.peutRecevoirCotation,
        porte_signature=saisie.porteSignature,
        ligne_statistiques=saisie.ligneStatistiques,
    )
    return _relire(niveau_id)


@routeur.get("/postes", response=list[PosteAdmin], auth=exige(PERM.ADM_ORG))
def postes(request):
    """
    Les postes de travail et leur occupation.

    Pas de filtre par structure, contrairement au referentiel de saisie :
    l'administrateur cherche precisement les postes vacants, et un filtre
    l'obligerait a ouvrir les structures une par une pour les trouver.
    """
    return services.registre_postes()


@routeur.post("/postes", response={201: PosteAdmin}, auth=exige(PERM.ADM_ORG))
def creer_poste(request, saisie: SaisiePoste):
    """
    Ouvre un poste dans une structure.

    Un poste se cree **sans occupant** : c'est l'unite de la hierarchie, pas
    l'agent, et un poste vacant est ce que l'ecran cherche precisement a rendre
    visible. L'affectation vient apres, par `POST /affectations`.
    """
    poste = services.creer_poste(
        request.auth,
        structure_id=saisie.structureId,
        libelle=saisie.libelle,
        niveau_id=saisie.niveauId,
        poste_superieur_id=saisie.posteSuperieurId,
        profil_par_defaut_id=saisie.profilParDefautId,
        effectif_prevu=saisie.effectifPrevu,
    )
    return 201, _relire_poste(poste.pk)


@routeur.patch("/postes/{poste_id}", response=PosteAdmin, auth=exige(PERM.ADM_ORG))
def modifier_poste(request, poste_id: int, saisie: SaisieModificationPoste):
    """Corrige un poste en place. La structure n'y figure pas — voir le service."""
    services.modifier_poste(
        request.auth,
        poste_id,
        libelle=saisie.libelle,
        niveau_id=saisie.niveauId,
        poste_superieur_id=saisie.posteSuperieurId,
        profil_par_defaut_id=saisie.profilParDefautId,
        effectif_prevu=saisie.effectifPrevu,
    )
    return _relire_poste(poste_id)


@routeur.post("/postes/{poste_id}/cloture", response={204: None}, auth=exige(PERM.ADM_ORG))
def cloturer_poste(request, poste_id: int, saisie: SaisieCloturePoste):
    """
    Ferme un poste. **Il n'existe pas de route de suppression** : effacer un
    poste effacerait qui a valide quoi a cet etage (principe 1 de `modeles.py`).

    `POST` et non `DELETE` : le geste porte un motif, et un corps de requete sur
    un `DELETE` n'est lu par aucun intermediaire de facon garantie.
    """
    services.cloturer_poste(request.auth, poste_id, motif=saisie.motif)
    return 204, None


# =====================================================================
#  Les affectations — F-04
# =====================================================================


@routeur.get("/affectations", response=list[AffectationSortie], auth=exige(PERM.ADM_ORG))
def affectations(request, posteId: int | None = None, utilisateurId: int | None = None):
    """
    Qui a occupe quoi, et entre quelles dates.

    Les deux filtres se combinent. Sans aucun, la route rend l'histoire entiere
    de l'institution : c'est assume, l'organigramme du Port compte quelques
    centaines de lignes, et paginer une liste que l'ecran trie deja par poste
    aurait coute plus que de la rendre.

    Les parametres sont en camelCase : ils traversent l'URL, et la convention de
    sortie du projet est celle-la.
    """
    return services.registre_affectations(poste_id=posteId, utilisateur_id=utilisateurId)


@routeur.post("/affectations", response={201: AffectationSortie}, auth=exige(PERM.ADM_ORG))
def affecter(request, saisie: SaisieAffectation):
    """
    Affecte un agent a un poste.

    C'est aussi la **mutation** : l'affectation en cours est close la veille du
    nouveau debut, dans la meme transaction. Deux occupations ne se chevauchent
    donc jamais d'une journee — sur un poste de validation, une journee a deux
    titulaires est une journee ou deux personnes ont pu signer au meme titre.
    """
    affectation = services.affecter(
        request.auth,
        utilisateur_id=saisie.utilisateurId,
        poste_id=saisie.posteId,
        debut=saisie.debut,
        motif=saisie.motif,
    )
    return 201, _relire_affectation(affectation.pk)


@routeur.post(
    "/affectations/{affectation_id}/fin", response=AffectationSortie, auth=exige(PERM.ADM_ORG)
)
def terminer_affectation(request, affectation_id: int, saisie: SaisieFinAffectation):
    """
    Met fin a une occupation sans lui donner de suite — depart, retraite, mise a
    disposition. L'agent se retrouve sans poste, et le poste redevient vacant.
    """
    services.terminer_affectation(request.auth, affectation_id, fin=saisie.fin, motif=saisie.motif)
    return _relire_affectation(affectation_id)


# =====================================================================
#  Relectures
# =====================================================================


def _relire(niveau_id: int) -> dict:
    """
    Rend la ligne telle que le registre l'affiche.

    Le front remplace sa ligne par ce que la route rend : lui renvoyer le
    modele ecrit, sans `nombreStructures` ni `nombrePostes`, ferait tomber les
    deux compteurs a zero jusqu'au rechargement suivant.
    """
    for ligne in services.registre_niveaux():
        if ligne["id"] == niveau_id:
            return ligne
    raise AssertionError("Le niveau vient d'etre ecrit : il ne peut pas manquer au registre.")


def _relire_poste(poste_id: int) -> dict:
    """Meme raison que `_relire` : le modele ecrit ne porte ni `titulaires`, ni
    le libelle de son niveau, et les deux colonnes tomberaient a vide."""
    for ligne in services.registre_postes():
        if ligne["id"] == poste_id:
            return ligne
    raise AssertionError("Le poste vient d'etre ecrit : il ne peut pas manquer au registre.")


def _relire_affectation(affectation_id: int) -> dict:
    """Le nom de l'agent et le sigle de la structure viennent de deux jointures
    que l'instance ecrite ne porte pas."""
    for ligne in services.registre_affectations():
        if ligne["id"] == affectation_id:
            return ligne
    raise AssertionError("L'affectation vient d'etre ecrite : elle ne peut pas manquer.")

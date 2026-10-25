"""
Routes d'habilitation — `/api/habilitations/*`.

Deux publics, et il ne faut pas les confondre :

 * **l'administrateur fonctionnel** (`ADM_HAB`) tient les comptes, les profils,
   les perimetres et le registre des delegations ;
 * **tout responsable** pose et retire ses propres delegations sans demander a
   quiconque — descriptif fonctionnel §3.4.

D'ou deux gardes differentes sur ce meme routeur. Les trois routes ouvertes a
la session seule sont nommement commentees ; toute autre route nomme la
permission qu'elle exige.
"""

from django.db import connection
from ninja import Router

from noyau.erreurs import HorsPerimetre
from noyau.habilitation.dependances import PERM, exige, session_seule
from noyau.habilitation.modeles import Profil
from noyau.habilitation.schemas import (
    AgentRattache,
    BasculePermission,
    DelegationPossible,
    DelegationSortie,
    FicheCompte,
    PerimetreLigne,
    ProfilSortie,
    SaisieCompte,
    SaisieCreationProfil,
    SaisieDelegation,
    SaisieEtatCompte,
    SaisieInvalidationProfil,
    SaisieModificationCompte,
    SaisieModificationProfil,
    SaisiePerimetre,
    SaisieProfil,
    SaisieRattachement,
    SessionSortie,
    UtilisateurLigne,
)
from noyau.habilitation.services import (
    attribuer_profil,
    basculer_permission,
    catalogue_perimetres,
    changer_etat_compte,
    creer_compte,
    declarer_delegation,
    definir_perimetre,
    delegataires_possibles,
    delegations_visibles,
    detacher_session,
    etat_delegation,
    etendue_de,
    etendues_delegables,
    interrompre_delegation,
    modifier_compte,
    rattacher_session,
    retirer_profil,
)
from noyau.habilitation.services import creer_profil as services_creer_profil
from noyau.habilitation.services import invalider_profil as services_invalider_profil
from noyau.habilitation.services import modifier_profil as services_modifier_profil
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.journal.service import tracer_acces
from noyau.perimetre.modeles import Perimetre

# Le premier parametre s'appelle `request` et n'est pas annote : les deux
# sont imposes par django-ninja, et le premier va contre nos conventions.
# L'explication complete est dans `noyau/identite/api.py`.
routeur = Router()


# =====================================================================
#  Comptes
# =====================================================================


@routeur.get("/utilisateurs", response=list[UtilisateurLigne], auth=exige(PERM.ADM_HAB))
def utilisateurs(request, vue: str = "tous"):
    """
    Le registre des comptes.

    La vue « invitations » renvoie toujours vide : **l'etat « invite » n'existe
    pas au modele**. La table porte `actif` et `invalide_le`, rien qui
    distingue un compte cree d'un compte jamais active. Voir
    docs/questions-ouvertes.md, A20 — c'est un circuit entier qui manque,
    pas une colonne.
    """
    comptes = Utilisateur.objects.select_related("structure", "poste").prefetch_related(
        "profils__profil"
    )

    if vue == "actifs":
        comptes = comptes.filter(actif=True, invalide_le__isnull=True)
    elif vue == "suspendus":
        comptes = comptes.filter(actif=False)
    elif vue == "invitations":
        comptes = comptes.none()

    return [_ligne_compte(u) for u in comptes]


def _ligne_compte(u: Utilisateur) -> dict:
    return {
        "id": u.pk,
        "nomComplet": u.nom_complet,
        "initiales": u.initiales,
        "identifiant": u.identifiant_annuaire or "",
        "structure": str(u.structure) if u.structure else "",
        "poste": u.poste.libelle if u.poste else "",
        # Un agent peut porter plusieurs profils. Les joindre plutot que
        # d'en montrer un seul : afficher « Agent » a quelqu'un qui est
        # aussi administrateur serait faux.
        "profil": " · ".join(
            sorted(a.profil.libelle for a in u.profils.all() if a.retire_le is None)
        )
        or "(aucun)",
        "etat": "actif" if u.is_active else "suspendu",
    }


@routeur.get("/utilisateurs/{utilisateur_id}", response=FicheCompte, auth=exige(PERM.ADM_HAB))
def fiche(request, utilisateur_id: int):
    """
    Ce qui compose les droits d'un agent.

    Le registre joint les profils en une chaine, ce qui suffit a les lire mais
    pas a les administrer : on ne retire pas un profil dont on n'a pas
    l'identifiant. D'ou cette route, appelee par le panneau d'un agent.

    **Cette lecture est tracee** (RF-ADM-03). C'est la seule du depot qui le
    soit aujourd'hui, et c'est justifie : la fiche porte le matricule, le
    courriel, le telephone et les droits d'une personne nommee. Consulter le
    dossier d'un agent est un acte, pas une navigation — le registre, lui,
    n'est pas trace, il ne montre que des libelles.
    """
    agent = (
        Utilisateur.objects.select_related("structure", "poste")
        .prefetch_related("profils__profil")
        .filter(pk=utilisateur_id, invalide_le__isnull=True)
        .first()
    )
    if agent is None:
        raise HorsPerimetre("Agent introuvable.")

    tracer_acces(
        acteur=request.auth,
        objet_type="utilisateur",
        objet_id=agent.pk,
        action="consultation",
        adresse_ip=request.META.get("REMOTE_ADDR"),
        agent_utilisateur=request.META.get("HTTP_USER_AGENT"),
    )

    perimetre = (
        Perimetre.objects.filter(utilisateur=agent, valide_au__isnull=True)
        .select_related("structure")
        .first()
    )
    rattachement = (
        UtilisateurSession.objects.filter(utilisateur=agent, retire_le__isnull=True)
        .select_related("session")
        .first()
    )

    return {
        "id": agent.pk,
        "nomComplet": agent.nom_complet,
        "identifiant": agent.identifiant_annuaire or "",
        "courriel": agent.courriel,
        "telephone": agent.telephone,
        "matricule": agent.matricule,
        "structureId": agent.structure_id,
        "structure": str(agent.structure) if agent.structure else "",
        "posteId": agent.poste_id,
        "poste": agent.poste.libelle if agent.poste else "",
        "etat": "actif" if agent.is_active else "suspendu",
        # Le hache lui-meme ne sort jamais : seule son existence est une
        # information d'administration.
        "accesLocal": bool(agent.mot_de_passe),
        "profils": [
            {
                "id": a.profil.pk,
                "libelle": a.profil.libelle,
                "verrouille": a.profil.systeme,
            }
            for a in agent.profils.all()
            if a.retire_le is None
        ],
        "perimetre": (
            {
                "portee": perimetre.portee,
                "libelle": dict(Perimetre.PORTEES)[perimetre.portee],
                "structureId": perimetre.structure_id,
                "structure": str(perimetre.structure) if perimetre.structure else None,
            }
            if perimetre
            else None
        ),
        "sessionCourrier": rattachement.session.libelle if rattachement else None,
    }


@routeur.post("/utilisateurs", response={201: UtilisateurLigne}, auth=exige(PERM.ADM_HAB))
def creer(request, saisie: SaisieCompte):
    """
    Cree un compte, avec son profil et son perimetre.

    Les trois en un seul appel, et non trois routes enchainees : un compte cree
    puis abandonne entre deux appels est un agent qui se connecte et ne voit
    rien. La regle et l'atomicite sont dans le service.
    """
    agent = creer_compte(
        request.auth,
        identifiant=saisie.identifiant,
        prenom=saisie.prenom,
        nom=saisie.nom,
        structure_id=saisie.structureId,
        poste_id=saisie.posteId,
        profil_id=saisie.profilId,
        portee=saisie.portee,
        perimetre_structure_id=saisie.perimetreStructureId,
        courriel=saisie.courriel,
        telephone=saisie.telephone,
        matricule=saisie.matricule,
        mot_de_passe=saisie.motDePasse,
    )
    return 201, _ligne_compte(_relire(agent.pk))


@routeur.patch(
    "/utilisateurs/{utilisateur_id}", response=UtilisateurLigne, auth=exige(PERM.ADM_HAB)
)
def modifier(request, utilisateur_id: int, saisie: SaisieModificationCompte):
    """Etat civil et affectation. Les droits se changent par les routes dediees."""
    agent = modifier_compte(
        request.auth,
        utilisateur_id,
        prenom=saisie.prenom,
        nom=saisie.nom,
        courriel=saisie.courriel,
        telephone=saisie.telephone,
        structure_id=saisie.structureId,
        poste_id=saisie.posteId,
    )
    return _ligne_compte(_relire(agent.pk))


@routeur.patch(
    "/utilisateurs/{utilisateur_id}/etat", response=UtilisateurLigne, auth=exige(PERM.ADM_HAB)
)
def changer_etat(request, utilisateur_id: int, saisie: SaisieEtatCompte):
    """
    Suspend un compte ou le retablit.

    Il n'existe pas de route de suppression, et ce n'est pas un oubli : effacer
    un compte effacerait qui a signe quoi.
    """
    agent = changer_etat_compte(request.auth, utilisateur_id, actif=saisie.actif)
    return _ligne_compte(_relire(agent.pk))


def _relire(utilisateur_id: int) -> Utilisateur:
    """Recharge avec ses jointures : l'instance ecrite ne porte pas ses profils."""
    return (
        Utilisateur.objects.select_related("structure", "poste")
        .prefetch_related("profils__profil")
        .get(pk=utilisateur_id)
    )


# =====================================================================
#  Profils
# =====================================================================


@routeur.get("/profils", response=list[ProfilSortie], auth=exige(PERM.ADM_HAB))
def profils(request):
    return [_ligne_profil(profil) for profil in _profils_en_vigueur()]


@routeur.post("/profils", response={201: ProfilSortie}, auth=exige(PERM.ADM_HAB))
def creer_profil(request, saisie: SaisieCreationProfil):
    """
    Cree un profil, eventuellement derive d'un autre.

    C'est la sortie que le refus de `PATCH /profils/{id}/permissions` promet
    depuis le premier jour — « creez un profil derive » — et qui n'existait pas.
    """
    profil = services_creer_profil(
        request.auth,
        code=saisie.code,
        libelle=saisie.libelle,
        description=saisie.description,
        depuis_profil_id=saisie.depuisProfilId,
    )
    return 201, _relire_profil(profil.pk)


@routeur.patch("/profils/{profil_id}", response=ProfilSortie, auth=exige(PERM.ADM_HAB))
def modifier_profil(request, profil_id: int, saisie: SaisieModificationProfil):
    """Libelle et description. Le code et les permissions ont leurs regles — voir
    le service."""
    services_modifier_profil(
        request.auth, profil_id, libelle=saisie.libelle, description=saisie.description
    )
    return _relire_profil(profil_id)


@routeur.post("/profils/{profil_id}/invalidation", response={204: None}, auth=exige(PERM.ADM_HAB))
def invalider_profil(request, profil_id: int, saisie: SaisieInvalidationProfil):
    """
    Sort un profil du catalogue. La ligne n'est pas effacee — sans quoi on ne
    pourrait plus dire quels droits un agent detenait a une date passee.

    `POST` et non `DELETE` : le geste porte un motif.
    """
    services_invalider_profil(request.auth, profil_id, motif=saisie.motif)
    return 204, None


def _profils_en_vigueur():
    return (
        Profil.objects.filter(invalide_le__isnull=True)
        .prefetch_related("permissions")
        .order_by("libelle")
    )


def _ligne_profil(profil: Profil) -> dict:
    return {
        "id": profil.pk,
        "code": profil.code,
        "libelle": profil.libelle,
        "description": profil.description,
        "nombreAgents": profil.utilisateurprofil_set.filter(retire_le__isnull=True).count(),
        "verrouille": profil.systeme,
        "permissions": sorted(p.code for p in profil.permissions.all()),
    }


def _relire_profil(profil_id: int) -> dict:
    """Recharge avec ses permissions : l'instance ecrite ne les porte pas, et
    `permissions` sortirait vide juste apres une derivation."""
    return _ligne_profil(_profils_en_vigueur().get(pk=profil_id))


@routeur.patch("/profils/{profil_id}/permissions", response={204: None}, auth=exige(PERM.ADM_HAB))
def basculer(request, profil_id: int, saisie: BasculePermission):
    """Accorde ou retire une permission. La regle est dans le service."""
    basculer_permission(request.auth, profil_id, saisie.permission, saisie.accordee)
    return 204, None


@routeur.post(
    "/utilisateurs/{utilisateur_id}/profils", response={204: None}, auth=exige(PERM.ADM_HAB)
)
def poser_profil(request, utilisateur_id: int, saisie: SaisieProfil):
    """
    Attribue un profil a un agent.

    C'est ici que se joue ce qu'un autre logiciel appellerait « changer le role
    de quelqu'un ». Un agent peut en porter plusieurs : on ajoute, on ne
    remplace pas.
    """
    attribuer_profil(request.auth, utilisateur_id, saisie.profilId)
    return 204, None


@routeur.delete(
    "/utilisateurs/{utilisateur_id}/profils/{profil_id}",
    response={204: None},
    auth=exige(PERM.ADM_HAB),
)
def oter_profil(request, utilisateur_id: int, profil_id: int):
    """Le rattachement n'est pas supprime mais date — RNF-TRACE-01."""
    retirer_profil(request.auth, utilisateur_id, profil_id)
    return 204, None


# =====================================================================
#  Perimetres
# =====================================================================


@routeur.get("/perimetres", response=list[PerimetreLigne], auth=exige(PERM.ADM_HAB))
def perimetres(request):
    """
    Le catalogue des perimetres : les quatre portees du referentiel.

    Ce n'est pas une table et cela n'a pas a en devenir une — le front porte
    lui-meme `perimetre: { portee, structureId }` pour chaque compte. Les
    quatre entrees de l'ecran sont ces quatre portees, rien de plus.
    """
    return catalogue_perimetres()


@routeur.patch(
    "/utilisateurs/{utilisateur_id}/perimetre", response={204: None}, auth=exige(PERM.ADM_HAB)
)
def poser_perimetre(request, utilisateur_id: int, saisie: SaisiePerimetre):
    """
    Change la portee d'un agent.

    C'est le geste le plus lourd de consequences de tout le pilier : il ne
    change pas ce qu'un agent peut faire, mais l'etendue de ce sur quoi il le
    fait. L'ancien perimetre est clos et date, jamais ecrase.
    """
    definir_perimetre(
        request.auth, utilisateur_id, portee=saisie.portee, structure_id=saisie.structureId
    )
    return 204, None


# =====================================================================
#  Sessions courrier
# =====================================================================


@routeur.get("/sessions", response=list[SessionSortie], auth=exige(PERM.ADM_HAB))
def sessions(request):
    encours = _courriers_en_cours()

    resultat = []
    for session in SessionCourrier.objects.filter(invalide_le__isnull=True).order_by("id"):
        agents = [
            AgentRattache(
                id=rattachement.utilisateur_id,
                nomComplet=rattachement.utilisateur.nom_complet,
                poste=(
                    rattachement.utilisateur.poste.libelle if rattachement.utilisateur.poste else ""
                ),
                rattacheLe=rattachement.attribue_le.date().isoformat(),
            )
            for rattachement in session.utilisateursession_set.filter(
                retire_le__isnull=True
            ).select_related("utilisateur__poste")
        ]
        resultat.append(
            {
                "id": session.pk,
                "libelle": session.libelle,
                "courriersEnCours": encours.get(session.pk, 0),
                "agents": agents,
            }
        )
    return resultat


@routeur.post("/sessions/{session_id}/agents", response={204: None}, auth=exige(PERM.ADM_HAB))
def rattacher(request, session_id: int, saisie: SaisieRattachement):
    """
    Rattache un agent a une session courrier.

    Un agent ne tient qu'une session a la fois. Ce n'est pas une regle du
    service : c'est une contrainte d'exclusion du moteur. Le service la
    devance seulement pour que le refus soit lisible.
    """
    rattacher_session(request.auth, session_id, saisie.utilisateurId)
    return 204, None


@routeur.delete(
    "/sessions/{session_id}/agents/{utilisateur_id}",
    response={204: None},
    auth=exige(PERM.ADM_HAB),
)
def detacher(request, session_id: int, utilisateur_id: int):
    """Clot le rattachement, sans l'effacer : il reste au registre."""
    detacher_session(request.auth, session_id, utilisateur_id)
    return 204, None


def _courriers_en_cours() -> dict[int, int]:
    """
    Compte par session, en SQL direct.

    Le modele `courrier.modeles.Courrier` existe depuis le 17 aout 2026, mais ce
    compteur reste en SQL : **le noyau n'importe aucun pilier.** L'inverse est
    permis — le pilier courrier importe `noyau.identite` — et une seule
    dependance dans ce sens suffirait a rendre le socle inutilisable sans les
    piliers qu'il est cense porter. Meme raison que
    `noyau.parametrage.lecture_referentiel._courriers_par_correspondant`.

    Le compte est **volontairement hors perimetre** : c'est un ecran
    d'administration des habilitations, sous `ADM_HAB`, et il repond « combien de
    courriers ce registre retient-il ? » — une question sur la charge d'un
    service, pas sur des courriers. Aucun objet ni expediteur n'en sort.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT session_id, count(*)
              FROM courrier
             WHERE statut_courrier IN ('cree','en_cours') AND invalide_le IS NULL
             GROUP BY session_id
            """
        )
        return dict(curseur.fetchall())


# =====================================================================
#  Delegations
# =====================================================================


@routeur.get("/delegations", response=list[DelegationSortie], auth=exige(PERM.ADM_HAB))
def registre_delegations(request):
    """Le registre complet — administrateur seul."""
    return [_composer_delegation(d) for d in delegations_visibles(request.auth, siennes=False)]


#: Session seule, et non `ADM_HAB` : le §3.4 veut qu'un responsable pose et
#: retire ses delegations « sans avoir a demander a quiconque ». Ce qui borne
#: le geste n'est pas une permission d'administration, c'est la regle « on ne
#: delegue que ce que l'on possede », appliquee par le service.
@routeur.get("/delegations/miennes", response=list[DelegationSortie], auth=session_seule)
def mes_delegations(request):
    return [_composer_delegation(d) for d in delegations_visibles(request.auth, siennes=True)]


@routeur.get("/delegations/possible", response=DelegationPossible, auth=session_seule)
def delegation_possible(request):
    """
    Ce que la session peut deleguer, et a qui. Le client n'enumere rien : lui
    faire proposer une etendue que le serveur refusera ensuite ne ferait que
    deplacer le refus apres la saisie.
    """
    return {
        "delegataires": [
            {
                "id": u.pk,
                "nomComplet": u.nom_complet,
                "poste": u.poste.libelle if u.poste else "",
            }
            for u in delegataires_possibles(request.auth)
        ],
        "etendues": etendues_delegables(request.auth),
    }


@routeur.post("/delegations", response=DelegationSortie, auth=session_seule)
def poser_delegation(request, saisie: SaisieDelegation):
    delegation = declarer_delegation(
        request.auth,
        delegataire_id=saisie.delegataireId,
        etendue=saisie.etendue,
        debut=saisie.debut,
        fin=saisie.fin,
        motif=saisie.motif,
    )
    return _composer_delegation(delegation)


@routeur.delete("/delegations/{delegation_id}", response={204: None}, auth=session_seule)
def clore_delegation(request, delegation_id: int):
    interrompre_delegation(request.auth, delegation_id)
    return 204, None


def _composer_delegation(delegation) -> dict:
    return {
        "id": delegation.pk,
        "titulaire": delegation.titulaire.nom_complet,
        "delegataire": delegation.beneficiaire.nom_complet,
        "poste": delegation.beneficiaire.poste.libelle if delegation.beneficiaire.poste else "",
        "etendue": etendue_de(delegation),
        "debut": delegation.debut.date().isoformat(),
        "fin": delegation.fin.date().isoformat(),
        "motif": delegation.motif or "",
        "etat": etat_delegation(delegation),
    }

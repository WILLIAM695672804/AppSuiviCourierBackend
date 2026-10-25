"""
Routes de session — `/api/auth/*`.

Elles sont la contrepartie exacte de `frontend/src/features/authentification/`.
La forme de `/auth/moi` est imposee par l'interface `UtilisateurConnecte` de
`frontend/src/types/habilitation.ts` : le front n'y recalcule rien, il affiche
ce qu'il recoit. Toute divergence se voit immediatement a l'ecran — ce qui est
la meilleure garantie qu'on ait.
"""

from django.contrib.auth import authenticate, login, logout
from ninja import Router, Schema

from noyau.habilitation.dependances import session_seule
from noyau.habilitation.resolution import delegation_active, permissions_de
from noyau.identite.modeles import Utilisateur, UtilisateurSession
from noyau.journal.service import inscrire
from noyau.perimetre.portee import perimetre_en_vigueur

# ---------------------------------------------------------------------
#  Deux contraintes de django-ninja pesent sur CHAQUE route du projet, et
#  toutes deux vont contre nos conventions. Elles n'en sont pas moins
#  obligatoires.
#
#  1. Le premier parametre s'appelle **`request`**, en anglais. Ninja ne
#     le reconnait que par son nom (`if name == "request"` dans
#     `ninja/signature/details.py`) : nomme autrement, il devient un
#     parametre de requete HTTP obligatoire, et toute la route repond 422
#     « Field required ». Le nom n'est donc pas un choix de nommage, c'est
#     l'API de la bibliotheque — comme `self`.
#
#  2. Il n'est **pas annote**. Ninja construirait un schema Pydantic pour
#     `HttpRequest`, qui n'est pas serialisable, et le serveur ne
#     demarrerait plus.
# ---------------------------------------------------------------------
routeur = Router()


class SaisieConnexion(Schema):
    identifiant: str
    motDePasse: str


class PerimetreSortie(Schema):
    portee: str
    structureId: int | None


class SessionCourrierSortie(Schema):
    id: int
    code: str
    libelle: str


class DelegationSortie(Schema):
    id: int
    nomComplet: str


class UtilisateurConnecte(Schema):
    """Miroir de l'interface TypeScript du meme nom."""

    id: int
    nomComplet: str
    initiales: str
    posteLibelle: str
    structureLibelle: str
    #: Le sigle de la structure de rattachement — `structure.code`, vide si
    #: l'agent n'en a aucune. Le libelle ne suffit pas la ou une saisie designe
    #: des structures par sigle : la modale d'activite doit ecarter de son
    #: selecteur la structure porteuse, qu'elle ne connait que par la session.
    structureSigle: str
    permissions: list[str]
    perimetre: PerimetreSortie
    sessionCourrier: SessionCourrierSortie | None
    litToutesSessions: bool
    delegationDe: DelegationSortie | None


def _composer(utilisateur: Utilisateur) -> dict:
    """
    Compose la reponse attendue par le front.

    Les permissions sont resolues **ici** — profils et delegations en cours
    additionnes — et envoyees a plat. Le front ne doit jamais avoir a deviner
    qu'une delegation est en cours pour savoir ce qu'il peut afficher.
    """
    perimetre = perimetre_en_vigueur(utilisateur)
    delegation = delegation_active(utilisateur)

    rattachement = (
        UtilisateurSession.objects.filter(utilisateur=utilisateur, retire_le__isnull=True)
        .select_related("session")
        .first()
    )

    return {
        "id": utilisateur.pk,
        "nomComplet": utilisateur.nom_complet,
        "initiales": utilisateur.initiales,
        "posteLibelle": utilisateur.poste.libelle if utilisateur.poste else "",
        "structureLibelle": str(utilisateur.structure) if utilisateur.structure else "",
        "structureSigle": utilisateur.structure.code if utilisateur.structure else "",
        "permissions": sorted(permissions_de(utilisateur)),
        "perimetre": {
            "portee": perimetre.portee_front if perimetre else "poste",
            "structureId": perimetre.structure_id if perimetre else None,
        },
        "sessionCourrier": (
            {
                "id": rattachement.session_id,
                "code": rattachement.session.code.upper(),
                "libelle": rattachement.session.libelle,
            }
            if rattachement
            else None
        ),
        "litToutesSessions": bool(rattachement and rattachement.session.lit_toutes_sessions),
        "delegationDe": (
            {"id": delegation.titulaire_id, "nomComplet": delegation.titulaire.nom_complet}
            if delegation
            else None
        ),
    }


@routeur.post("/connexion", response=UtilisateurConnecte, auth=None)
def connexion(request, saisie: SaisieConnexion):
    from noyau.erreurs import ErreurMetier

    utilisateur = authenticate(request, username=saisie.identifiant, password=saisie.motDePasse)
    if utilisateur is None:
        # Message unique, quelle que soit la cause : distinguer « compte
        # inconnu » de « mot de passe faux » permet d'enumerer les comptes.
        raise ErreurMetier("Identifiant ou mot de passe incorrect.", statut=401, code="refus")

    login(request, utilisateur)

    # La connexion est journalisee, et le **moyen** avec elle. C'est ce qui
    # permet a la supervision de compter les connexions encore faites par mot
    # de passe applicatif — le chiffre qui dit si la bascule vers l'annuaire
    # est achevee (RF-ADM-02). Sans cette ligne, l'ecran des integrations
    # n'aurait qu'un zero a montrer, et un zero se lit comme une reussite.
    inscrire(
        objet_type="utilisateur",
        objet_id=utilisateur.pk,
        type_evenement="connexion",
        libelle=f"Connexion de {utilisateur.nom_complet}",
        acteur=utilisateur,
        detail="Authentification par mot de passe applicatif.",
        donnees={"moyen": "mot_de_passe"},
    )
    return _composer(utilisateur)


# Une session ouverte est requise pour la fermer : sans garde, la route
# serait un point d'entree anonyme, et le filet
# `test_toute_route_porte_une_authentification` la signale a juste titre.
@routeur.post("/deconnexion", response={204: None}, auth=session_seule)
def deconnexion(request):
    logout(request)
    return 204, None


@routeur.get("/moi", response=UtilisateurConnecte, auth=session_seule)
def moi(request):
    """
    Le seul endpoint sans exigence de permission.

    Il est appele au chargement de chaque page par le fournisseur de session
    du front. Exiger une permission ici rendrait l'application inaccessible a
    quiconque n'en porte qu'une seule.
    """
    return _composer(request.user)

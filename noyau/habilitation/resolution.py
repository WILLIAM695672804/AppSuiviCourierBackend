"""
Resolution des permissions d'un utilisateur.

Le front recoit une **liste plate** de codes et ne recalcule rien :
`UtilisateurConnecte.permissions` dans `frontend/src/types/habilitation.ts`.
C'est ici que cette liste se construit, et c'est le seul endroit.

Deux sources s'additionnent :

 1. les profils attribues et non retires ;
 2. les delegations en cours a l'instant present.

Une delegation n'accorde jamais plus que ce qu'elle enumere : elle ne
transmet pas les permissions du titulaire en bloc. Le beneficiaire d'une
delegation de signature ne recupere pas le droit de coter.
"""

from django.db.models import Q
from django.utils import timezone

from noyau.habilitation.modeles import Delegation, Permission
from noyau.identite.modeles import Utilisateur


def permissions_de(utilisateur: Utilisateur) -> set[str]:
    """Les codes de permission dont l'utilisateur dispose maintenant."""
    depuis_profils = Permission.objects.filter(
        profils__utilisateurprofil__utilisateur=utilisateur,
        profils__utilisateurprofil__retire_le__isnull=True,
        profils__invalide_le__isnull=True,
    ).values_list("code", flat=True)

    depuis_delegations = Permission.objects.filter(
        delegations__in=delegations_en_cours(utilisateur)
    ).values_list("code", flat=True)

    return set(depuis_profils) | set(depuis_delegations)


def delegations_en_cours(utilisateur: Utilisateur):
    """Les delegations dont l'utilisateur beneficie a cet instant."""
    maintenant = timezone.now()
    return Delegation.objects.filter(
        Q(beneficiaire=utilisateur),
        debut__lte=maintenant,
        fin__gte=maintenant,
        invalide_le__isnull=True,
    )


def delegation_active(utilisateur: Utilisateur) -> Delegation | None:
    """
    La delegation au titre de laquelle l'utilisateur agit, s'il y en a une.

    Le front l'affiche en clair (`delegationDe`) : un agent qui agit au nom
    d'un autre doit le voir a l'ecran, et le journal enregistre les deux
    identites.
    """
    return delegations_en_cours(utilisateur).select_related("titulaire").first()


#: Le profil des comptes usagers. Seme par la migration `0001` du socle.
PROFIL_PORTAIL = "EXTERNE"


def comptes_du_portail():
    """Les comptes usagers : profil `EXTERNE`, et rien d'autre.

    Ces comptes n'ont ni structure, ni poste, ni perimetre. Ce n'est pas un
    oubli du jeu d'essai : le portail borne ses lectures par `deposant`, et lui
    donner une portee serait *plus* permissif que de n'en donner aucune
    ([ADR 013](../../docs/architecture/013-le-portail-ne-passe-pas-par-restreindre.md)).

    Tout controle qui exige un perimetre ou un rattachement doit donc les
    ecarter, sans quoi il signale comme anomalie une decision d'architecture.
    """
    return Utilisateur.objects.filter(
        profils__profil__code=PROFIL_PORTAIL,
        profils__retire_le__isnull=True,
    )


def possede(utilisateur: Utilisateur, *codes: str) -> bool:
    """Vrai si l'utilisateur porte **au moins une** des permissions citees.

    Le « au moins une » est la meme regle que `usePermission` cote front :
    plusieurs codes ouvrent souvent le meme ecran par des chemins differents
    (EXP_SAI ou EXP_LEC, COT ou COT_DEL).
    """
    return bool(permissions_de(utilisateur) & set(codes))

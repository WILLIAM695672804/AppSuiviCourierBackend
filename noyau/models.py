"""
Point d'entree des modeles du noyau.

Django cherche les modeles dans `models.py`. Le noyau les range par domaine,
dans des sous-paquets, parce qu'un fichier de mille lignes melant
l'organigramme, les habilitations et le journal ne se relit pas. Ce fichier ne
fait que les reexporter.

Ordre d'import impose par les dependances : organisation, puis identite, puis
le reste. Ne pas le reordonner par gout alphabetique.
"""

from noyau.organisation.modeles import (  # noqa: I001
    AffectationPoste,
    NiveauHierarchique,
    Poste,
    Structure,
)
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.habilitation.modeles import (
    Delegation,
    DelegationPermission,
    Permission,
    Profil,
    ProfilPermission,
    UtilisateurProfil,
)
from noyau.perimetre.modeles import Perimetre
from noyau.journal.modeles import ChampHistorique, Evenement, JournalAcces
from noyau.pieces.modeles import PieceJointe
from noyau.notifications.modeles import EnvoiNotification, Notification
from noyau.parametres.modeles import Parametre
from noyau.parametrage.modeles import (
    Circuit,
    CircuitEtape,
    CircuitRegle,
    CircuitVersion,
    Correspondant,
    MentionType,
    Nature,
    Priorite,
    RubriqueClassement,
    SeuilAlerte,
)

__all__ = [
    "AffectationPoste",
    "ChampHistorique",
    "Circuit",
    "CircuitEtape",
    "CircuitRegle",
    "CircuitVersion",
    "Correspondant",
    "Delegation",
    "DelegationPermission",
    "EnvoiNotification",
    "Evenement",
    "JournalAcces",
    "MentionType",
    "Nature",
    "NiveauHierarchique",
    "Notification",
    "Parametre",
    "Perimetre",
    "Permission",
    "PieceJointe",
    "Poste",
    "Priorite",
    "Profil",
    "ProfilPermission",
    "RubriqueClassement",
    "SessionCourrier",
    "SeuilAlerte",
    "Structure",
    "Utilisateur",
    "UtilisateurProfil",
    "UtilisateurSession",
]

"""
Formes echangees pour les notifications.

Convention du depot : **sortie en camelCase**, en miroir de
`frontend/src/features/notifications/api.ts`.
"""

from ninja import Schema


class NotificationSortie(Schema):
    id: int
    type: str
    libelle: str
    detail: str
    #: `information` ou `alerte`. Deux valeurs et pas cinq : une echelle fine
    #: se remplit d'elle-meme par le haut.
    importance: str
    #: Chemin du front (`/dossiers/42`), jamais une URL absolue.
    lien: str | None
    lue: bool
    creeLe: str


class MesNotifications(Schema):
    #: Compte sur toute la table, pas sur la page rendue : une pastille bornee
    #: a la taille de la page ferait croire que la file se vide.
    nonLues: int
    notifications: list[NotificationSortie]


class CompteLecture(Schema):
    """Ce que « tout marquer lu » a effectivement touche."""

    marquees: int


class EnvoiBloque(Schema):
    id: int
    canal: str
    etat: str
    libelle: str
    tentatives: int
    raison: str
    creeLe: str


class LigneCanal(Schema):
    canal: str
    enAttente: int
    envoyes: int
    echoues: int
    sansTransport: int


class EtatFile(Schema):
    """
    L'etat d'exploitation de la file.

    `sansTransport` se lit avant les echecs : ce n'est pas une panne, c'est ce
    que l'institution n'a pas branche.
    """

    canaux: list[LigneCanal]
    enAttente: int
    bloques: list[EnvoiBloque]

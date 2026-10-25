"""
Contrat du tableau de bord d'administration.

Convention de sortie du depot : **camelCase**. Les noms suivent
`frontend/src/features/administration/api.ts` champ pour champ — un ecart s'y
verrait a l'execution et nulle part avant.

Tous les blocs sont presents en toute circonstance, meme vides. Un compte qui
n'a pas `AUDIT` recoit `acces` a zero et `activite` vide, pas une reponse
amputee : le front n'a alors pas a distinguer « pas le droit » de « rien a
montrer », et son affichage reste pilote par ses propres gardes.
"""

from ninja import Schema


class IndicateurAdmin(Schema):
    libelle: str
    valeur: str
    variation: str | None
    ton: str
    note: str | None


class PointActivite(Schema):
    """Un point de la courbe. Le libelle de periode est calcule au serveur —
    « S32 » ou « août » selon le pas, que le front n'a pas a deviner."""

    periode: str
    operations: int


class RepartitionType(Schema):
    libelle: str
    valeur: int
    part: int


class LigneAdoption(Schema):
    structure: str
    actifs: int
    habilites: int
    operations: int
    part: int
    #: `None` quand la structure n'a rien fait sur la periode. L'ecran en fait
    #: « Aucune activité », en rouge : c'est l'information de la ligne.
    derniereActivite: str | None


class CompteurReferentiel(Schema):
    libelle: str
    valeur: int


class AnomalieReferentiel(Schema):
    libelle: str
    nombre: int
    #: L'ecran ou corriger. Une anomalie mene toujours a son remede.
    chemin: str
    ton: str


class AlerteAcces(Schema):
    id: int
    horodatage: str
    agent: str
    action: str
    objet: str


class SupervisionAcces(Schema):
    signales: int
    refuses: int
    confidentiels: int
    dernieres: list[AlerteAcces]


class TableauDeBordAdmin(Schema):
    indicateurs: list[IndicateurAdmin]

    activite: list[PointActivite]
    operationsTotal: int
    operationsVariation: str
    parType: list[RepartitionType]

    adoption: list[LigneAdoption]
    structuresInactives: int

    referentiel: list[CompteurReferentiel]
    anomalies: list[AnomalieReferentiel]

    acces: SupervisionAcces

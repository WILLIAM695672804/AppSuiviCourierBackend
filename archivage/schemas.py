"""
Contrat des ecrans d'archivage.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/archivage/api.ts`.

Trois nullabilites, et chacune dit une chose differente :

 * `valideePar` / `valideeLe` a `null` : la regle n'a pas le visa du service
   des archives. Elle existe, elle se lit, et elle ne decide de rien ;
 * `echeanceSortFinal` a `null` : aucune regle ne couvre la typologie. La date
   d'elimination n'est pas « inconnue », elle n'existe pas — et c'est une
   anomalie bloquante, pas un champ vide ;
 * `tauxConformite` a `null` : le fonds est vide. Annoncer 100 % de conformite
   sur zero dossier est exactement le chiffre qu'un rapport recopierait avant
   qu'on le corrige (ADR 011).
"""

from ninja import Schema


class Compteur(Schema):
    libelle: str
    valeur: int
    note: str
    feu: str


class RegleConservation(Schema):
    id: int
    typologie: str
    description: str
    #: Duree d'utilite administrative, en annees a compter de la cloture.
    dua: int
    sortFinal: str
    #: Le texte qui fonde la duree. Sans lui, la regle n'est pas opposable.
    fondementJuridique: str
    valideePar: str | None
    valideeLe: str | None
    actif: bool
    #: Les dossiers **clos** de la typologie. Une regle ne s'applique qu'a
    #: partir de la cloture.
    dossiersConcernes: int


class Referentiel(Schema):
    regles: list[RegleConservation]
    compteurs: list[Compteur]
    enAttenteValidation: int


class Versement(Schema):
    id: int
    reference: str
    objet: str
    typologie: str
    structure: str
    closLe: str
    dua: int
    sortFinal: str
    echeanceSortFinal: str | None
    etat: str
    pieces: int
    piecesAttendues: int
    feu: str
    fondementJuridique: str


class FileVersements(Schema):
    versements: list[Versement]
    compteurs: list[Compteur]


class AnomalieVersement(Schema):
    libelle: str
    precision: str
    #: Bloquante ne veut pas dire grave : cela veut dire que le versement n'a
    #: pas de sens tant que ce n'est pas reglé.
    bloquante: bool


class PieceVersee(Schema):
    id: int
    nom: str
    format: str
    taille: str
    #: Les pieces manquantes sortent avec `presente = false` plutot que d'etre
    #: absentes : un bordereau se lit pour ce qu'il contient et pour ce qui y
    #: manque.
    presente: bool


class Maillon(Schema):
    etape: str
    horodatage: str
    empreinte: str


class VersementDetail(Versement):
    verseLe: str | None
    versePar: str | None
    anomalies: list[AnomalieVersement]
    piecesJointes: list[PieceVersee]
    #: Vide tant que le dossier n'est pas verse, et c'est exact : il n'y a rien
    #: a sceller avant.
    chaineIntegrite: list[Maillon]


class PreuveIntegrite(Schema):
    reference: str
    objet: str
    algorithme: str
    empreinte: str
    horodatage: str
    #: L'application elle-meme. C'est une limite, et elle est ecrite : un
    #: horodatage qualifie suppose un tiers de confiance. Voir A40.
    autorite: str
    nombrePieces: int
    taille: str
    produitePar: str


class ConformiteArchivistique(Schema):
    compteurs: list[Compteur]
    echeancesDepassees: list[Versement]
    typologiesSansRegle: list[str]
    tauxConformite: float | None


# =====================================================================
#  Les saisies
# =====================================================================


class SaisieRegle(Schema):
    typologie: str
    description: str
    dua: int
    sortFinal: str
    fondementJuridique: str
    piecesAttendues: int = 0


class SaisieVersement(Schema):
    observation: str = ""
    #: Verser malgre une anomalie non bloquante suppose de la motiver.
    anomaliesAcceptees: bool = False


class DemandePreuve(Schema):
    motif: str
    destinataire: str


class Creation(Schema):
    id: int

"""
Formes echangees pour les pieces jointes.

Convention du depot : **sortie en camelCase**, en miroir de
`frontend/src/features/pieces/api.ts`.

Le depot n'a pas de schema d'entree : c'est un envoi `multipart/form-data`, et
django-ninja passe le fichier par `UploadedFile` et les champs par `Form`. Un
`Schema` d'entree ici aurait force le client a envoyer du JSON, donc a encoder
le binaire en base64 — un tiers de poids en plus pour rien.
"""

from ninja import Schema


class VersionPiece(Schema):
    """Une version anterieure. Elle reste telechargeable — RF-GED-04."""

    uid: str
    version: int
    deposeeLe: str
    tailleLisible: str


class PieceSortie(Schema):
    uid: str
    nom: str
    extension: str
    #: En octets, pour trier et comparer. `tailleLisible` est pour l'affichage.
    taille: int
    tailleLisible: str
    categorie: str
    version: int
    #: SHA-256 en clair — la preuve d'integrite de RF-GED-09. Une preuve qu'on
    #: ne peut pas lire ne prouve rien.
    empreinte: str
    deposeeLe: str
    #: Retiree ne veut pas dire supprimee : le binaire reste, l'empreinte reste
    #: verifiable, et la piece reste telechargeable par qui voit l'objet.
    retiree: bool
    #: Faux quand la ligne n'a pas de binaire — cas des mentions inscrites par
    #: le pilier activite jusqu'au 17 aout 2026, un nom et un poids sans
    #: fichier. Distinct de `retiree` : une piece retiree a bien ete versee.
    telechargeable: bool
    versions: list[VersionPiece]


class SaisieRetraitPiece(Schema):
    #: Obligatoire. Une piece qui disparait sans raison ecrite est exactement ce
    #: qu'un controle regarde de pres.
    motif: str

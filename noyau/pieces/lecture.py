"""
Ce qui se lit des pieces jointes.

**Seules les versions courantes sont listees.** Une piece dont une version
suivante existe n'apparait pas dans la liste : elle est atteignable par
`versions`, sur la ligne qui l'a remplacee. Lister les cinq versions d'un meme
document a plat ferait chercher longtemps laquelle est la bonne, et RF-GED-04
demande le versionnement, pas l'empilement.

Les pieces retirees sont listees **avec leur marque**, et non masquees : sur un
dossier qu'on relit, savoir qu'une piece a ete retiree — et quand — vaut mieux
que de la voir disparaitre sans trace.
"""

from noyau.identite.modeles import Utilisateur
from noyau.pieces.modeles import PieceJointe
from noyau.pieces.services import _cible_accessible


def pieces_de(acteur: Utilisateur, objet_type: str, objet_id: int) -> list[dict]:
    """
    Les pieces d'un objet, versions courantes en tete de chaine.

    Passe par `_cible_accessible` : une piece n'a pas de droits propres, ce sont
    ceux de son objet. Interroger la table sans cette verification rendrait
    lisible, par son identifiant, une piece attachee a un dossier qu'on ne voit
    pas.

    `ecriture=False` : lister demande la permission de **lecture** du pilier.
    Exiger celle de saisie — ce que ce module a fait un temps — cachait les
    pieces d'une activite a tous ceux qui la voyaient sans avoir le droit d'y
    ecrire, alors qu'ils en lisaient le reste.
    """
    _cible_accessible(acteur, objet_type, objet_id, ecriture=False)

    toutes = list(
        PieceJointe.objects.filter(objet_type=objet_type, objet_id=objet_id).order_by(
            "-cree_le", "-id"
        )
    )
    remplacees = {p.piece_precedente_id for p in toutes if p.piece_precedente_id}

    return [_ligne(piece, toutes) for piece in toutes if piece.pk not in remplacees]


def _ligne(piece: PieceJointe, toutes: list[PieceJointe]) -> dict:
    return {
        "uid": str(piece.uid),
        "nom": piece.nom_original,
        "extension": piece.extension or "",
        "taille": piece.taille_octets,
        "tailleLisible": _lisible(piece.taille_octets),
        "categorie": piece.categorie,
        "version": piece.version,
        # L'empreinte est rendue en clair : c'est la preuve d'integrite de
        # RF-GED-09, et une preuve qu'on ne peut pas lire ne prouve rien.
        "empreinte": piece.empreinte_sha256,
        "deposeeLe": piece.cree_le.strftime("%d/%m/%Y") if piece.cree_le else "",
        "retiree": piece.invalide_le is not None,
        # Faux pour les lignes sans binaire : le pilier activite en a inscrit
        # jusqu'au 17 aout 2026 — un nom et un poids, sans fichier. Elles
        # restent en base (rien ne se supprime), mais l'ecran doit cesser de
        # proposer un telechargement qui ne peut pas aboutir. Un lien mort vaut
        # moins qu'une mention honnete.
        "telechargeable": bool(piece.chemin_stockage),
        "versions": _chaine(piece, toutes),
    }


def _chaine(piece: PieceJointe, toutes: list[PieceJointe]) -> list[dict]:
    """
    Les versions anterieures, de la plus recente a la plus ancienne.

    Remontee en memoire et non par requete : la liste complete des pieces de
    l'objet est deja chargee, et une requete par version ferait N appels sur un
    ecran qui en affiche vingt.
    """
    par_id = {p.pk: p for p in toutes}
    anterieures = []
    courante = piece.piece_precedente_id

    while courante is not None and courante in par_id:
        ancienne = par_id[courante]
        anterieures.append(
            {
                "uid": str(ancienne.uid),
                "version": ancienne.version,
                "deposeeLe": ancienne.cree_le.strftime("%d/%m/%Y") if ancienne.cree_le else "",
                "tailleLisible": _lisible(ancienne.taille_octets),
            }
        )
        courante = ancienne.piece_precedente_id

    return anterieures


def _lisible(octets: int) -> str:
    """« 1,2 Mo ». Le front affiche cette chaine telle quelle."""
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{round(octets / 1024)} Ko"
    return f"{octets / (1024 * 1024):.1f}".replace(".", ",") + " Mo"

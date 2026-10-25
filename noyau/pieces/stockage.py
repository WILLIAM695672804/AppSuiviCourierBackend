"""
Ou vit le binaire d'une piece jointe.

**Jamais en base.** Le commentaire du schema est explicite : « une base
contenant les binaires devient insauvegardable ». Seul `chemin_stockage` est
stocke ; le fichier vit sur un volume, et vivra sur MinIO le jour ou la
plateforme y passera (RNF-SOUV-01, hebergement sur site).

Ce module est la **seule** frontiere avec le systeme de fichiers. Trois
fonctions, et rien qui ressemble a un chemin construit ailleurs : le jour du
passage a MinIO, c'est ce fichier qu'on reecrit, et lui seul.

## Le chemin est derive de l'empreinte

`ab/cd/abcdef…` — deux niveaux de repertoires tires des quatre premiers
caracteres du SHA-256, puis l'empreinte entiere comme nom de fichier.

Trois consequences, toutes voulues :

 1. **Deux depots du meme fichier n'occupent qu'une place.** Un rapport envoye
    a quatre directions est un seul objet sur le disque, quatre lignes en base.
 2. **Le nom d'origine ne touche jamais le disque.** « Rapport final (2).pdf »,
    un nom en arabe, un `../` : rien de tout cela n'atteint le systeme de
    fichiers. Le nom d'origine est une donnee, conservee en base et rendue au
    telechargement.
 3. **L'arborescence reste plate.** Un repertoire unique a cent mille fichiers
    est lent a lister sur la plupart des systemes ; deux niveaux de 256 le
    ramenent a quelques centaines d'entrees par repertoire.

## Ce que ce module ne fait pas

Il ne supprime rien. Une piece invalidee garde son binaire : la ligne dit
qu'elle ne compte plus, l'empreinte reste verifiable, et une piece jointe
effacee du disque ferait echouer la preuve d'integrite de RF-GED-09 sur un
dossier archive. La purge, si elle a lieu un jour, sera une decision d'archivage
avec son bordereau d'elimination — pas un effet de bord d'un clic.
"""

import hashlib
from pathlib import Path

from django.conf import settings

from noyau.erreurs import ErreurMetier

#: Ce qu'on lit du fichier a la fois pour calculer son empreinte. 1 Mio :
#: assez grand pour que le cout des appels systeme disparaisse, assez petit
#: pour qu'un depot de 100 Mo ne charge pas 100 Mo en memoire.
TRANCHE = 1024 * 1024

SIGNATURES = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "tif": (b"II*\x00", b"MM\x00*"),
    "tiff": (b"II*\x00", b"MM\x00*"),
    # Office historique : OLE. Office moderne et ODF : ZIP.
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"),
    "docx": (b"PK\x03\x04",),
    "xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"),
    "xlsx": (b"PK\x03\x04",),
    "odt": (b"PK\x03\x04",),
    "ods": (b"PK\x03\x04",),
}


def racine() -> Path:
    """
    Le volume des pieces jointes.

    Sous `MEDIA_ROOT`, dans un sous-repertoire nomme : `MEDIA_ROOT` peut servir
    a autre chose un jour, et melanger les pieces jointes a des exports ou des
    fichiers temporaires rendrait toute sauvegarde selective impossible.
    """
    return Path(settings.MEDIA_ROOT) / "pieces"


def empreinte_et_taille(fichier) -> tuple[str, int]:
    """
    Le SHA-256 et le poids reel, calcules **en lisant le fichier**.

    Le poids annonce par le client n'est pas utilise : il est declaratif, et
    rien n'oblige un client a dire la verite. C'est aussi ce qui rend le
    plafond de taille controlable — un plafond verifie sur un nombre envoye
    par celui qu'on veut limiter ne limite personne.

    Le curseur est remis a zero en sortant : l'appelant ecrit ensuite le meme
    flux, et un fichier deja consomme s'ecrirait vide sans qu'aucune erreur ne
    se produise.
    """
    condensat = hashlib.sha256()
    taille = 0

    fichier.seek(0)
    for tranche in iter(lambda: fichier.read(TRANCHE), b""):
        condensat.update(tranche)
        taille += len(tranche)
    fichier.seek(0)

    return condensat.hexdigest(), taille


def chemin_de(empreinte: str) -> str:
    """Le chemin relatif d'une piece, derive de son empreinte."""
    return f"{empreinte[:2]}/{empreinte[2:4]}/{empreinte}"


def verifier_signature(fichier, extension: str, nom: str) -> None:
    """
    Refuse un contenu qui ne ressemble pas a son extension.

    Le type MIME declare par le client n'est pas une preuve. On controle ici les
    octets stables, au plus pres de l'ecriture disque, pour qu'un appel direct a
    `ecrire()` ne puisse pas contourner la garde de depot.
    """
    attendues = SIGNATURES.get(extension)
    if not attendues:
        return

    fichier.seek(0)
    debut = fichier.read(max(len(signature) for signature in attendues))
    fichier.seek(0)

    if not any(debut.startswith(signature) for signature in attendues):
        raise ErreurMetier(
            f"« {nom} » ne semble pas etre un fichier .{extension} valide.",
            code="signature_fichier_refusee",
        )


def ecrire(fichier, empreinte: str, *, extension: str, nom: str) -> str:
    """
    Pose le binaire sur le volume, et rend son chemin relatif.

    `extension` a deja ete comparee a la liste blanche metier par l'appelant.
    Ce module verifie ensuite la signature du contenu avant toute ecriture.

    **Si le fichier est deja la, rien n'est reecrit.** Meme empreinte, meme
    contenu : c'est la propriete du SHA-256, et la reecriture ne ferait que
    risquer de tronquer un fichier qu'une autre requete est en train de lire.

    L'ecriture passe par un fichier temporaire renomme ensuite. Un
    `write()` direct interrompu — disque plein, processus tue — laisserait un
    fichier partiel portant le nom d'une empreinte qui ne lui correspond plus,
    et toute verification d'integrite ulterieure echouerait sur une piece que
    personne ne saurait plus reconstruire.
    """
    verifier_signature(fichier, extension, nom)

    relatif = chemin_de(empreinte)
    absolu = racine() / relatif

    if absolu.exists():
        return relatif

    absolu.parent.mkdir(parents=True, exist_ok=True)
    provisoire = absolu.with_suffix(".partiel")

    fichier.seek(0)
    with provisoire.open("wb") as sortie:
        for tranche in iter(lambda: fichier.read(TRANCHE), b""):
            sortie.write(tranche)

    provisoire.replace(absolu)
    return relatif


def ouvrir(chemin_relatif: str):
    """
    Le binaire, en lecture.

    Leve `FileNotFoundError` si le fichier manque. L'appelant doit traiter ce
    cas : une ligne en base sans fichier sur le disque n'est pas impossible —
    restauration partielle, volume non monte — et repondre une erreur claire
    vaut mieux qu'une trace de pile.
    """
    return (racine() / chemin_relatif).open("rb")

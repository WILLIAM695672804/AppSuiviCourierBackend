"""
Rendre un document et le servir — la derniere marche de la chaine (ADR 023).

`structure` compose, `rendu_docx` verse dans le gabarit, `conversion` tire le
PDF. Restait, dans chaque route qui edite, une quarantaine de lignes toujours
identiques : choisir le format, ecrire dans un repertoire temporaire, convertir,
relire les octets, traduire les deux pannes de LibreOffice en 503 parlants.

Elles etaient ecrites une fois, dans `pilotage/api.py`. Au deuxieme document —
le registre des courriers, le 19 aout 2026 — les recopier aurait garanti que
l'une des deux finisse par rendre un `Content-Type` faux ou par avaler une
`ConversionEchouee`. Ce module les porte pour toutes.

Il ne connait aucun pilier, et ne rend pas de `HttpResponse` : il rend les
octets et leur type MIME. La route reste maitresse de son en-tete et de sa
trace — c'est elle qui sait ce qu'elle expose et a qui.
"""

import tempfile
import unicodedata
from pathlib import Path

from noyau.documents import conversion, rendu_docx
from noyau.documents.structure import Document
from noyau.erreurs import ErreurMetier

#: Les deux formats servis, et ce que le navigateur doit en faire.
FORMATS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def produire(document: Document, format: str) -> tuple[bytes, str]:
    """
    Le document en octets, et son type MIME.

    Le repertoire ne survit pas a l'appel : le fichier est lu en memoire avant
    d'etre rendu. Un document institutionnel pese quelques dizaines de
    kilo-octets ; le garder sur disque aurait demande de savoir quand le
    supprimer, ce que personne ne sait.
    """
    if format not in FORMATS:
        raise ErreurMetier(
            f"Format « {format} » inconnu. Formats servis : {', '.join(FORMATS)}.",
            code="format_inconnu",
            statut=400,
        )

    with tempfile.TemporaryDirectory(prefix="document-") as temporaire:
        dossier = Path(temporaire)
        fichier = rendu_docx.ecrire(document, dossier / "document.docx")

        if format == "pdf":
            try:
                fichier = conversion.en_pdf(fichier, dossier)
            except conversion.ConversionIndisponible as absent:
                # 503 et non 500 : ce n'est pas un bogue du document, c'est un
                # serveur incomplet. Le message dit ce qui debloque — telecharger
                # le Word — plutot que de laisser l'agent chercher.
                raise ErreurMetier(
                    "Le PDF n'est pas disponible sur ce serveur : LibreOffice n'y est "
                    "pas installé. Le format Word reste téléchargeable.",
                    code="pdf_indisponible",
                    statut=503,
                ) from absent
            except conversion.ConversionEchouee as echec:
                raise ErreurMetier(
                    f"La production du PDF a échoué. {echec} Le format Word reste téléchargeable.",
                    code="pdf_echoue",
                    statut=503,
                ) from echec

        return fichier.read_bytes(), FORMATS[format]


def nom_de_fichier(reference: str, format: str, *, prefixe: str = "") -> str:
    """
    « registre-arrivee-2026-08-19.pdf » — nommable, triable, sans accent.

    Un nom de fichier finit dans un dossier partage, dans une piece jointe de
    courriel, parfois sur une cle USB : les accents et les espaces y survivent
    mal, et un fichier qu'on ne retrouve pas vaut un fichier qu'on n'a pas
    produit.
    """
    sans_accent = (
        unicodedata.normalize("NFKD", reference).encode("ascii", "ignore").decode().lower()
    )
    propre = "".join(caractere if caractere.isalnum() else "-" for caractere in sans_accent)
    while "--" in propre:
        propre = propre.replace("--", "-")
    propre = propre.strip("-")
    if prefixe and not propre.startswith(prefixe):
        propre = f"{prefixe}-{propre}"
    return f"{propre}.{format}"

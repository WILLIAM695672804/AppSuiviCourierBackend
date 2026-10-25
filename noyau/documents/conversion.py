"""
Le .docx en PDF, par LibreOffice sans interface.

Seul module du depot a connaitre `soffice`. Le reste de la chaine ignore
qu'un binaire externe existe : c'est ce qui permettra de basculer en tache
Celery si la latence l'exige, sans toucher au rendu ni aux piliers.

**La conversion s'execute dans la requete**, et non en differe : l'utilisateur
attend son fichier, et Celery imposerait une route de scrutation et un stockage
intermediaire pour un travail d'une a deux secondes. Deux risques en decoulent,
et ce module les porte tous les deux :

 1. **Le profil.** Le premier lancement de LibreOffice cree un profil
    utilisateur. Deux processus qui partagent le meme profil se bloquent
    mutuellement : chaque appel recoit donc le sien, dans le repertoire
    temporaire de la conversion, supprime avec lui.
 2. **Le delai de garde.** Un `soffice` qui ne rend pas la main immobiliserait
    un ouvrier gunicorn. Au-dela du delai, le processus est tue et l'appelant
    recoit une erreur nommee.

Le .docx est produit **avant** la conversion et ne depend pas d'elle : un export
PDF en echec ne prive pas le Directeur general de sa note.
"""

import shutil
import subprocess
from pathlib import Path

from django.conf import settings


class ConversionIndisponible(RuntimeError):
    """LibreOffice n'est pas installe sur ce serveur. Cela se corrige a l'exploitation."""


class ConversionEchouee(RuntimeError):
    """LibreOffice a repondu, mais n'a pas produit de PDF."""


def binaire() -> str:
    return getattr(settings, "LIBREOFFICE_BINAIRE", "soffice")


def binaire_disponible() -> bool:
    """Sert aux tests, et a la route qui refuse le PDF plutot que de le tenter."""
    return shutil.which(binaire()) is not None


def commande_de_conversion(source: Path, dossier: Path, executable: str) -> list[str]:
    """
    La commande, isolee pour etre testable sans lancer LibreOffice.

    `pdf:writer_pdf_Export` et non `pdf` seul : sans filtre nomme, LibreOffice
    choisit selon l'extension d'entree et rend un PDF d'images sur certaines
    installations.
    """
    return [
        executable,
        "--headless",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation=file://{dossier / 'profil-libreoffice'}",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        str(dossier),
        str(source),
    ]


def en_pdf(source: Path, dossier: Path, *, delai: int | None = None) -> Path:
    """
    Convertit `source` et rend le chemin du PDF, ecrit dans `dossier`.

    `dossier` est un repertoire temporaire dont l'appelant a la charge : c'est
    lui qui le cree et le supprime, parce que c'est lui qui sait quand le
    fichier a ete servi.
    """
    executable = shutil.which(binaire())
    if executable is None:
        raise ConversionIndisponible(
            f"LibreOffice est introuvable ({binaire()}). "
            "Le format Word reste disponible ; le PDF demande une installation "
            "sur le serveur applicatif."
        )

    garde = delai if delai is not None else getattr(settings, "LIBREOFFICE_DELAI", 60)

    try:
        acheve = subprocess.run(  # commande construite ici (commande_de_conversion), sans shell
            commande_de_conversion(source, dossier, executable),
            capture_output=True,
            timeout=garde,
            check=False,
        )
    except subprocess.TimeoutExpired as expiration:
        raise ConversionEchouee(
            f"La conversion en PDF a dépassé le délai de {garde} s et a été interrompue."
        ) from expiration

    pdf = dossier / f"{source.stem}.pdf"
    if not pdf.exists():
        raise ConversionEchouee(
            "LibreOffice n'a produit aucun PDF. "
            f"Code de sortie {acheve.returncode}. "
            f"Sortie : {acheve.stderr.decode('utf8', 'replace')[:400]}"
        )
    return pdf

"""
La conversion en PDF — la seule couche qui connait LibreOffice.

**Les tests portent d'abord sur l'echec.** Le cas nominal se voit a l'oeil ;
c'est l'echec qui se comporte mal si on ne l'ecrit pas — un `soffice` qui ne
rend jamais la main immobilise un ouvrier gunicorn, et l'ecran du Directeur
general tourne indefiniment sans rien dire.
"""

from pathlib import Path

import pytest

from noyau.documents import conversion


def test_un_binaire_absent_leve_une_erreur_nommee(tmp_path, settings):
    """
    Et non un `FileNotFoundError` brut.

    La route doit pouvoir distinguer « LibreOffice n'est pas installe sur ce
    serveur » — qui se corrige a l'exploitation — d'un document mal forme.
    """
    settings.LIBREOFFICE_BINAIRE = "soffice-qui-n-existe-pas"
    source = tmp_path / "note.docx"
    source.write_bytes(b"PK\x03\x04")

    with pytest.raises(conversion.ConversionIndisponible):
        conversion.en_pdf(source, tmp_path)


def test_un_document_illisible_leve_une_erreur_de_conversion(tmp_path):
    """
    LibreOffice sort sans rien produire : on ne rend pas un chemin mort.

    Du texte brut sous extension `.docx` ne suffit pas a faire echouer
    LibreOffice : son filtre de secours l'importe comme texte et rend quand
    meme un PDF. Il faut du binaire que meme ce filtre refuse.
    """
    source = tmp_path / "note.docx"
    source.write_bytes(b"\x00\x01\x02garbage non lisible\xff\xfe")

    with pytest.raises(conversion.ConversionEchouee):
        conversion.en_pdf(source, tmp_path, delai=60)


def test_le_delai_de_garde_est_respecte(tmp_path, settings):
    """
    Un `soffice` qui ne rend pas la main est tue.

    Un script qui dort tient lieu de LibreOffice bloque : ce qui est teste
    est la garde, pas le convertisseur. `sleep` seul ne convient pas ici —
    les options de la commande de conversion (`--headless`, `-env:...`) sont
    des arguments que GNU `sleep` refuse d'emblee au lieu de dormir.
    """
    script = tmp_path / "soffice-qui-bloque.sh"
    script.write_text("#!/bin/sh\nsleep 5\n")
    script.chmod(0o755)
    settings.LIBREOFFICE_BINAIRE = str(script)
    source = tmp_path / "note.docx"
    source.write_bytes(b"PK\x03\x04")

    with pytest.raises(conversion.ConversionEchouee, match="délai"):
        conversion.en_pdf(source, tmp_path, delai=1)


def test_chaque_appel_recoit_son_profil(tmp_path):
    """
    Deux `soffice` qui partagent un profil se bloquent mutuellement.

    C'est un piege documente : sans profil isole, la deuxieme conversion
    simultanee attend la premiere sans jamais aboutir.
    """
    commande = conversion.commande_de_conversion(Path("/tmp/n.docx"), tmp_path, "soffice")

    profil = [morceau for morceau in commande if morceau.startswith("-env:UserInstallation=")]
    assert profil, "Aucun profil isole dans la commande"
    assert str(tmp_path) in profil[0]


@pytest.mark.skipif(
    conversion.binaire_disponible() is False,
    reason="LibreOffice absent de cette machine",
)
def test_un_docx_valide_donne_un_pdf(tmp_path):
    """Le cas nominal, saute la ou LibreOffice n'est pas installe."""
    from noyau.documents import rendu_docx
    from noyau.documents.structure import Document, Paragraphe, Section

    source = rendu_docx.ecrire(
        Document(
            titre="Note d'essai",
            surtitre="Division du suivi et de la relance",
            sous_titre="Essai",
            reference="ESSAI-1",
            sections=(Section(titre="Objet", blocs=(Paragraphe(texte="Un essai."),)),),
        ),
        tmp_path / "note.docx",
    )

    pdf = conversion.en_pdf(source, tmp_path)

    assert pdf.suffix == ".pdf"
    assert pdf.read_bytes().startswith(b"%PDF")

"""
La note de synthese en tant que document — §3.1 et §3.2.

Ce que ces tests protegent :

 1. **Le contenu varie avec les donnees.** C'est tout l'objet du chantier :
    une note qui sortirait identique quelle que soit la periode ne serait
    qu'une capture d'ecran avec un en-tete.
 2. **Une absence se dit.** ADR 011 : « aucun point n'appelle d'arbitrage » est
    une section, pas une section manquante.
 3. **Le classement long part en annexe.** Sinon les points d'arbitrage
    tombent en page trois et personne ne les lit.
"""

import pytest
from django.core.management import call_command

from gouvernance.modeles import Seance
from noyau.documents.structure import Chiffres, Encadre, Puces, Tableau
from noyau.identite.modeles import Utilisateur
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache
from pilotage import synthese as calcul

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
EXPORT = "/api/pilotage/synthese/export"


@pytest.fixture(autouse=True)
def parametres_neufs():
    vider_cache()
    yield
    vider_cache()


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


def _dg() -> Utilisateur:
    """
    Le lecteur de la note : la synthese se compose depuis le classement, et le
    classement depend desormais de qui le lit — le Directeur general consolide
    par tete de structure.
    """
    return Utilisateur.objects.get(identifiant_annuaire="dg")


def _titres(document) -> list[str]:
    return [titre for titre, _ in document.sections_numerotees()]


def test_la_note_porte_l_entete_institutionnel_et_sa_reference(jeu):
    document = calcul.synthese_document(_dg())

    assert document.surtitre
    assert document.titre.startswith("Note de synthèse")
    assert document.reference.startswith("NOTE-")


def test_les_sections_sont_numerotees_sans_trou(jeu):
    """La numerotation vient du rang, jamais d'un titre ecrit en dur."""
    numeros = [titre.split(".")[0] for titre in _titres(calcul.synthese_document(_dg()))]

    assert numeros == [str(rang) for rang in range(1, len(numeros) + 1)]


def test_les_faits_marquants_sont_des_phrases(jeu):
    """
    Des phrases et non des chiffres — c'est la raison d'etre du module.

    Un lecteur en seance ne recompose pas « 62 » et « 71 » en « l'execution a
    progresse de neuf points ».
    """
    document = calcul.synthese_document(_dg())
    section = document.sections[0]
    puces = [bloc for bloc in section.blocs if isinstance(bloc, Puces)]

    assert puces
    assert all(item.endswith(".") for item in puces[0].items)


def test_la_section_d_arbitrage_reste_meme_quand_il_n_y_a_rien(jeu):
    """
    ADR 011 : une absence se nomme.

    `_points_d_attention` produit deja un point « Aucun point d'attention »
    quand rien ne remonte ; la section ne doit pas etre ecartee pour autant.
    """
    document = calcul.synthese_document(_dg())
    encadres = [
        bloc for section in document.sections for bloc in section.blocs if isinstance(bloc, Encadre)
    ]

    assert encadres


def test_les_chiffres_d_ensemble_sortent_en_bloc_chiffres(jeu):
    document = calcul.synthese_document(_dg())
    chiffres = [
        bloc
        for section in document.sections
        for bloc in section.blocs
        if isinstance(bloc, Chiffres)
    ]

    assert chiffres
    assert len(chiffres[0].items) == 3


def test_un_classement_court_reste_dans_le_corps(jeu):
    """En deca du seuil, l'annexe n'apporterait qu'un aller-retour de lecture."""
    Parametre.objects.filter(cle="pilotage.lignes_avant_annexe").update(valeur="100")
    vider_cache()

    document = calcul.synthese_document(_dg())

    assert document.annexes == ()


def test_un_classement_long_part_en_annexe(jeu):
    """Au-dela du seuil, le corps garde une synthese et renvoie a l'annexe."""
    Parametre.objects.filter(cle="pilotage.lignes_avant_annexe").update(valeur="2")
    vider_cache()

    document = calcul.synthese_document(_dg())

    assert len(document.annexes) == 1
    assert "Classement" in document.annexes[0].titre

    tableaux_du_corps = [
        bloc for section in document.sections for bloc in section.blocs if isinstance(bloc, Tableau)
    ]
    complet = next(bloc for bloc in document.annexes[0].blocs if isinstance(bloc, Tableau))
    assert len(tableaux_du_corps[0].lignes) < len(complet.lignes)


def test_le_classement_porte_une_barre_de_score(jeu):
    """Le seul « graphique » de la note, et il reste editable dans Word."""
    Parametre.objects.filter(cle="pilotage.lignes_avant_annexe").update(valeur="100")
    vider_cache()

    document = calcul.synthese_document(_dg())
    tableau = next(
        bloc for section in document.sections for bloc in section.blocs if isinstance(bloc, Tableau)
    )

    assert any(cellule.barre is not None for ligne in tableau.lignes for cellule in ligne)


def test_le_document_et_l_ecran_lisent_les_memes_mesures(jeu):
    """
    Deux calculs auraient fini par donner deux chiffres.

    L'ecran (`synthese()`) et le document (`synthese_document()`) partent des
    memes fonctions de `mesures` : ce test le constate par le nombre de lignes
    du classement, qui est ce qui bougerait en premier.
    """
    ecran = calcul.synthese(_dg())
    Parametre.objects.filter(cle="pilotage.lignes_avant_annexe").update(valeur="100")
    vider_cache()
    document = calcul.synthese_document(_dg())

    tableau = next(
        bloc for section in document.sections for bloc in section.blocs if isinstance(bloc, Tableau)
    )
    assert len(tableau.lignes) == len(ecran["classement"])


@pytest.mark.parametrize("type_seance,libelle", Seance.TYPES)
def test_la_reference_reste_lisible_pour_chaque_type_de_seance(type_seance, libelle):
    """
    Une reference se cite a voix haute : « la note NOTE-CODIR du 3 septembre ».

    Les libelles reels vont du sigle deja constitue (« CODIR ») a la phrase
    (« Reunion presidee par le DG ») : le sigle doit rester court, non vide, et
    sans accent — la reference se retape a la main.
    """
    sigle = calcul._sigle_instance(libelle)

    assert sigle
    assert sigle.isascii()
    assert sigle.isupper()
    assert len(sigle) <= 8


# =====================================================================
#  L'export — GET /api/pilotage/synthese/export
# =====================================================================


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


def test_l_export_est_garde(client, jeu):
    """
    Une route de sortie sans garde n'ouvre pas une erreur : elle ouvre les
    chiffres de l'institution.
    """
    assert client.get(f"{EXPORT}?format=docx").status_code == 401


def test_l_export_word_rend_un_docx(connecte):
    reponse = connecte("dg").get(f"{EXPORT}?format=docx")

    assert reponse.status_code == 200
    assert "wordprocessingml" in reponse["Content-Type"]
    assert reponse.content.startswith(b"PK\x03\x04")


def test_le_nom_du_fichier_se_lit(connecte):
    """Il atterrit dans le dossier de telechargement d'un directeur."""
    reponse = connecte("dg").get(f"{EXPORT}?format=docx")

    assert "note-synthese-" in reponse["Content-Disposition"]
    assert reponse["Content-Disposition"].endswith('.docx"')


def test_le_nom_du_fichier_reprend_la_reference(jeu):
    """« NOTE-CODIR-2026-09-03 » se relit « note-synthese-codir-2026-09-03.docx »."""
    from pilotage.api import _nom_du_fichier

    assert _nom_du_fichier("NOTE-CODIR-2026-09-03", "docx") == "note-synthese-codir-2026-09-03.docx"
    assert _nom_du_fichier("NOTE-RPDG-2026-09-03", "pdf") == "note-synthese-rpdg-2026-09-03.pdf"


def test_un_format_inconnu_est_refuse(connecte):
    reponse = connecte("dg").get(f"{EXPORT}?format=odt")

    assert reponse.status_code == 400


def test_l_export_est_trace(connecte):
    """
    Sortir une donnee du systeme est un acte, pas une navigation — §3.12.

    C'est la meme regle que `GET /pilotage/rapports/export`, la seule autre
    route du pilotage a sortir un fichier.
    """
    from django.db import connection

    connecte("dg").get(f"{EXPORT}?format=docx")

    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT count(*) FROM journal_acces WHERE objet_type = %s AND action = %s",
            ["note_synthese", "export"],
        )
        assert curseur.fetchone()[0] == 1


def test_le_pdf_repond_proprement_quand_libreoffice_manque(connecte, settings):
    """
    Le format Word reste servi ; le PDF dit pourquoi il ne l'est pas.

    Une page blanche, ou un 500, aurait envoye le Directeur general chercher
    un bogue dans la note.
    """
    settings.LIBREOFFICE_BINAIRE = "soffice-qui-n-existe-pas"

    reponse = connecte("dg").get(f"{EXPORT}?format=pdf")

    assert reponse.status_code == 503
    assert "Word" in reponse.json()["message"]

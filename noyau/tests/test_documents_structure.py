"""
Le document en objets neutres — la couche que les piliers composent.

Ce que ces tests protegent :

 1. **Les imports existants survivent au passage en paquet.** `pilotage`
    importe `noyau.documents` depuis l'export CSV des rapports ; si le
    reexport saute, c'est l'export qui tombe, pas ce module.
 2. **Une section vide ne disparait que si son absence ne dit rien.** C'est
    l'ADR 011 : le pilotage nomme ce qu'il ne mesure pas.
 3. **La numerotation se recalcule.** Elle n'est jamais ecrite dans un titre.
"""

import pytest

from noyau import documents
from noyau.documents.structure import (
    Cellule,
    Chiffre,
    Chiffres,
    Colonne,
    Document,
    Encadre,
    Paragraphe,
    Puces,
    Section,
    Tableau,
    retenir,
)


def test_les_imports_existants_survivent_au_paquet():
    """`pilotage/rapports.py` importe ces deux noms depuis `noyau.documents`."""
    lignes = documents.entete_lignes()

    assert lignes[0] == ("République du Cameroun", "Republic of Cameroon")
    assert len(lignes) == len(documents.ENTETE)


def test_entete_lignes_rend_une_copie():
    """Un appelant qui trie sa liste ne trie pas l'en-tete de tout le monde."""
    premiere = documents.entete_lignes()
    premiere.clear()

    assert documents.entete_lignes() != []


def _section(titre: str, texte: str = "Un contenu.") -> Section:
    return Section(titre=titre, blocs=(Paragraphe(texte=texte),))


def test_retenir_ecarte_les_sections_absentes_et_vides():
    """Une section sans bloc n'a rien a dire : elle ne prend pas une page."""
    gardees = retenir(_section("Faits marquants"), None, Section(titre="Vide", blocs=()))

    assert [section.titre for section in gardees] == ["Faits marquants"]


def test_une_section_qui_dit_une_absence_est_retenue():
    """
    « Aucun point n'appelle d'arbitrage » est une information — ADR 011.

    C'est au compositeur de la note de produire cette phrase ; `retenir` ne
    peut pas deviner qu'une absence est parlante. Le test fixe la frontiere :
    une section porteuse d'une phrase passe, meme si la phrase dit un vide.
    """
    section = _section("Points appelant un arbitrage", "Aucun point n'appelle d'arbitrage.")

    assert retenir(section) == (section,)


def test_la_numerotation_se_recalcule():
    """Le numero n'est jamais ecrit dans un titre : il se deduit du rang."""
    document = _document(sections=(_section("Faits marquants"), _section("Chiffres")))

    assert document.sections_numerotees() == (
        ("1. Faits marquants", document.sections[0]),
        ("2. Chiffres", document.sections[1]),
    )


def test_les_annexes_sont_lettrees_et_non_numerotees():
    """« Annexe A », pour qu'un renvoi du corps ne se confonde pas avec 5."""
    document = _document(
        sections=(_section("Faits marquants"),),
        annexes=(_section("Classement complet"), _section("Detail des decisions")),
    )

    assert [titre for titre, _ in document.annexes_lettrees()] == [
        "Annexe A — Classement complet",
        "Annexe B — Detail des decisions",
    ]


def test_un_document_sans_section_est_refuse():
    """
    Un document vide est un bogue de composition, pas un document.

    L'agent qui recoit un PDF d'une page blanche sous en-tete officiel ne
    signale pas un bogue : il conclut qu'il n'y avait rien a dire.
    """
    with pytest.raises(ValueError, match="au moins une section"):
        _document(sections=())


def test_une_barre_hors_bornes_est_refusee():
    """Une barre a 140 % deborderait de sa cellule sans que rien ne le dise."""
    with pytest.raises(ValueError, match="entre 0 et 100"):
        Cellule(texte="140", barre=140)


def _document(
    sections: tuple[Section, ...],
    annexes: tuple[Section, ...] = (),
) -> Document:
    return Document(
        titre="Note de synthèse",
        surtitre="Division du suivi et de la relance",
        sous_titre="Séance du 3 septembre 2026",
        reference="NOTE-CODIR-2026-09",
        sections=sections,
        annexes=annexes,
    )


def test_un_tableau_verifie_la_largeur_de_ses_lignes():
    """Trois en-tetes et deux cellules : le rendu decalerait tout en silence."""
    with pytest.raises(ValueError, match="3 colonnes"):
        Tableau(
            colonnes=(Colonne(entete="Rang"), Colonne(entete="Structure"), Colonne(entete="Score")),
            lignes=((Cellule(texte="1"), Cellule(texte="DSR")),),
        )


def test_les_blocs_composites_acceptent_ce_qu_on_leur_donne():
    """Un test de fumee sur les types restants : ils doivent s'instancier."""
    chiffres = Chiffres(items=(Chiffre(libelle="Exécution", valeur="62 %"),))
    puces = Puces(items=("Un fait.", "Un autre."))
    encadre = Encadre(titre="Structures sous le seuil", texte="DSI, DAJ.", feu="rouge")

    section = Section(titre="Chiffres d'ensemble", blocs=(chiffres, puces, encadre))

    assert len(section.blocs) == 3

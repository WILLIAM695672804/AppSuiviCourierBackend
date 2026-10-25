"""
La traduction d'un document dans le gabarit Word officiel.

Seul module du depot a importer python-docx. Un pilier metier compose une
`structure.Document` et ne passe jamais par ici.

**Regle unique et non negociable : aucune mise en forme directe.** Chaque
paragraphe recoit un style nomme du gabarit (`Titre section`, `Corps document`,
`Cellule tableau`…). Une taille de police ou une couleur posee dans ce fichier
survivrait au premier rendu et divergerait du modele des que la DSR en remet un
nouveau. Les tests `test_le_rendu_n_ecrit_aucune_mise_en_forme_directe` et
`test_aucune_mise_en_forme_directe_dans_les_cellules` en sont le garde-fou.

Le seul endroit ou l'on descend dans le XML est l'ombrage des cellules :
python-docx ne l'expose pas, et c'est ce qui porte les barres de score et les
feux. Une barre est un tableau imbrique de deux cellules, pas une image — le
document reste editable par le secretariat avant la seance (ADR 023).
"""

from pathlib import Path
from typing import Any

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm

from noyau.documents.structure import (
    Bloc,
    Chiffres,
    Document,
    Encadre,
    Paragraphe,
    Puces,
    Section,
    Tableau,
)

GABARIT = Path(__file__).parent / "gabarits" / "pad-officiel.docx"

#: Le style de tableau du gabarit — celui qui porte les filets. Il est pose par
#: `scripts/preparer_gabarit.py` : le trait est une affaire de gabarit, pas de
#: code. « Table Grid » n'existe pas dans un document francais.
STYLE_TABLEAU = "Tableau document"

#: Largeur utile d'une A4 aux marges du gabarit. Sert a repartir les colonnes
#: selon leur poids : la structure dit « quatre fois plus large », pas
#: « 72 mm » — une mesure dans un pilier metier serait de la mise en page.
LARGEUR_UTILE_MM = 170

#: Largeur d'une barre de score, en millimetres. Elle tient dans la colonne de
#: cotation du classement, la plus etroite qui en porte une.
LARGEUR_BARRE_MM = 28

#: Les teintes des feux. Claires : elles doivent rester lisibles sous du texte
#: noir, et une note s'imprime souvent en niveaux de gris.
TEINTES = {
    "vert": "DCEFE1",
    "orange": "FBE7CD",
    "rouge": "F8D7DA",
    "inconnu": "EDEFF2",
}

#: Le remplissage d'une barre de score, et son creux.
BARRE_PLEINE = "5A6478"
BARRE_CREUSE = "EDEFF2"


def ecrire(document: Document, destination: Path) -> Path:
    """
    Ecrit le document dans le gabarit et rend le chemin du fichier.

    `destination` est un chemin complet, extension comprise. L'appelant choisit
    ou : c'est lui qui sait si le fichier est temporaire ou conserve.
    """
    if not GABARIT.exists():
        raise FileNotFoundError(
            f"Gabarit absent : {GABARIT}. Le produire avec "
            "`./.venv/bin/python scripts/preparer_gabarit.py`."
        )

    fichier = docx.Document(str(GABARIT))

    _ecrire_le_titre(fichier, document)
    for titre, section in document.sections_numerotees():
        _ecrire_la_section(fichier, titre, section, style_titre="Titre section")
    for titre, annexe in document.annexes_lettrees():
        fichier.add_page_break()
        _ecrire_la_section(fichier, titre, annexe, style_titre="Titre annexe")
    _poser_la_reference(fichier, document.reference)

    destination.parent.mkdir(parents=True, exist_ok=True)
    fichier.save(str(destination))
    return destination


def _ecrire_le_titre(fichier: Any, document: Document) -> None:
    fichier.add_paragraph(document.surtitre, style="Surtitre note")
    fichier.add_paragraph(document.titre, style="Titre note")
    fichier.add_paragraph(document.sous_titre, style="Sous-titre note")


def _ecrire_la_section(fichier: Any, titre: str, section: Section, *, style_titre: str) -> None:
    fichier.add_paragraph(titre, style=style_titre)
    for bloc in section.blocs:
        _ecrire_le_bloc(fichier, bloc)


def _ecrire_le_bloc(fichier: Any, bloc: Bloc) -> None:
    if isinstance(bloc, Paragraphe):
        fichier.add_paragraph(bloc.texte, style="Corps document")
    elif isinstance(bloc, Puces):
        for item in bloc.items:
            fichier.add_paragraph(f"— {item}", style="Puce document")
    elif isinstance(bloc, Chiffres):
        _ecrire_les_chiffres(fichier, bloc)
    elif isinstance(bloc, Tableau):
        _ecrire_le_tableau(fichier, bloc)
    elif isinstance(bloc, Encadre):
        _ecrire_l_encadre(fichier, bloc)
    else:  # pragma: no cover — l'union `Bloc` est fermee
        raise TypeError(f"Bloc inconnu au rendu : {type(bloc).__name__}")


def _ecrire_les_chiffres(fichier: Any, bloc: Chiffres) -> None:
    """
    Les chiffres cote a cote, dans un tableau sans bordure.

    Un tableau et non des tabulations : trois chiffres alignes a la tabulation
    se decalent des qu'un libelle s'allonge, et la note part chez le Directeur
    general.
    """
    tableau = fichier.add_table(rows=2, cols=len(bloc.items))
    tableau.autofit = False
    largeur = Mm(LARGEUR_UTILE_MM / len(bloc.items))
    for rang, chiffre in enumerate(bloc.items):
        _remplir(tableau.cell(0, rang), chiffre.libelle, "Libelle chiffre")
        _remplir(tableau.cell(1, rang), chiffre.valeur, "Valeur chiffre")
        tableau.cell(0, rang).width = largeur
        tableau.cell(1, rang).width = largeur


def _ecrire_le_tableau(fichier: Any, bloc: Tableau) -> None:
    tableau = fichier.add_table(rows=1 + len(bloc.lignes), cols=len(bloc.colonnes))
    tableau.style = STYLE_TABLEAU
    tableau.autofit = False

    total = sum(colonne.poids for colonne in bloc.colonnes)
    for rang, colonne in enumerate(bloc.colonnes):
        cellule = tableau.cell(0, rang)
        _remplir(cellule, colonne.entete, "Entete tableau", a_droite=colonne.a_droite)
        cellule.width = Mm(LARGEUR_UTILE_MM * colonne.poids / total)

    for numero, ligne in enumerate(bloc.lignes, start=1):
        for rang, contenu in enumerate(ligne):
            cellule = tableau.cell(numero, rang)
            _remplir(
                cellule,
                contenu.texte,
                "Cellule tableau",
                a_droite=bloc.colonnes[rang].a_droite,
            )
            cellule.width = Mm(LARGEUR_UTILE_MM * bloc.colonnes[rang].poids / total)
            if contenu.feu:
                _ombrer(cellule, TEINTES[contenu.feu])
            if contenu.barre is not None:
                _poser_la_barre(cellule, contenu.barre)

    if bloc.legende:
        fichier.add_paragraph(bloc.legende, style="Legende tableau")


def _ecrire_l_encadre(fichier: Any, bloc: Encadre) -> None:
    """
    Un point d'arbitrage : un titre, un texte, et le feu en teinte de fond.

    Le feu teinte, il ne dit pas : le libelle reste dans le titre. Une note
    photocopiee en noir et blanc perd la couleur, jamais l'information.
    """
    tableau = fichier.add_table(rows=1, cols=1)
    tableau.style = STYLE_TABLEAU
    tableau.autofit = False
    cellule = tableau.cell(0, 0)
    cellule.width = Mm(LARGEUR_UTILE_MM)
    _remplir(cellule, bloc.titre, "Titre encadre")
    cellule.add_paragraph(bloc.texte, style="Corps document")
    if bloc.feu:
        _ombrer(cellule, TEINTES[bloc.feu])


def _remplir(cellule: Any, texte: str, style: str, *, a_droite: bool = False) -> None:
    """
    Ecrit dans une cellule en remplacant son paragraphe vide d'origine.

    Le style se pose **apres** le texte : `paragraphe.text = …` reconstruit le
    passage, et l'ordre inverse laisserait un passage sans style, donc rendu
    dans la police par defaut de Word.
    """
    paragraphe = cellule.paragraphs[0]
    paragraphe.text = texte
    paragraphe.style = style
    if a_droite:
        paragraphe.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _ombrer(cellule: Any, teinte: str) -> None:
    """
    Teinte le fond d'une cellule.

    python-docx n'expose pas `w:shd` : c'est l'un des deux endroits du depot ou
    l'on descend dans le XML de Word, et il est borne a cette fonction.
    """
    ombre = OxmlElement("w:shd")
    ombre.set(qn("w:val"), "clear")
    ombre.set(qn("w:color"), "auto")
    ombre.set(qn("w:fill"), teinte)
    cellule._tc.get_or_add_tcPr().append(ombre)


def _poser_la_barre(cellule: Any, pourcentage: int) -> None:
    """
    Une barre de remplissage, en cellules ombrees.

    Deux cellules d'un tableau imbrique — plein a gauche, creux a droite —
    plutot qu'une image : le document reste editable par le secretariat, et le
    trait est net a toute echelle d'impression (ADR 023). A 0 ou a 100, une
    seule cellule : une cellule de largeur nulle est un tableau invalide, que
    Word ouvre en signalant une erreur.
    """
    barre = cellule.add_table(rows=1, cols=2 if 0 < pourcentage < 100 else 1)
    barre.autofit = False
    largeur = Mm(LARGEUR_BARRE_MM)

    if pourcentage <= 0:
        barre.cell(0, 0).width = largeur
        _ombrer(barre.cell(0, 0), BARRE_CREUSE)
        return
    if pourcentage >= 100:
        barre.cell(0, 0).width = largeur
        _ombrer(barre.cell(0, 0), BARRE_PLEINE)
        return

    barre.cell(0, 0).width = Mm(LARGEUR_BARRE_MM * pourcentage / 100)
    barre.cell(0, 1).width = Mm(LARGEUR_BARRE_MM * (100 - pourcentage) / 100)
    _ombrer(barre.cell(0, 0), BARRE_PLEINE)
    _ombrer(barre.cell(0, 1), BARRE_CREUSE)


def _poser_la_reference(fichier: Any, reference: str) -> None:
    """
    La reference du document, en derniere ligne du pied.

    Elle est posee au rendu et non dans le gabarit : elle change a chaque
    document, la « Page X sur Y » non.

    **Un nouveau paragraphe, jamais un paragraphe existant.** Le premier
    paragraphe du pied porte le bandeau legal sous forme d'image ancree, et le
    second la pagination : ecrire par-dessus l'un ou l'autre les effacerait
    sans qu'aucune erreur ne se produise.
    """
    pied = fichier.sections[0].footer
    pied.add_paragraph(reference, style="Legende tableau")

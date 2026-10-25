"""
Le document en objets neutres.

Ce module ne connait ni Word, ni HTML, ni le pilotage. C'est sa raison d'etre :
un pilier metier compose une `Document`, et l'on verifie ce qu'il a compose
sans ecrire un seul fichier. Le jour ou le bordereau de transmission et le
registre passeront par ici, ils ne reecriront pas la chaine.

**Les numeros de section ne sont jamais ecrits dans un titre.** Une section
peut disparaitre parce que la periode n'avait rien a y mettre ; un « 3. » fige
dans une chaine de caracteres produirait alors une note qui saute du 2 au 4.
La numerotation se deduit du rang, ici et nulle part ailleurs.
"""

from dataclasses import dataclass

#: Les feux du projet — `noyau.feu`. Repris en texte : ce module ne depend de
#: rien, et un import pour quatre chaines aurait couple la structure au calcul.
FEUX = ("vert", "orange", "rouge", "inconnu")


@dataclass(frozen=True)
class Paragraphe:
    """Un paragraphe de corps."""

    texte: str


@dataclass(frozen=True)
class Puces:
    """Une liste a puces. Les faits marquants en sont une."""

    items: tuple[str, ...]


@dataclass(frozen=True)
class Chiffre:
    """Un chiffre et ce qu'il compte."""

    libelle: str
    valeur: str


@dataclass(frozen=True)
class Chiffres:
    """Une rangee de chiffres, cote a cote."""

    items: tuple[Chiffre, ...]


@dataclass(frozen=True)
class Colonne:
    """
    Une colonne de tableau.

    `poids` est une largeur relative, pas une mesure : le rendu la traduit en
    millimetres selon la largeur utile de la page. Ecrire des millimetres ici
    aurait fait de la structure une mise en page.
    """

    entete: str
    poids: int = 1
    a_droite: bool = False


@dataclass(frozen=True)
class Cellule:
    """
    Une cellule.

    `barre` est un pourcentage de 0 a 100 : le rendu en fait une barre de
    remplissage. C'est le seul « graphique » de la chaine, et c'est
    volontaire — voir la spec, section 5.

    `feu` teinte la cellule **et** son texte reste lisible en noir et blanc :
    la couleur ajoute, elle ne porte jamais seule l'information.
    """

    texte: str
    barre: int | None = None
    feu: str | None = None

    def __post_init__(self) -> None:
        if self.barre is not None and not 0 <= self.barre <= 100:
            raise ValueError(f"Une barre se mesure entre 0 et 100, reçu {self.barre}.")
        if self.feu is not None and self.feu not in FEUX:
            raise ValueError(f"Feu inconnu : {self.feu}. Attendus : {', '.join(FEUX)}.")


@dataclass(frozen=True)
class Tableau:
    """Un tableau a en-tete. `legende` se pose dessous, en petit."""

    colonnes: tuple[Colonne, ...]
    lignes: tuple[tuple[Cellule, ...], ...]
    legende: str = ""

    def __post_init__(self) -> None:
        attendu = len(self.colonnes)
        for rang, ligne in enumerate(self.lignes, start=1):
            if len(ligne) != attendu:
                raise ValueError(
                    f"La ligne {rang} porte {len(ligne)} cellules pour "
                    f"{attendu} colonnes : le rendu decalerait le tableau."
                )


@dataclass(frozen=True)
class Encadre:
    """Un point qui appelle une decision : un titre, un texte, un feu."""

    titre: str
    texte: str
    feu: str | None = None

    def __post_init__(self) -> None:
        if self.feu is not None and self.feu not in FEUX:
            raise ValueError(f"Feu inconnu : {self.feu}. Attendus : {', '.join(FEUX)}.")


#: Ce qu'une section peut contenir.
Bloc = Paragraphe | Puces | Chiffres | Tableau | Encadre


@dataclass(frozen=True)
class Section:
    """Une section, sans son numero : il se calcule au rendu."""

    titre: str
    blocs: tuple[Bloc, ...]


@dataclass(frozen=True)
class Document:
    """
    Un document pret a rendre.

    `reference` se pose au pied de chaque page, sous le bandeau legal : c'est
    ce qu'on cite quand on rappelle la note en seance.
    """

    titre: str
    surtitre: str
    sous_titre: str
    reference: str
    sections: tuple[Section, ...]
    annexes: tuple[Section, ...] = ()

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError(
                "Un document porte au moins une section : une page blanche sous "
                "en-tete officiel se lit comme « rien a signaler »."
            )

    def sections_numerotees(self) -> tuple[tuple[str, Section], ...]:
        """Les sections, avec le numero recalcule depuis leur rang."""
        return tuple(
            (f"{rang}. {section.titre}", section)
            for rang, section in enumerate(self.sections, start=1)
        )

    def annexes_lettrees(self) -> tuple[tuple[str, Section], ...]:
        """
        Les annexes, lettrees.

        Lettrees et non numerotees : « voir l'annexe A » ne se confond pas avec
        « voir le point 5 » quand la note est lue a voix haute en seance.
        """
        return tuple(
            (f"Annexe {chr(ord('A') + rang)} — {annexe.titre}", annexe)
            for rang, annexe in enumerate(self.annexes)
        )


def retenir(*candidates: Section | None) -> tuple[Section, ...]:
    """
    Les sections qui ont quelque chose a dire.

    Ecarte les `None` et les sections sans bloc. **Elle n'ecarte pas une
    section qui dit une absence** : « aucun point n'appelle d'arbitrage » est
    une information, et la taire la ferait passer pour un oubli (ADR 011).
    C'est au compositeur de produire cette phrase plutot que de rendre la
    section vide.
    """
    return tuple(section for section in candidates if section is not None and section.blocs)

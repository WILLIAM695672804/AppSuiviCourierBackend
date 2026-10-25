"""
Le feu tricolore, en un seul endroit.

Vert, orange, rouge, inconnu — c'est ce que le front affiche partout : sur une
activite, sur un engagement, sur une obligation. Trois piliers, une seule regle.

**Deux seuils recopies sont deux seuils qui divergeront.** Le jour ou la DSR
decidera qu'un avancement de 80 % est encore vert, la modification doit se faire
ici et nulle part ailleurs — sinon le tableau de bord des activites et celui de
la gouvernance donneront deux couleurs pour le meme chiffre.

Les valeurs viendront du dictionnaire des indicateurs que la DSR administre ; en
attendant elles sont ici, comme dans `frontend/src/lib/feu.ts`.
"""

#: Au-dessus : vert. La cible est tenue.
SEUIL_VERT = 85
#: Au-dessus : orange. En dessous : rouge.
SEUIL_ORANGE = 60


def feu(taux: float | None) -> str:
    """
    La couleur d'un taux.

    `None` sort en « inconnu » et non en rouge : une mesure absente n'est pas
    une mauvaise mesure, et les confondre ferait paraitre en alerte tout ce qui
    n'est pas encore renseigne.
    """
    if taux is None:
        return "inconnu"
    if taux >= SEUIL_VERT:
        return "vert"
    if taux >= SEUIL_ORANGE:
        return "orange"
    return "rouge"

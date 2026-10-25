"""
Erreurs metier.

A distinguer d'une erreur de saisie. Une saisie invalide se corrige dans le
formulaire ; une erreur metier dit que l'etat du systeme interdit le geste :
declarer un avancement sur une activite suspendue, soumettre un plan deja
soumis, lever une instruction deja levee.

Le message est affiche tel quel a l'agent par
`frontend/src/lib/erreurApi.ts`. Il doit donc etre ecrit pour lui : dire ce
qui bloque, et ce qui debloquerait. « Conflit d'etat » n'apprend rien a
personne.
"""


class ErreurMetier(Exception):
    """Une regle de gestion refuse l'ecriture."""

    statut = 409
    code = "regle_metier"

    def __init__(self, message: str, *, code: str | None = None, statut: int | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if statut:
            self.statut = statut


class EtatInvalide(ErreurMetier):
    """Le geste est impossible dans l'etat actuel de l'objet."""

    code = "etat_invalide"


class HorsPerimetre(ErreurMetier):
    """
    L'objet existe, mais hors du perimetre de l'agent.

    404 et non 403 : repondre « interdit » confirme l'existence de l'objet.
    Sur un courrier confidentiel, cette confirmation est deja une fuite
    (decision de cadrage D5).
    """

    statut = 404
    code = "introuvable"

    def __init__(self, message: str = "Objet introuvable.") -> None:
        super().__init__(message)

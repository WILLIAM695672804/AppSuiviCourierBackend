"""
Les periodes d'un rapport — mois, trimestre, semestre, exercice.

Un rapport periodique porte sur une periode **close**. C'est la seule regle de
ce module, et elle explique tout le reste : un rapport de juillet imprime le
20 juillet et un rapport de juillet imprime le 3 aout n'auraient pas les memes
chiffres, et le second aurait raison. Publier un document date dont le contenu
bouge encore, c'est publier un chiffre que personne ne peut verifier.

Une periode demandee qui n'est pas close n'est donc pas une erreur : elle est
**ramenee** a la derniere close, et le serveur dit dans sa reponse ce qu'il a
applique. C'est le raisonnement de l'ADR 009 pour le perimetre, tenu ici pour
le temps : un lien partage en fin de trimestre ne doit pas rendre 400 a qui n'a
rien fait de mal.

Le decoupage suit **l'exercice**, dont le premier mois est un parametre :
`pilotage.mois_debut_exercice`. Il vaut 1 — l'annee civile — et c'est une
**hypothese** : aucun document fourni ne fixe l'exercice budgetaire du Port
(A52). Le poser en base plutot qu'en dur evite la seule chose qui ne se
rattrape pas — un rapport annuel dont les bornes seraient fausses et qu'il
faudrait redeployer pour corriger.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from noyau.calendrier import MOIS_LONGS, libelle_mois
from noyau.parametres.service import valeur

MOIS = "mois"
TRIMESTRE = "trimestre"
SEMESTRE = "semestre"
ANNEE = "annee"

#: Le nombre de mois que couvre chaque granularite. Sert aussi de referentiel
#: ferme : une granularite inconnue vaut `mois`, la plus courte — une faute de
#: frappe dans une adresse ne doit pas sortir un rapport annuel.
DUREES = {MOIS: 1, TRIMESTRE: 3, SEMESTRE: 6, ANNEE: 12}


@dataclass(frozen=True)
class Periode:
    """Une periode close, bornes incluses."""

    granularite: str
    annee: int
    #: Le rang de la periode dans l'**exercice** : 1 a 12 pour un mois, 1 a 4
    #: pour un trimestre, 1 ou 2 pour un semestre, toujours 1 pour un exercice.
    rang: int
    debut: date
    fin: date
    libelle: str

    @property
    def code(self) -> str:
        """« 2026-T2 » — ce qui nomme un fichier d'export sans ambiguite."""
        prefixes = {MOIS: "M", TRIMESTRE: "T", SEMESTRE: "S", ANNEE: "A"}
        return f"{self.annee}-{prefixes[self.granularite]}{self.rang}"


def resoudre(
    granularite: str = MOIS,
    annee: int | None = None,
    rang: int | None = None,
    *,
    aujourd_hui: date | None = None,
) -> tuple[Periode, bool]:
    """
    La periode demandee, ou la derniere close si elle ne l'est pas encore.

    Rend `(periode, ramenee)`. `ramenee` vaut vrai quand la demande a ete
    deplacee : l'ecran l'affiche, parce qu'un utilisateur qui demande juillet et
    lit juin sans qu'on le lui dise croit a un bogue.
    """
    jour = aujourd_hui or date.today()
    granularite = granularite if granularite in DUREES else MOIS

    derniere = derniere_close(granularite, aujourd_hui=jour)
    if annee is None or rang is None:
        return (derniere, False)

    demandee = _periode(granularite, annee, _rang_borne(granularite, rang))
    if demandee.fin > derniere.fin:
        return (derniere, True)
    return (demandee, False)


def derniere_close(granularite: str, *, aujourd_hui: date | None = None) -> Periode:
    """La derniere periode entierement ecoulee a la date donnee."""
    jour = aujourd_hui or date.today()
    duree = DUREES[granularite]

    annee_courante, rang_courant = _exercice_du_jour(jour, duree)
    annee, rang = annee_courante, rang_courant - 1
    if rang < 1:
        # Le rang 0 signifie « la periode en cours est la premiere de
        # l'exercice » : la derniere close est alors la derniere du precedent.
        annee -= 1
        rang = 12 // duree
    return _periode(granularite, annee, rang)


def mois_debut_exercice() -> int:
    """
    Le premier mois de l'exercice — hypothese A52, `pilotage.mois_debut_exercice`.

    Une valeur hors de 1..12 vaut janvier : un parametre mal saisi ne doit pas
    faire sortir un rapport dont les bornes n'existent pas.
    """
    mois = valeur("pilotage.mois_debut_exercice", 1)
    try:
        mois = int(mois)
    except (TypeError, ValueError):
        return 1
    return mois if 1 <= mois <= 12 else 1


def _exercice_du_jour(jour: date, duree: int) -> tuple[int, int]:
    """L'exercice auquel appartient un jour, et le rang de sa periode en cours."""
    debut = mois_debut_exercice()
    # Le nombre de mois ecoules depuis l'ouverture de l'exercice. Un exercice
    # ouvert en juillet met septembre au rang 3, pas au rang 9.
    ecoules = (jour.month - debut) % 12
    annee = jour.year if jour.month >= debut else jour.year - 1
    return (annee, ecoules // duree + 1)


def precedente(periode: Periode) -> Periode:
    """
    La periode d'avant, pour la comparaison.

    Un rapport sans comparaison est une photographie : il dit ou l'on est, pas
    dans quel sens on va. C'est la comparaison qui en fait un instrument de
    pilotage.
    """
    duree = DUREES[periode.granularite]
    if periode.granularite == ANNEE:
        return _periode(ANNEE, periode.annee - 1, 1)
    if periode.rang > 1:
        return _periode(periode.granularite, periode.annee, periode.rang - 1)
    return _periode(periode.granularite, periode.annee - 1, 12 // duree)


def _periode(granularite: str, annee: int, rang: int) -> Periode:
    duree = DUREES[granularite]
    rang = 1 if granularite == ANNEE else rang

    # Les mois se comptent depuis l'ouverture de l'exercice, puis se ramenent a
    # une annee civile. Un exercice ouvert en juillet fait donc deborder ses
    # dernieres periodes sur l'annee suivante — c'est exactement ce qui doit
    # arriver, et c'est ce qu'un calcul en dur sur `annee` aurait rate.
    premier = _mois_civil(annee, (rang - 1) * duree)
    dernier = _mois_civil(annee, (rang - 1) * duree + duree - 1)

    debut = date(premier[0], premier[1], 1)
    fin = date(dernier[0], dernier[1], monthrange(dernier[0], dernier[1])[1])
    return Periode(
        granularite=granularite,
        annee=annee,
        rang=rang,
        debut=debut,
        fin=fin,
        libelle=_libelle(granularite, annee, rang, premier, dernier),
    )


def _mois_civil(annee_exercice: int, decalage: int) -> tuple[int, int]:
    """Le (annee, mois) civil situe `decalage` mois apres l'ouverture de l'exercice."""
    absolu = (mois_debut_exercice() - 1) + decalage
    return (annee_exercice + absolu // 12, absolu % 12 + 1)


def _libelle(
    granularite: str, annee: int, rang: int, premier: tuple[int, int], dernier: tuple[int, int]
) -> str:
    if granularite == MOIS:
        # L'annee du **mois**, pas celle de l'exercice : « Janvier 2027 » ne
        # doit pas s'afficher « Janvier 2026 » parce que l'exercice a ouvert en
        # juillet.
        return libelle_mois(premier[0], premier[1])
    if granularite == ANNEE:
        return f"Exercice {annee}"
    # « 2e trimestre 2026 (avril à juin) » : le rang seul se lit vite, les mois
    # evitent d'avoir a les recompter avant de croire le chiffre.
    ordinal = "1er" if rang == 1 else f"{rang}e"
    nom = "trimestre" if granularite == TRIMESTRE else "semestre"
    return f"{ordinal} {nom} {annee} ({MOIS_LONGS[premier[1] - 1]} à {MOIS_LONGS[dernier[1] - 1]})"


def _rang_borne(granularite: str, rang: int) -> int:
    """Un rang hors bornes vaut le premier : jamais un depassement d'index."""
    maximum = 12 // DUREES[granularite]
    return rang if 1 <= rang <= maximum else 1

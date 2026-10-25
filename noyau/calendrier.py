"""
Le calendrier : les mois en francais, et les jours ouvres.

**Les mois.** Trois modules les portaient chacun de leur cote — l'administration
en abrege, la gouvernance en toutes lettres, la matrice en important ceux de
l'administration. Une quatrieme copie serait arrivee avec le pilotage, et le
jour ou l'un aurait ecrit « fevr. » sans accent, deux ecrans du meme tableau de
bord auraient affiche deux libelles pour le meme mois.

Ecrit a la main plutot que par `strftime` : **la locale du serveur n'est pas
garantie francaise**, et un « June » dans une note de synthese du CODIR se
verrait. C'est la raison que donnait deja `gouvernance/lecture.py`, et elle vaut
pour tout le depot.

**Les jours ouvres.** Le delai d'un courrier se compte en jours ouvres — c'est ce
que dit l'ecran d'enregistrement, et ce que suppose la table `jour_ferie` du
socle, dont le commentaire avertit qu'elle « n'existe dans aucun document
source : a administrer ». Une table vide donne donc un calendrier sans ferie,
seulement sans week-end. C'est exact, et visible : l'onglet des jours feries de
l'administration montre ce qui est declare.

Samedi et dimanche sont non ouvres. Le Port travaille en semaine, et aucun
document ne decrit d'exception ; le jour ou l'un en decrira une, elle se posera
en parametre, pas dans ce module.
"""

from datetime import date, timedelta

#: Forme abregee, pour les axes de graphique ou la place manque.
MOIS_COURTS = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)

#: Forme longue, pour les titres et les libelles de periode.
MOIS_LONGS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def libelle_mois(annee: int, mois: int) -> str:
    """
    « Juillet 2026 » — le libelle d'une periode mensuelle.

    Initiale en majuscule parce que le libelle ouvre une phrase ou un titre
    d'ecran, jamais le milieu d'une phrase.
    """
    return f"{MOIS_LONGS[mois - 1].capitalize()} {annee}"


def en_toutes_lettres(jour: date) -> str:
    """« 26 juin 2026 »."""
    return f"{jour.day} {MOIS_LONGS[jour.month - 1]} {jour.year}"


def mois_precedent(annee: int, mois: int) -> tuple[int, int]:
    """Le mois d'avant. Ecrit ici parce que trois modules le refaisaient."""
    return (annee - 1, 12) if mois == 1 else (annee, mois - 1)


def douze_derniers_mois(annee: int, mois: int) -> list[tuple[int, int]]:
    """
    Les douze mois qui s'achevent a celui passe, du plus ancien au plus recent.

    Du plus ancien au plus recent : c'est l'ordre d'une courbe, et l'inverser a
    l'affichage est le genre d'erreur qui ne se voit pas quand la serie est
    plate.
    """
    serie: list[tuple[int, int]] = []
    courant = (annee, mois)
    for _ in range(12):
        serie.append(courant)
        courant = mois_precedent(*courant)
    return list(reversed(serie))


# =====================================================================
#  Jours ouvres
# =====================================================================

#: Garde-fou du parcours de dates. Un delai de plusieurs milliers de jours
#: ouvres viendrait d'une saisie aberrante, et la boucle tournerait longtemps
#: avant que quiconque s'en apercoive.
PLAFOND_JOURS = 5000


def feries(depuis: date, jusqu_a: date) -> set[date]:
    """
    Les jours feries declares sur l'intervalle, bornes comprises.

    Lus une fois et rendus en ensemble : les deux fonctions ci-dessous
    parcourent les dates une par une, et une requete par jour aurait couvert
    l'ecran d'enregistrement d'allers-retours.
    """
    from noyau.parametrage.modeles import JourFerie

    return set(
        JourFerie.objects.filter(date_ferie__gte=depuis, date_ferie__lte=jusqu_a).values_list(
            "date_ferie", flat=True
        )
    )


def est_ouvre(jour: date, jours_feries: set[date]) -> bool:
    """Ni samedi, ni dimanche, ni ferie declare."""
    return jour.weekday() < 5 and jour not in jours_feries


def ajouter_jours_ouvres(depart: date, jours: int) -> date:
    """
    L'echeance a `jours` jours ouvres apres `depart`.

    Le jour de depart ne compte pas : un courrier arrive le lundi avec cinq
    jours ouvres est du le lundi suivant, pas le vendredi. C'est ainsi qu'un
    service courrier compte, et l'inverse retirerait un jour a l'agent.

    `jours <= 0` rend `depart` inchange plutot que de lever : un delai nul est
    une saisie que le service refuse en amont, et une exception ici ferait
    echouer un enregistrement pour une echeance.
    """
    if jours <= 0:
        return depart

    jours = min(jours, PLAFOND_JOURS)
    # Large exprès : on ignore combien de feries tomberont dans l'intervalle, et
    # une seconde requete pour les rattraper couterait plus que la marge.
    jours_feries = feries(depart, depart + timedelta(days=jours * 2 + 30))

    courant = depart
    restants = jours
    while restants > 0:
        courant += timedelta(days=1)
        if est_ouvre(courant, jours_feries):
            restants -= 1
    return courant


def jours_ouvres_entre(debut: date, fin: date) -> int:
    """
    Le nombre de jours ouvres ecoules de `debut` a `fin`, `debut` exclu.

    Symetrique de `ajouter_jours_ouvres` : `jours_ouvres_entre(d,
    ajouter_jours_ouvres(d, n))` vaut `n`. C'est ce qui permet de comparer un
    delai consomme a un delai alloue sans que les deux comptent differemment.

    Rend 0 quand `fin` precede `debut` : la consommation d'un delai ne se
    compte pas a rebours.
    """
    if fin <= debut:
        return 0

    jours_feries = feries(debut, fin)
    compte = 0
    courant = debut
    while courant < fin:
        courant += timedelta(days=1)
        if est_ouvre(courant, jours_feries):
            compte += 1
    return compte

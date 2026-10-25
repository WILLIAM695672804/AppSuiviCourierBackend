"""
Ecritures du pilier performance — §3.3.

Deux gestes, et aucun ne pose un score : **la matrice se recalcule** (ADR 010).
Ce qui s'ecrit ici, ce sont les **regles de mesure** — la definition d'un
indicateur, l'inscription d'une production au calendrier. C'est plus lourd de
consequence qu'une donnee : changer un seuil requalifie tout l'historique
affiche, et inscrire une production cree une obligation pour des structures qui
n'ont rien demande.

D'ou la garde `SCORE_ADM` sur ces deux routes, et l'evenement journalise a
chaque fois : « qui a change la regle, et quand » est la premiere question
posee le jour ou un classement surprend.
"""

import re
import unicodedata
from datetime import date

from django.db import transaction

from activite.modeles import CalendrierProduction
from noyau.erreurs import ErreurMetier
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from performance.matrice import structures_classees
from performance.modeles import Critere, Indicateur

#: Les libelles que le front envoie, vers les codes que la base stocke. Le
#: front affiche « Mensuelle » ; la base ecrit « mensuelle ». La traduction est
#: **ici**, une fois, plutot que dans chaque appelant.
PERIODICITES = {
    "mensuelle": "mensuelle",
    "trimestrielle": "trimestrielle",
    "semestrielle": "semestrielle",
    "annuelle": "annuelle",
}


def _sans_accent(texte: str) -> str:
    """Casse et accents retires, pour comparer une saisie a un referentiel."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texte.strip().lower())
        if not unicodedata.combining(c)
    )


def _periodicite(saisie: str) -> str:
    code = PERIODICITES.get(_sans_accent(saisie))
    if code is None:
        raise ErreurMetier(
            "Périodicité inconnue. Valeurs admises : mensuelle, trimestrielle, "
            "semestrielle, annuelle.",
            code="periodicite_inconnue",
        )
    return code


# =====================================================================
#  Dictionnaire des indicateurs
# =====================================================================


def creer_indicateur(
    acteur: Utilisateur,
    *,
    code: str,
    libelle: str,
    definition: str,
    formule: str,
    source: str,
    periodicite: str,
    responsable: str,
    unite: str = "%",
    seuil_vert: int = 85,
    seuil_orange: int = 60,
    critere: str | None = None,
) -> Indicateur:
    """
    Ajoute une entree au dictionnaire — §3.3.

    Le code est unique et sert de reference dans les documents de la DSR : le
    reutiliser pour un autre calcul rendrait faux tout ce qui le cite. On
    refuse plutot que de suffixer.

    Les seuils sont controles ici et non par le schema : « orange au-dessus de
    vert » n'est pas une saisie malformee, c'est une regle de mesure impossible,
    et le message doit dire laquelle des deux bornes deplacer.
    """
    if Indicateur.objects.filter(code=code).exists():
        raise ErreurMetier(
            f"Le code « {code} » est déjà porté par un indicateur. "
            "Choisissez-en un autre : le code sert de référence dans les "
            "documents de la DSR.",
            code="code_pris",
        )
    if seuil_orange >= seuil_vert:
        raise ErreurMetier(
            "Le seuil orange doit rester inférieur au seuil vert.",
            code="seuils_incoherents",
        )

    axe = _critere(critere)

    with transaction.atomic():
        indicateur = Indicateur.objects.create(
            code=code,
            libelle=libelle,
            definition=definition,
            formule=formule,
            source=source,
            periodicite=_periodicite(periodicite),
            responsable=responsable,
            unite=unite,
            seuil_vert=seuil_vert,
            seuil_orange=seuil_orange,
            critere=axe,
            cree_par=acteur.pk,
        )
        inscrire(
            objet_type="indicateur_dictionnaire",
            objet_id=indicateur.pk,
            type_evenement="indicateur_defini",
            libelle=f"Indicateur « {libelle} » ajouté au dictionnaire",
            acteur=acteur,
            detail=f"Formule retenue : {formule}",
            donnees={"code": code, "critere": axe.code if axe else None},
        )
    return indicateur


def _critere(reference: str | None) -> Critere | None:
    """
    Le critere alimente, designe par son code ou par son libelle.

    Les deux sont acceptes parce que l'ecran affiche le libelle : exiger le
    code aurait suppose que l'administrateur le connaisse, et une reference
    inconnue vaut mieux refusee que silencieusement mise a `null` — un
    indicateur detache de son critere ne se voit qu'au moment ou le score ne
    bouge pas.
    """
    if not reference:
        return None

    axe = Critere.objects.filter(code=reference).first()
    if axe is not None:
        return axe

    for candidat in Critere.objects.all():
        if _sans_accent(candidat.libelle) == _sans_accent(reference):
            return candidat

    raise ErreurMetier(
        f"Aucun critère de la matrice ne correspond à « {reference} ».",
        code="critere_inconnu",
    )


# =====================================================================
#  Calendrier officiel de production
# =====================================================================


def ajouter_production(
    acteur: Utilisateur,
    *,
    production: str,
    nature: str,
    periodicite: str,
    echeance: str,
    relance_automatique: bool = True,
    jours_avant_relance: int | None = None,
) -> CalendrierProduction:
    """
    Inscrit une production au calendrier officiel — §3.3.

    **Une ligne par structure classee, pas une ligne globale.** La table lie
    une production a une structure ; c'est ce qui permet de dire laquelle n'a
    pas depose. Le nombre de structures attendues saisi a l'ecran n'est donc
    pas retenu : ce sont les structures **reelles** qui font le compte, et un
    chiffre saisi a la main aurait diverge du referentiel des la creation de la
    direction suivante.

    Les structures retenues sont celles du classement (`structures_classees`) :
    demander une production a une structure qu'on ne classe pas produirait une
    obligation dont le non-respect ne pese sur rien.

    L'echeance est saisie en toutes lettres (« le 5 du mois suivant ») parce
    que c'est ainsi qu'elle est communiquee aux structures. Le jour en est
    extrait pour engendrer les obligations ; sans jour lisible, on refuse
    plutot que de retenir un 1er par defaut, qui avancerait toutes les
    echeances de la production.
    """
    structures = structures_classees()
    if not structures:
        raise ErreurMetier(
            "Aucune structure ne figure aux tableaux statistiques : il n'y a "
            "personne à qui demander cette production.",
            code="referentiel_vide",
        )

    code_periodicite = _periodicite(periodicite)
    jour = _jour_echeance(echeance)
    code_nature = _nature(nature)

    with transaction.atomic():
        lignes = CalendrierProduction.objects.bulk_create(
            [
                CalendrierProduction(
                    structure=structure,
                    nature=code_nature,
                    intitule=production,
                    periodicite=code_periodicite,
                    jour_echeance=jour,
                    relance_automatique=relance_automatique,
                    jours_avant_relance=jours_avant_relance,
                    actif=True,
                    valide_du=date.today(),
                    cree_par=acteur.pk,
                )
                for structure in structures
            ]
        )
        premiere = lignes[0]
        inscrire(
            objet_type="calendrier_production",
            objet_id=premiere.pk,
            type_evenement="production_inscrite",
            libelle=f"« {production} » inscrite au calendrier officiel",
            acteur=acteur,
            detail=f"{len(lignes)} structures attendues — échéance : {echeance}",
            donnees={
                "periodicite": code_periodicite,
                "jourEcheance": jour,
                "structures": [s.code for s in structures],
            },
        )
    return premiere


def _jour_echeance(echeance: str) -> int:
    """
    Le quantieme lu dans la phrase d'echeance.

    Un seul nombre est attendu. Deux nombres (« le 5 ou le 10 ») ne decrivent
    pas une echeance mais une tolerance, et la tolerance ne se calcule pas :
    on refuse.
    """
    nombres = re.findall(r"\d{1,2}", echeance)
    if len(nombres) != 1:
        raise ErreurMetier(
            "L'échéance doit porter un jour et un seul, par exemple « le 5 du mois suivant ».",
            code="echeance_illisible",
        )

    jour = int(nombres[0])
    if not 1 <= jour <= 31:
        raise ErreurMetier(
            "Le jour d'échéance doit être compris entre 1 et 31.",
            code="echeance_illisible",
        )
    return jour


def _nature(saisie: str) -> str:
    """
    La nature, ramenee au referentiel de `CalendrierProduction`.

    Le referentiel est ferme : les obligations engendrees s'y appuient, et une
    nature libre aurait produit autant de valeurs que de saisies — « PV »,
    « P.V. », « proces verbal » — qu'aucun regroupement n'aurait recollees.
    """
    attendues = dict(CalendrierProduction.NATURES)
    for code, libelle in attendues.items():
        if _sans_accent(saisie) in (_sans_accent(code), _sans_accent(libelle)):
            return code

    raise ErreurMetier(
        "Nature inconnue. Valeurs admises : " + ", ".join(attendues.values()) + ".",
        code="nature_inconnue",
    )

"""
Ecritures sur les regles parametrables — zone H.

**C'est la sortie des questions ouvertes.** La table `parametre` porte les
regles que la conception a inventees faute de reponse du metier ; chacune est
marquee `hypothese`, avec le nom de qui doit trancher. Jusqu'ici, la trancher
demandait un `UPDATE` en SQL : la reponse du client passait par le
developpement, et rien ne garantissait qu'elle laisse une trace.

Deux regles gouvernent ce module.

 1. **Une hypothese ne devient pas un acte sans source.** C'est la consigne
    permanente du projet — « ne pas changer une regle marquee `hypothese` sans
    arbitrage ecrit ». Le service exige la reference documentaire, et la
    conserve : « Note DG du 3 septembre 2026 » est ce qui distingue une decision
    d'un remplacement d'invention par une autre.
 2. **Un acte ne redevient pas une hypothese.** Ce serait effacer un arbitrage
    rendu. Une decision qui change se remplace par une autre decision, avec sa
    propre source — pas par un retour a l'incertitude.

Toute ecriture vide le cache de `service.valeur()`. L'oublier ferait appliquer
l'ancien seuil jusqu'au redemarrage, et deux serveurs derriere un repartiteur
appliqueraient deux regles differentes sans que rien ne le signale.
"""

from decimal import Decimal, InvalidOperation

from django.db import models, transaction

from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.parametres import service as cache
from noyau.parametres.modeles import Parametre

STATUT_ACTE = "acte"
STATUT_HYPOTHESE = "hypothese"


def regles() -> list[dict]:
    """
    Toutes les regles parametrables, hypotheses en tete.

    L'ordre n'est pas cosmetique : une hypothese est une question sans reponse,
    et un ecran qui la noierait au milieu de trente regles actees ferait oublier
    qu'elle attend un arbitrage. C'est le meme principe que « ce qu'on attend de
    vous en tete » sur le portail.
    """
    # Pas `order_by("statut")` : `acte` precede `hypothese` dans l'alphabet, et
    # le tri naturel mettrait donc les questions en attente en queue de liste —
    # exactement l'inverse de ce qu'on veut.
    lignes = Parametre.objects.all().order_by(
        models.Case(
            models.When(statut=STATUT_HYPOTHESE, then=models.Value(0)),
            default=models.Value(1),
            output_field=models.IntegerField(),
        ),
        "domaine",
        "cle",
    )
    return [
        {
            "cle": ligne.cle,
            "libelle": ligne.libelle,
            "valeur": ligne.valeur,
            "typeValeur": ligne.type_valeur,
            "domaine": ligne.domaine,
            "statut": ligne.statut,
            "estHypothese": ligne.statut == STATUT_HYPOTHESE,
            "source": ligne.source,
            "aTrancherPar": ligne.a_trancher_par,
            "modifieLe": ligne.modifie_le,
        }
        for ligne in lignes
    ]


def modifier_regle(
    acteur: Utilisateur,
    cle: str,
    *,
    valeur: str,
    source: str | None = None,
) -> Parametre:
    """
    Change la valeur d'une regle, sans toucher a son statut.

    Une **hypothese** se corrige librement : c'est une invention de la
    conception, et l'ajuster ne fait que remplacer une invention par une autre —
    ce qui est exactement ce que le statut annonce.

    Un **acte**, lui, exige une source a chaque changement. Modifier un seuil
    arbitre sans dire d'ou vient le nouveau chiffre le ramenerait au rang
    d'invention, en gardant l'etiquette qui dit le contraire.
    """
    parametre = _regle(cle)
    valeur = _valeur_valide(parametre, valeur)

    if valeur == parametre.valeur and not source:
        return parametre

    if parametre.statut == STATUT_ACTE and not (source or "").strip():
        raise ErreurMetier(
            f"« {parametre.libelle} » a ete arbitre. Changer sa valeur suppose de "
            "citer la decision qui le change.",
            code="source_exigee",
        )

    ancienne = parametre.valeur

    with transaction.atomic():
        parametre.valeur = valeur
        if source:
            parametre.source = source.strip()
        parametre.modifie_par = acteur.pk
        parametre.save()

        inscrire(
            acteur=acteur,
            objet_type="parametre",
            objet_id=parametre.pk,
            type_evenement="regle_modifiee",
            libelle=f"Regle « {parametre.libelle} » : {ancienne} → {valeur}",
            detail=source,
            donnees={
                "cle": parametre.cle,
                "avant": ancienne,
                "apres": valeur,
                "statut": parametre.statut,
            },
        )

    # Hors de la transaction : vider le cache avant le commit ouvrirait une
    # fenetre ou une autre requete le repeuple avec l'ancienne valeur, encore
    # seule visible en base. La regle changee serait alors ignoree jusqu'au
    # redemarrage, sans que rien ne le signale.
    cache.vider_cache()
    return parametre


def trancher_regle(
    acteur: Utilisateur,
    cle: str,
    *,
    source: str,
    valeur: str | None = None,
) -> Parametre:
    """
    Fait passer une hypothese au rang d'acte — la sortie des questions ouvertes.

    **La source est obligatoire et n'est pas un commentaire** : c'est la
    reference de l'arbitrage — « Note DG du 3 septembre 2026 », « Reunion DSR du
    12 aout ». Sans elle, on remplace une invention par une autre en lui donnant
    l'etiquette d'une decision, ce qui est pire que l'invention assumee.

    `valeur` est facultatif : le metier confirme souvent l'hypothese telle
    quelle, et l'obliger a retaper le chiffre est le meilleur moyen d'en obtenir
    un faux.

    Trancher une regle deja actee est refuse. Ce n'est pas une precaution
    formelle : la route servirait alors a reecrire une decision passee en
    silence, et l'ecran ne montrerait plus qu'un arbitrage a eu lieu deux fois.
    """
    source = (source or "").strip()
    if not source:
        raise ErreurMetier(
            "La reference de l'arbitrage est obligatoire : sans elle, la regle "
            "reste une hypothese, quel que soit le statut affiche.",
            code="source_exigee",
        )

    parametre = _regle(cle)
    if parametre.statut == STATUT_ACTE:
        raise ErreurMetier(
            f"« {parametre.libelle} » a deja ete arbitre ({parametre.source}). "
            "Changez sa valeur en citant la nouvelle decision.",
            code="regle_deja_actee",
        )

    ancienne = parametre.valeur
    if valeur is not None:
        valeur = _valeur_valide(parametre, valeur)

    with transaction.atomic():
        if valeur is not None:
            parametre.valeur = valeur
        parametre.statut = STATUT_ACTE
        parametre.source = source
        # Plus personne n'a a trancher : la colonne dirait le contraire de ce
        # que le statut annonce, et l'ecran continuerait a reclamer un arbitrage
        # rendu.
        parametre.a_trancher_par = None
        parametre.modifie_par = acteur.pk
        parametre.save()

        inscrire(
            acteur=acteur,
            objet_type="parametre",
            objet_id=parametre.pk,
            type_evenement="regle_tranchee",
            libelle=f"Regle « {parametre.libelle} » arbitree : {parametre.valeur}",
            detail=source,
            donnees={
                "cle": parametre.cle,
                "avant": ancienne,
                "apres": parametre.valeur,
                "source": source,
            },
        )

    cache.vider_cache()
    return parametre


# =====================================================================
#  Refus
# =====================================================================


def _regle(cle: str) -> Parametre:
    parametre = Parametre.objects.filter(cle=cle).first()
    if parametre is None:
        raise HorsPerimetre("Cette regle n'existe pas.")
    return parametre


def _valeur_valide(parametre: Parametre, valeur: str) -> str:
    """
    Refuse une valeur que `service._convertir` ne saurait pas relire.

    Sans ce controle, une faute de frappe passe a l'ecriture et **casse a la
    lecture** : `int('1O')` leve dans le calcul d'un retard, a des kilometres de
    la saisie qui l'a causee, et l'ecran d'origine ne montre rien d'anormal.
    """
    valeur = (valeur or "").strip()
    if not valeur:
        raise ErreurMetier("Une regle ne peut pas etre vide.", code="valeur_vide")

    if parametre.type_valeur == "entier":
        try:
            int(valeur)
        except ValueError:
            raise ErreurMetier(
                f"« {parametre.libelle} » attend un nombre entier — « {valeur} » n'en est pas un.",
                code="valeur_non_entiere",
            ) from None

    elif parametre.type_valeur == "decimal":
        try:
            Decimal(valeur)
        except (InvalidOperation, ValueError):
            raise ErreurMetier(
                f"« {parametre.libelle} » attend un nombre — « {valeur} » n'en est pas un.",
                code="valeur_non_decimale",
            ) from None

    elif parametre.type_valeur == "booleen":
        if valeur.lower() not in cache.VRAIS + cache.FAUX:
            raise ErreurMetier(
                f"« {parametre.libelle} » attend oui ou non, pas « {valeur} ».",
                code="valeur_non_booleenne",
            )
        # Normalisee : `service._convertir` accepte huit ecritures, l'ecran n'en
        # affichera qu'une.
        valeur = "true" if valeur.lower() in cache.VRAIS else "false"

    return valeur

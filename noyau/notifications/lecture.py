"""
Ce qui se lit des notifications.

**Aucun `restreindre()` ici, et ce n'est pas un oubli.** Une notification est
adressee a une personne : le filtre est `destinataire = utilisateur`, exactement
comme le portail filtre par `deposant` (ADR 013). Passer en plus par le
perimetre serait au mieux inutile, au pire faux — un agent muté garde ses
notifications, qui parlent d'un dossier dont il est sorti.

C'est aussi pourquoi les routes sont en `session_seule` : il n'existe pas de
permission « lire ses propres notifications », et en inventer une reviendrait a
pouvoir la retirer a quelqu'un — c'est-a-dire a le laisser dans le silence sans
qu'aucun ecran ne le dise.

L'etat de la file, lui, n'est pas une lecture personnelle : c'est de
l'exploitation, et il exige `ADM_PAR`.
"""

from django.db import models
from django.db.models import Count, Q

from noyau.identite.modeles import Utilisateur
from noyau.notifications.modeles import (
    ETAT_ECHOUE,
    ETAT_EN_ATTENTE,
    ETAT_ENVOYE,
    ETAT_SANS_TRANSPORT,
    EnvoiNotification,
    Notification,
)

#: Ce qu'un chargement de cloche rapporte. Au-dela, l'ecran propose « tout
#: marquer lu » plutot qu'une pagination : une liste de deux cents
#: notifications ne se lit pas, elle se solde.
PLAFOND = 50


def mes_notifications(acteur: Utilisateur, *, non_lues_seulement: bool = False) -> dict:
    """
    Les notifications d'un agent, non lues en tete.

    Le compteur est calcule sur **toute** la table et non sur la page rendue :
    une pastille qui afficherait « 50 » parce que la requete s'arrete la ferait
    croire que la file se vide alors qu'elle stagne.
    """
    lignes = Notification.objects.filter(destinataire=acteur)
    if non_lues_seulement:
        lignes = lignes.filter(lu_le__isnull=True)

    # Non lues d'abord, puis par date : une alerte d'hier non lue compte plus
    # qu'une information de ce matin deja vue.
    #
    # `nulls_first=True` n'est pas une precaution de style. PostgreSQL classe
    # les NULL **en dernier** dans un tri ascendant, et `order_by("lu_le")`
    # aurait donc renvoye les non lues en queue de liste — exactement l'inverse
    # de ce qu'on veut, et sans que rien ne le signale.
    lignes = lignes.order_by(models.F("lu_le").asc(nulls_first=True), "-cree_le", "-id")[:PLAFOND]

    return {
        "nonLues": Notification.objects.filter(destinataire=acteur, lu_le__isnull=True).count(),
        "notifications": [_ligne(n) for n in lignes],
    }


def etat_de_la_file() -> dict:
    """
    Ce que la file contient, par canal et par etat — exploitation.

    `sansTransport` est le chiffre a lire en premier : ce n'est pas une panne,
    c'est ce que l'institution n'a pas branche. Le confondre avec les echecs
    ferait chercher un incident la ou il n'y a qu'une decision en attente.
    """
    par_canal = (
        EnvoiNotification.objects.values("canal")
        .annotate(
            enAttente=Count("id", filter=Q(etat=ETAT_EN_ATTENTE)),
            envoyes=Count("id", filter=Q(etat=ETAT_ENVOYE)),
            echoues=Count("id", filter=Q(etat=ETAT_ECHOUE)),
            sansTransport=Count("id", filter=Q(etat=ETAT_SANS_TRANSPORT)),
        )
        .order_by("canal")
    )

    derniers = (
        EnvoiNotification.objects.filter(etat__in=[ETAT_ECHOUE, ETAT_SANS_TRANSPORT])
        .select_related("notification")
        .order_by("-cree_le", "-id")[:20]
    )

    return {
        "canaux": [dict(ligne) for ligne in par_canal],
        "enAttente": EnvoiNotification.objects.filter(etat=ETAT_EN_ATTENTE).count(),
        "bloques": [
            {
                "id": envoi.pk,
                "canal": envoi.canal,
                "etat": envoi.etat,
                "libelle": envoi.notification.libelle,
                "tentatives": envoi.tentatives,
                # La raison telle que le transport l'a rendue. Une erreur
                # reecrite ne se cherche plus dans une documentation.
                "raison": envoi.erreur or "",
                "creeLe": envoi.cree_le.strftime("%d/%m/%Y %H:%M") if envoi.cree_le else "",
            }
            for envoi in derniers
        ],
    }


def _ligne(notification: Notification) -> dict:
    return {
        "id": notification.pk,
        "type": notification.type_notification,
        "libelle": notification.libelle,
        "detail": notification.detail,
        "importance": notification.importance,
        "lien": notification.lien,
        "lue": notification.lu_le is not None,
        "creeLe": notification.cree_le.strftime("%d/%m/%Y %H:%M") if notification.cree_le else "",
    }

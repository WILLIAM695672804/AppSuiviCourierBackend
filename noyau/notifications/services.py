"""
Mettre en file, depiler, marquer lu — RF-SUI-03, RF-ADM-04.

## Le point d'entree unique

`notifier()` est le seul endroit du depot qui cree une notification. Un pilier
qui insererait la ligne lui-meme sauterait les preferences de l'usager, la
duplication par canal et le compte des envois — trois oublis silencieux.

## Pourquoi aucun evenement n'est inscrit au journal

La regle du depot est qu'une ecriture metier inscrit un evenement. Une
notification n'en est pas une : c'est un **effet** d'un acte deja journalise.
Le dossier retourne a l'etape precedente a produit son evenement ; ecrire un
second evenement pour dire qu'on a prevenu quelqu'un ferait grossir l'histoire
du dossier (ADR 012) de lignes qui ne racontent rien de plus, et noierait les
actes sous leurs echos.

Ce qui se trace se trace la ou ça compte : la table `envoi_notification` **est**
le journal des sorties, avec son etat, ses tentatives et son erreur.

La lecture d'une notification n'est pas davantage un acte metier. Elle n'entre
pas non plus dans le journal des acces : `tracer_acces` sert a savoir qui a
regarde un dossier, pas qui a fait disparaitre une pastille rouge.

## La file ne se depile pas toute seule

`depiler()` est appelee par la commande `envoyer_notifications`, elle-meme
appelee par un ordonnanceur — cron ou Celery battu. Pas de `on_commit` qui
enverrait dans le processus de la requete : un serveur SMTP lent rendrait lente
la route qui a declenche la notification, et une panne de messagerie ferait
echouer une cotation.
"""

from django.db import transaction
from django.utils import timezone

from noyau.erreurs import ErreurMetier, HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.notifications import transports
from noyau.notifications.modeles import (
    CANAL_COURRIEL,
    CANAL_SMS,
    ETAT_ECHOUE,
    ETAT_EN_ATTENTE,
    ETAT_ENVOYE,
    ETAT_SANS_TRANSPORT,
    EnvoiNotification,
    Notification,
)
from noyau.parametres.service import valeur as parametre

#: Combien de fois le depileur repasse sur un envoi echoue avant de le laisser.
#: Hypothese (A51) : trois est l'usage, aucun document ne le fixe.
TENTATIVES_DEFAUT = 3

#: Combien d'envois un passage du depileur traite. Une borne, et non « tout ce
#: qui traine » : une file de dix mille lignes accumulee pendant une panne ne
#: doit pas partir d'un coup a la reprise.
LOT_DEFAUT = 200


def notifier(
    destinataire: Utilisateur,
    *,
    type_notification: str,
    libelle: str,
    detail: str = "",
    importance: str | None = None,
    objet_type: str | None = None,
    objet_id: int | None = None,
    lien: str | None = None,
    acteur: Utilisateur | None = None,
    accuse_de_reception: bool = False,
) -> Notification:
    """
    Previent quelqu'un, et met en file ce qui doit sortir.

    La notification interne est **toujours** creee, quelles que soient les
    preferences : « Portail seulement » n'est pas l'absence de notification,
    c'est l'obligation de venir lire. Couper le canal interne reviendrait a ne
    pas prevenir du tout.

    On ne se notifie pas soi-meme. L'agent qui vient de coter un courrier sait
    qu'il l'a cote ; lui envoyer un message le lui apprenant est le meilleur
    moyen de lui faire ignorer les suivants.

    `accuse_de_reception` est la seule exception, et elle est nommee pour qu'on
    ne puisse pas y tomber par distraction : l'accuse de reception n'apprend pas
    a l'usager ce qu'il vient de faire, il lui **confirme** que l'institution
    l'a recu — c'est-a-dire exactement ce qu'il ne peut pas savoir tout seul.
    C'est l'evenement `depot` du referentiel du portail.
    """
    if acteur is not None and acteur.pk == destinataire.pk and not accuse_de_reception:
        raise ErreurMetier(
            "On ne notifie pas l'auteur de son propre acte.",
            code="notification_a_soi_meme",
        )

    with transaction.atomic():
        notification = Notification.objects.create(
            destinataire=destinataire,
            type_notification=type_notification,
            libelle=libelle,
            detail=detail,
            importance=importance or "information",
            objet_type=objet_type,
            objet_id=objet_id,
            lien=lien,
            cree_par=acteur.pk if acteur else None,
        )

        for canal, adresse in _canaux_sortants(destinataire, type_notification):
            EnvoiNotification.objects.create(
                notification=notification,
                canal=canal,
                adresse=adresse,
            )

    return notification


def marquer_lue(acteur: Utilisateur, notification_id: int) -> Notification:
    """
    Ouvre une notification.

    404 et non 403 sur la notification d'autrui, comme partout (D5) : repondre
    « interdit » confirmerait qu'elle existe, et le libelle d'une notification
    en dit deja long sur ce qui se passe dans une autre direction.

    Relire une notification deja lue ne change pas sa date. La premiere lecture
    est la seule qui reponde a la question « l'a-t-elle vue a temps ? ».
    """
    notification = Notification.objects.filter(pk=notification_id, destinataire=acteur).first()
    if notification is None:
        raise HorsPerimetre()

    if notification.lu_le is None:
        notification.lu_le = timezone.now()
        notification.save(update_fields=["lu_le"])

    return notification


def tout_marquer_lu(acteur: Utilisateur) -> int:
    """
    Vide la pastille d'un coup, et rend le nombre de lignes touchees.

    Un seul `UPDATE` : marquer cent notifications une par une ferait cent
    requetes pour un geste qui n'en merite pas.
    """
    return Notification.objects.filter(destinataire=acteur, lu_le__isnull=True).update(
        lu_le=timezone.now()
    )


def depiler(limite: int | None = None) -> dict:
    """
    Passe les envois en attente aux transports.

    Rend un compte rendu — c'est ce que la commande affiche et ce que
    l'ordonnanceur consigne. Un depileur muet ne se surveille pas.

    Les envois sont traites un par un, chacun dans sa transaction : un transport
    qui casse au dixieme message ne doit pas defaire les neuf premiers, deja
    partis. Rien ne peut les rappeler.
    """
    lot = limite or int(parametre("notifications.lot_depilement", LOT_DEFAUT))
    tentatives_max = int(parametre("notifications.tentatives_max", TENTATIVES_DEFAUT))

    attente = list(
        EnvoiNotification.objects.filter(
            etat__in=[ETAT_EN_ATTENTE, ETAT_ECHOUE],
            tentatives__lt=tentatives_max,
        )
        .select_related("notification")
        .order_by("cree_le", "id")[:lot]
    )

    compte = {"traites": 0, "envoyes": 0, "echoues": 0, "sans_transport": 0}

    for envoi in attente:
        transport = transports.TRANSPORTS.get(envoi.canal)
        resultat = (
            transport(envoi)
            if transport
            else transports.Resultat(
                reussi=False,
                branche=False,
                raison=f"Aucun transport n'est déclaré pour le canal « {envoi.canal} ».",
            )
        )

        with transaction.atomic():
            envoi.tentatives += 1
            if resultat.reussi:
                envoi.etat = ETAT_ENVOYE
                envoi.envoye_le = timezone.now()
                envoi.erreur = None
                compte["envoyes"] += 1
            elif not resultat.branche:
                # Pas `echoue` : rien n'a echoue, rien n'a ete tente. Reessayer
                # ne changerait rien tant qu'une decision d'infrastructure n'a
                # pas ete prise.
                envoi.etat = ETAT_SANS_TRANSPORT
                envoi.erreur = resultat.raison
                compte["sans_transport"] += 1
            else:
                envoi.etat = ETAT_ECHOUE
                envoi.erreur = resultat.raison
                compte["echoues"] += 1

            envoi.save(update_fields=["etat", "tentatives", "envoye_le", "erreur"])

        compte["traites"] += 1

    return compte


def _canaux_sortants(destinataire: Utilisateur, type_notification: str) -> list[tuple[str, str]]:
    """
    Les canaux **hors application** a servir, et l'adresse pour chacun.

    Le canal interne n'y figure jamais : il n'a pas de sortie.

    Les preferences ne concernent que les comptes du portail — un agent n'en a
    pas, et le lui demander serait lui offrir de couper les alertes de service.
    En l'absence de preference, aucun canal sortant : mieux vaut ne rien envoyer
    que d'ecrire a une adresse devinee.
    """
    from portail.modeles import CANAL_COURRIEL as PORTAIL_COURRIEL
    from portail.modeles import CANAL_SMS as PORTAIL_SMS
    from portail.modeles import PreferenceNotification

    preference = PreferenceNotification.objects.filter(utilisateur=destinataire).first()
    if preference is None:
        return []

    if not _evenement_accepte(preference, type_notification):
        return []

    if preference.canal == PORTAIL_COURRIEL and preference.courriel:
        return [(CANAL_COURRIEL, preference.courriel)]
    if preference.canal == PORTAIL_SMS and preference.telephone:
        return [(CANAL_SMS, preference.telephone)]

    # « Portail seulement », ou un canal choisi sans coordonnee. Le canal
    # interne suffit, et il a deja ete cree.
    return []


def _evenement_accepte(preference, type_notification: str) -> bool:
    """
    Le destinataire a-t-il coupe ce type d'evenement ?

    Un evenement **obligatoire** passe outre le refus : la demande de complement
    ouvre un delai de forclusion, la decision rendue ouvre un delai de recours.
    Laisser couper ces deux-la reviendrait a laisser l'usager organiser sa
    propre forclusion — c'est la regle portee par `EvenementNotifiable`, et elle
    se verifie ici aussi, pas seulement a l'ecriture des preferences.

    Un type inconnu du referentiel passe : c'est une notification de service,
    pas un evenement que l'usager a jamais eu l'occasion de refuser.
    """
    from portail.modeles import EvenementNotifiable, PreferenceEvenement

    evenement = EvenementNotifiable.objects.filter(cle=type_notification, actif=True).first()
    if evenement is None:
        return True
    if evenement.obligatoire:
        return True

    choix = PreferenceEvenement.objects.filter(preference=preference, evenement=evenement).first()
    return choix.actif if choix else True

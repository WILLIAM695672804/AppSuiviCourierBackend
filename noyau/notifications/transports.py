"""
Par ou une notification sort de l'application.

## Le probleme que ce module resout

L'etat des integrations est sans ambiguite (`supervision`, semis initial) : la
messagerie institutionnelle est « Non connecte », la passerelle SMS aussi.
Ecrire un pilier de notification qui suppose le contraire aurait produit le pire
des ecrans — celui qui affiche « envoye » sans que rien ne parte.

Chaque canal declare donc un transport, et un transport declare **s'il est
branche**. Quand il ne l'est pas, l'envoi ne part pas en echec : il passe en
`sans_transport`, avec la raison. La difference n'est pas cosmetique — un echec
se rejoue, une absence de transport se resout par une decision d'infrastructure,
et confondre les deux fait relancer indefiniment des messages qui n'ont nulle
part ou aller.

## Le courriel est ecrit, et desactive

Le code d'envoi par courriel existe et fonctionne : il passe par
`django.core.mail`, dont le backend est un reglage. Il est neanmoins **coupe
par defaut**, par la regle `notifications.courriel_actif` (hypothese, A51).

Ce n'est pas de la prudence de facade. Tant que le serveur SMTP, l'adresse
d'expedition et la politique de l'institution ne sont pas arretes, envoyer
depuis un environnement de recette a de vraies adresses d'agents est un incident,
pas un test. La regle vit en base : la trancher est un geste d'administration,
pas une livraison.

## Le SMS n'est pas ecrit

Aucune passerelle n'est nommee nulle part, et il n'existe pas d'API SMS
generique. Ecrire un transport contre une passerelle imaginaire aurait produit
du code que personne ne pourrait ni essayer ni corriger. Le canal existe,
son transport declare qu'il n'est pas branche, et l'usager qui l'a choisi le
voit dans l'etat de la file.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail

from noyau.notifications.modeles import CANAL_COURRIEL, CANAL_SMS, EnvoiNotification
from noyau.parametres.service import valeur as parametre

#: L'adresse d'expedition, tant qu'aucune n'est arretee (A51). `DEFAULT_FROM_EMAIL`
#: est le reglage de Django et vaut ce que l'environnement y met.
EXPEDITEUR_DEFAUT = "notifications@pad.local"


@dataclass(frozen=True)
class Resultat:
    """
    Ce qu'un transport rend.

    `branche=False` n'est pas un echec, et le service en tire un etat different.
    La raison est obligatoire dans les deux cas : un envoi qui n'est pas parti
    sans qu'on sache pourquoi ne se repare pas.
    """

    reussi: bool
    branche: bool = True
    raison: str = ""


def _courriel(envoi: EnvoiNotification) -> Resultat:
    if not _actif("notifications.courriel_actif"):
        return Resultat(
            reussi=False,
            branche=False,
            raison=(
                "L'envoi par courriel est coupé (règle « notifications.courriel_actif », "
                "hypothèse A51). Aucun serveur de messagerie n'est arrêté."
            ),
        )

    if not envoi.adresse:
        return Resultat(
            reussi=False,
            raison="Aucune adresse de courriel n'est connue pour ce destinataire.",
        )

    try:
        send_mail(
            subject=envoi.notification.libelle,
            # Le detail seul : le libelle est deja l'objet du message, et le
            # repeter dans le corps donne un courriel qui dit deux fois la
            # meme chose.
            message=envoi.notification.detail or envoi.notification.libelle,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", EXPEDITEUR_DEFAUT),
            recipient_list=[envoi.adresse],
            fail_silently=False,
        )
    except Exception as erreur:
        # `Exception` et non une liste de types : `send_mail` remonte ce que le
        # backend configure remonte — `SMTPException`, `OSError`, ou autre chose
        # selon le backend. Filtrer sur une liste ferait remonter l'exception
        # non prevue jusqu'a la commande, qui s'arreterait au premier envoi
        # cassant et laisserait toute la file derriere lui.
        return Resultat(reussi=False, raison=str(erreur)[:500])

    return Resultat(reussi=True)


def _sms(envoi: EnvoiNotification) -> Resultat:
    return Resultat(
        reussi=False,
        branche=False,
        raison=(
            "Aucune passerelle SMS n'est branchée (A48). Le canal est proposé, rien n'est envoyé."
        ),
    )


def _actif(cle: str) -> bool:
    """
    Lit une regle booleenne de `parametre`.

    Le defaut est **faux** : une regle absente de la table doit couper l'envoi,
    pas l'ouvrir. Un pilier qui s'active tout seul parce qu'une migration n'est
    pas passee est exactement le genre de surprise qu'on ne veut pas sur un
    canal sortant.
    """
    return bool(parametre(cle, False))


#: Un transport par canal sortant. Le canal interne n'y figure pas : il n'a pas
#: de sortie, il *est* la notification.
TRANSPORTS: dict[str, Callable[[EnvoiNotification], Resultat]] = {
    CANAL_COURRIEL: _courriel,
    CANAL_SMS: _sms,
}

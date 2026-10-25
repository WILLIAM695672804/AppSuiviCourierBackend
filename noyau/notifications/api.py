"""
Routes des notifications — `/api/notifications/*`.

## Pourquoi `session_seule` sur les trois premieres

Il n'existe pas de permission « lire ses propres notifications », et en creer
une serait pouvoir la retirer a quelqu'un — c'est-a-dire le laisser dans le
silence sans qu'aucun ecran ne le dise. Le filtre est le destinataire, comme le
portail filtre par deposant (ADR 013). Voir `noyau/notifications/lecture.py`.

`GET /file`, en revanche, n'est pas une lecture personnelle : c'est de
l'exploitation, et elle exige `ADM_PAR`.

Le premier parametre s'appelle `request` et n'est pas annote : django-ninja
l'impose. L'explication complete est dans `noyau/identite/api.py`.
"""

from ninja import Router

from noyau.habilitation.dependances import PERM, exige, session_seule
from noyau.notifications import lecture, services
from noyau.notifications.schemas import (
    CompteLecture,
    EtatFile,
    MesNotifications,
    NotificationSortie,
)

routeur = Router()


@routeur.get("", response=MesNotifications, auth=session_seule)
def mes_notifications(request, nonLues: bool = False):
    """
    Ce dont l'agent connecte a ete prevenu.

    `nonLues` sert la cloche ; sans le drapeau, l'ecran complet rend aussi ce
    qui est deja lu — une notification disparue apres lecture est une
    information qu'on ne peut plus retrouver.
    """
    return lecture.mes_notifications(request.auth, non_lues_seulement=nonLues)


@routeur.post("/{notification_id}/lecture", response=NotificationSortie, auth=session_seule)
def marquer_lue(request, notification_id: int):
    """
    Ouvre une notification.

    Relire n'ecrase pas la premiere date : c'est elle qui repond a « l'a-t-elle
    vue a temps ? ».
    """
    notification = services.marquer_lue(request.auth, notification_id)
    return lecture._ligne(notification)


@routeur.post("/lecture", response=CompteLecture, auth=session_seule)
def tout_marquer_lu(request):
    """Solde la pastille. Rend le nombre de lignes touchees, pas un 204 muet."""
    return {"marquees": services.tout_marquer_lu(request.auth)}


@routeur.get("/file", response=EtatFile, auth=exige(PERM.ADM_PAR))
def etat_de_la_file(request):
    """
    L'etat d'exploitation de la file — ce qui part, ce qui echoue, ce qui n'a
    nulle part ou aller.

    Aucun `restreindre()` : la file n'appartient a aucun perimetre, et c'est
    justement ce que l'administration doit voir en entier.
    """
    return lecture.etat_de_la_file()

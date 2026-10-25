"""
L'acteur de la transaction, vu du moteur.

Le declencheur `historiser_champs()` du socle inscrit dans `champ_historique`
qui a change quoi. Il lit l'acteur dans la variable de session
`app.utilisateur_id`, **que l'application doit poser au debut de chaque
transaction** — et il refuse l'ecriture quand elle manque :

    Modification de <table> sans acteur identifie.

Ce refus est voulu : une modification enregistree sans acteur retire toute
valeur probante a l'audit, et l'oubli passerait inapercu jusqu'au jour ou l'on
aurait besoin de la trace. `RNF-TRACE-01`.

Le noyau n'en avait pas besoin : il ne modifie aucune des sept tables
historisees. Le pilier activites en modifie quatre — `activite`, `paa`,
`tache`, `instruction_activite` — d'ou ce module.

**Une variable posee localement n'a d'effet que dans une transaction.** Hors
transaction, `set_config(…, true)` retombe des la requete suivante et le
declencheur refuse quand meme. Les deux gestionnaires ci-dessous ouvrent donc
leur propre bloc atomique.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction

from noyau.identite.modeles import Utilisateur


@contextmanager
def acteur(utilisateur: Utilisateur) -> Iterator[None]:
    """
    Ouvre une transaction ou les ecritures sont imputees a `utilisateur`.

    A poser autour de toute ecriture metier sur une table historisee. Les
    services du pilier activites l'utilisent systematiquement.
    """
    with transaction.atomic():
        with connection.cursor() as curseur:
            # `SET LOCAL` n'accepte pas de parametre lie. `set_config(..., true)`
            # fait la meme chose — porte local a la transaction — en acceptant
            # un parametre : aucune interpolation, et un scanner de moins a
            # rassurer. Meme forme que `traitement_automatique` ci-dessous.
            curseur.execute(
                "SELECT set_config('app.utilisateur_id', %s, true)", [str(utilisateur.pk)]
            )
        yield


@contextmanager
def traitement_automatique(nom: str) -> Iterator[None]:
    """
    Ouvre une transaction pour un traitement legitimement non nominatif :
    recalcul nocturne des agregats, engendrement des obligations.

    Le nom est inscrit tel quel dans `app.contexte`. Ecrire « batch » partout
    reviendrait a ne rien tracer du tout : nommer le traitement est le seul
    moyen de savoir, six mois plus tard, lequel a touche la ligne.
    """
    with transaction.atomic():
        with connection.cursor() as curseur:
            curseur.execute("SELECT set_config('app.contexte', %s, true)", [nom])
        yield

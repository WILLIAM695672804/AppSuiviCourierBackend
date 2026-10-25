"""
Ecriture au journal.

**Regle du projet : toute ecriture metier inscrit un evenement. Sans
exception.** Le §18 du cahier des charges l'exige pour les activites, le §10
et le §23 pour les courriers, RNF-TRACE-01 pour tout le reste.

La regle n'est tenable que si elle passe par un point unique. D'ou ce module :
un service metier appelle `inscrire()`, jamais `Evenement.objects.create()`.

Le filet correspondant — un test qui refuse toute route d'ecriture n'inscrivant
aucun evenement — reste a ecrire : il n'a pas d'objet tant qu'aucun pilier
metier n'expose de POST. A ajouter avec la premiere route d'ecriture du pilier
« activites », faute de quoi la regle ci-dessus ne sera qu'une intention.

Les tables etant partitionnees avec une cle primaire composite, l'insertion se
fait en SQL direct : l'ORM de Django ne sait pas ecrire dans une table dont la
cle primaire n'est pas une colonne unique.
"""

from typing import Any

from django.db import connection

from noyau.identite.modeles import Utilisateur


def inscrire(
    *,
    objet_type: str,
    objet_id: int,
    type_evenement: str,
    libelle: str,
    acteur: Utilisateur | None = None,
    agit_pour: Utilisateur | None = None,
    detail: str | None = None,
    courrier_id: int | None = None,
    structure_id: int | None = None,
    donnees: dict[str, Any] | None = None,
) -> None:
    """
    Inscrit un fait au journal.

    `acteur` est qui a saisi ; `agit_pour` est le titulaire au nom duquel il
    agit, en cas de delegation. Renseigner les deux n'est pas facultatif quand
    une delegation est active : c'est ce qui distingue « le remplacant a
    valide » de « le directeur a valide ».

    `structure_id` dit **dans quelle structure le geste a eu lieu**, et non de
    quelle structure vient l'acteur : un agent de la DSR qui ecrit dans le
    dossier d'une direction n'y transporte pas sa propre structure. Laisse a
    `None`, l'evenement est un **jalon public** — le trajet du courrier, que
    toute structure cotee a le droit de lire. Renseigne, il ne sort pas de la
    structure nommee (voir `courrier/cloisonnement.py`).

    Le defaut est donc le moins protecteur des deux, et c'est deliberé : un
    evenement qu'on oublie de qualifier reste visible, au lieu de disparaitre
    du dossier sans que personne ne s'en apercoive.
    """
    import json

    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO evenement (objet_type, objet_id, courrier_id, type_evenement,
                                   libelle, detail, acteur_id, agit_pour_id,
                                   structure_id, donnees)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                objet_type,
                objet_id,
                courrier_id,
                type_evenement,
                libelle,
                detail,
                acteur.pk if acteur else None,
                agit_pour.pk if agit_pour else None,
                structure_id,
                json.dumps(donnees) if donnees else None,
            ],
        )


def tracer_acces(
    *,
    acteur: Utilisateur,
    objet_type: str,
    action: str,
    objet_id: int | None = None,
    adresse_ip: str | None = None,
    agent_utilisateur: str | None = None,
) -> None:
    """
    Trace une consultation — RF-ADM-03.

    A appeler sur la lecture d'un objet **sensible** : courrier confidentiel,
    dossier clos, piece versee aux archives. Pas sur chaque liste, sinon la
    table grossit de plusieurs millions de lignes par mois sans rien apprendre
    a personne.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO journal_acces (acteur_id, objet_type, objet_id, action,
                                       adresse_ip, agent_utilisateur)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [acteur.pk, objet_type, objet_id, action, adresse_ip, agent_utilisateur],
        )

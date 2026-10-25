"""
La troisieme porte de la regle de visibilite.

La regle, telle que le client l'a enoncee le 11 aout 2026 :

    « On voit ce a quoi on est rattache — sa structure, plus ce sur quoi on a
      ete cote ou designe. Tout le reste est invisible, sauf permission
      explicite de consolidation. »

**Trois portes, jamais une seule.** `portee.restreindre()` n'en tient qu'une :
le rattachement, par la structure ou par l'agent. Les deux autres sont
particulieres au courrier :

 * la **cotation** — ma structure a ete cotee, je vois le courrier ;
 * la **designation** — j'ai ete designe au suivi, je le vois **meme hors de ma
   structure**. C'est la raison d'etre de cette porte : la personne de suivi
   coordonne au-dessus du chef de file, et souvent depuis une autre direction.

Ce module ne porte que la troisieme. Les deux premieres relevent du pilier
courrier, avec les tables qu'elles interrogent.

**Aucun modele ne couvre encore `cotation_suivi`** : le pilier courrier n'est pas
commence, et l'ouvrir pour une lecture serait disproportionne. La requete est
donc en SQL direct, comme `_courriers_en_cours` dans l'habilitation. Le jour ou
le pilier existera, ce module deviendra une ligne d'ORM — et son role, lui, ne
changera pas.
"""

from django.db import connection

from noyau.identite.modeles import Utilisateur


def courriers_suivis(utilisateur: Utilisateur) -> set[int]:
    """
    Les courriers dont l'utilisateur assure le suivi, aujourd'hui.

    Seules les designations **ouvertes** ouvrent un acces : une designation
    retiree laisse sa trace au registre, elle ne donne plus a voir. Sans quoi
    un agent qui a suivi un courrier il y a trois ans le verrait encore.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT c.courrier_id
              FROM cotation_suivi s
              JOIN cotation c ON c.id = s.cotation_id
             WHERE s.utilisateur_id = %s
               AND s.retire_le IS NULL
               AND c.invalide_le IS NULL
            """,
            [utilisateur.pk],
        )
        return {ligne[0] for ligne in curseur.fetchall()}


def suit(utilisateur: Utilisateur, courrier_id: int) -> bool:
    """Vrai si l'utilisateur assure aujourd'hui le suivi de ce courrier."""
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT 1
              FROM cotation_suivi s
              JOIN cotation c ON c.id = s.cotation_id
             WHERE s.utilisateur_id = %s
               AND c.courrier_id = %s
               AND s.retire_le IS NULL
               AND c.invalide_le IS NULL
             LIMIT 1
            """,
            [utilisateur.pk, courrier_id],
        )
        return curseur.fetchone() is not None


def suiveur(courrier_id: int) -> int | None:
    """
    Qui suit ce courrier, s'il est suivi.

    **C'est a cette personne que part la relance**, et non au chef de file.
    L'inverse se lit encore dans de vieux commentaires ; il est faux.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT s.utilisateur_id
              FROM cotation_suivi s
              JOIN cotation c ON c.id = s.cotation_id
             WHERE c.courrier_id = %s
               AND s.retire_le IS NULL
               AND c.invalide_le IS NULL
             LIMIT 1
            """,
            [courrier_id],
        )
        ligne = curseur.fetchone()
        return ligne[0] if ligne else None

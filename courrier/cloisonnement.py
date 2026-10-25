"""
Ce qu'une structure lit du dossier interne d'une autre — c'est-a-dire rien.

`visibilite.py` decide **quels courriers** un agent voit. Ce module decide, une
fois le courrier ouvert, **quelle part de son dossier** lui est rendue. Les deux
questions sont distinctes, et les confondre a produit le defaut que ce module
corrige : trois structures cotees sur le meme courrier voyaient chacune le
journal complet des deux autres — qui la DAF a mis sur l'affaire, ce que son
directeur a ecrit a son chef de service, combien de temps le dossier est reste
sur un bureau.

L'exigence, telle que le client l'a posee :

    « Pour les structures, le suivi est gere par leur bureau d'ordre — entree et
      sortie de la structure — sans exposer inutilement les instructions
      internes confidentielles aux autres utilisateurs. »

Deux notions, et il faut les tenir separees :

 * le **jalon** — enregistre, cote, entre en structure, sorti, cloture. C'est le
   trajet, il regarde tout le monde, et c'est ce que le bureau d'ordre d'une
   structure a besoin de savoir pour tenir son registre ;
 * le **geste interne** — affectation a un collaborateur, instruction du
   directeur a son service, redaction. Il regarde la structure qui l'a pose, et
   personne d'autre.

La frontiere est portee par `evenement.structure_id` : NULL est un jalon,
renseigne est un geste interne. Le choix du NULL par defaut n'est pas anodin —
un evenement qu'on oublierait de qualifier reste public, donc **aussi visible
qu'avant** cette migration. Le cloisonnement ne peut pas cacher par accident ce
qu'il n'a pas ete ecrit pour cacher, ce qui serait la pire des deux erreurs :
une piece manquante au dossier sans que personne ne s'en apercoive.

**Qui traverse le cloisonnement.** La DSR, parce que sa mission est le suivi des
delais et qu'elle ne peut pas relancer ce qu'elle ne voit pas ; le Directeur
general, qui cote ; et plus generalement toute portee `toutes`, qui consolide.
C'est exactement le mapping complet que l'exigence lui reconnait, et il n'entre
pas en contradiction avec le cloisonnement : le secret des instructions internes
protege une structure de sa voisine, pas de son autorite de tutelle.

La serrure du confidentiel, elle, n'est pas ici : elle ferme le courrier entier
et se pose bien avant, dans `visibilite.py`.
"""

from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from noyau.perimetre.portee import structures_visibles


def structures_lisibles(utilisateur: Utilisateur) -> set[int] | None:
    """
    Les structures dont l'agent lit le dossier interne.

    `None` signifie **aucun cloisonnement** — l'agent lit tout le dossier. Comme
    dans `structures_visibles()`, ce n'est pas la meme chose qu'un ensemble
    contenant les soixante-dix-sept structures du Port : l'appelant doit alors ne
    poser aucun filtre, plutot que construire un `IN` de tout l'organigramme.

    Trois voies l'ouvrent :

     * la **portee `toutes`** — consolider suppose de lire ;
     * la permission `REL`, celle de la relance : la DSR relance sur des faits
       internes — qui detient le courrier, depuis quand, ce qu'on lui a demande.
       Sans cette voie, le mapping complet que l'exigence lui reconnait
       s'arreterait a la porte de chaque direction ;
     * `VUE_DG`, la vue d'ensemble du Directeur general, qui cote et doit relire
       ce qu'il a coté.

    Sinon, l'agent lit le dossier interne des structures de son perimetre, plus
    celui de sa structure de rattachement — laquelle n'y figure pas toujours :
    un agent en portee `propre` sans perimetre pose n'aurait sinon acces a rien,
    pas meme a ce que son propre chef lui a ecrit.
    """
    if possede(utilisateur, PERM.REL) or possede(utilisateur, PERM.VUE_DG):
        return None

    visibles = structures_visibles(utilisateur)
    if visibles is None:
        return None

    identifiants = set(visibles.values_list("pk", flat=True))
    if utilisateur.structure_id is not None:
        identifiants.add(utilisateur.structure_id)
    return identifiants


def lit_le_dossier_de(utilisateur: Utilisateur, structure_id: int | None) -> bool:
    """
    L'agent lit-il ce geste ?

    `structure_id` a `None` est un jalon : oui, toujours. C'est la meme regle que
    celle du filtre SQL, ecrite pour les appelants qui tiennent deja leurs lignes
    en memoire — les cotations, par exemple, qui viennent de l'ORM.
    """
    if structure_id is None:
        return True
    lisibles = structures_lisibles(utilisateur)
    return lisibles is None or structure_id in lisibles

"""
A quoi une piece jointe peut se rattacher, et qui a le droit de l'y poser.

## Le probleme que ce module resout

`piece_jointe` est generique : `objet_type` / `objet_id`, comme `evenement`.
C'est ce qui permet d'attacher un fichier a une activite, a un dossier ou a une
demande d'usager sans creer trois tables.

Mais une route generique `POST /pieces` **ne peut pas savoir** si l'appelant a
le droit d'attacher quelque chose a l'activite n° 156. La permission depend du
pilier, et la visibilite depend du perimetre — deux questions auxquelles
`noyau` ne repond pas tout seul.

Trois issues possibles, et une seule tient :

 * ne rien verifier — c'est une fuite en ecriture, et pire : une piece deposee
   sur un objet qu'on ne voit pas devient lisible par ceux qui le voient ;
 * deporter le depot dans chaque pilier — six routes qui font la meme chose,
   dont cinq finiront par diverger sur le plafond de taille ou le calcul de
   l'empreinte ;
 * **declarer, une fois par type d'objet, la permission exigee et la requete
   deja restreinte.** C'est ce que fait ce registre.

## Ce qu'une entree declare

`permission_ecriture` — ce qu'il faut porter pour deposer ou retirer. C'est la
permission d'**ecriture** du pilier : joindre une piece a un dossier est un acte
d'instruction.

`permission_lecture` — ce qu'il faut porter pour lister et telecharger. Le
registre a longtemps n'en declare qu'une seule, celle d'ecriture, et la lecture
s'en servait faute de mieux : un agent qui voyait l'activite recevait un 404 sur
ses pieces des lors qu'il ne portait pas `ACT_SAI`, c'est-a-dire des qu'il
n'avait pas le droit d'en creer. Une piece n'a pas de droits propres — elle a
ceux de son objet — et cela vaut dans les deux sens : qui voit l'objet voit ce
qui y est joint. Les deux permissions coincident la ou le pilier n'en distingue
qu'une (le portail : `EXT` pour lire comme pour deposer).

`visibles` — une fonction qui rend les objets de ce type que l'agent peut
atteindre, **deja restreints**. C'est elle qui porte `restreindre()`, ou le
filtre par deposant pour le portail (ADR 013). Une fonction et non un couple de
champs : le portail ne se restreint pas par perimetre, et forcer sa regle dans
le moule du socle serait exactement la faille que l'ADR 013 ecarte.

`libelle` — comment l'objet se nomme a l'ecran et au journal.

## Ajouter un type

Une entree. Rien d'autre, et surtout pas une route. Si un pilier a besoin d'une
regle que ce registre ne sait pas exprimer, c'est le registre qu'il faut
etendre — pas une seconde route de depot.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import QuerySet

from noyau.habilitation.dependances import PERM
from noyau.identite.modeles import Utilisateur


@dataclass(frozen=True)
class Rattachement:
    libelle: str
    permission_lecture: str
    permission_ecriture: str
    visibles: Callable[[Utilisateur], QuerySet]


def _activites(agent: Utilisateur) -> QuerySet:
    # Import differe : `noyau` n'importe aucun pilier au chargement. C'est la
    # regle du socle, et la contourner ici ferait dependre l'authentification
    # de la presence du pilier activite.
    from activite.lecture import _visibles

    return _visibles(agent)


def _dossiers(agent: Utilisateur) -> QuerySet:
    from dossier.lecture import dossiers_visibles

    return dossiers_visibles(agent)


def _courriers(agent: Utilisateur) -> QuerySet:
    """
    Les courriers que cet agent peut atteindre.

    `visibles()` et non `restreindre()` : le registre a trois portes de plus que
    le perimetre — rattachement, cotation ou designation, consolidation explicite
    (ADR 022). S'en tenir a `restreindre()` ici aurait ouvert les pieces d'un
    courrier confidentiel a qui voit la structure sans voir le courrier.
    """
    from courrier.modeles import Courrier
    from courrier.visibilite import visibles

    return visibles(Courrier.objects.filter(invalide_le__isnull=True), agent)


def _demandes(agent: Utilisateur) -> QuerySet:
    """
    Les demandes de l'usager, et **les siennes seules**.

    Pas de `restreindre()` : un compte du portail n'a ni structure ni
    perimetre, et lui en donner un serait *plus* permissif que de n'en donner
    aucun (ADR 013). Le filtre est `deposant`, comme partout dans le pilier.
    """
    from portail.modeles import DemandeUsager

    return DemandeUsager.objects.filter(invalide_le__isnull=True, deposant=agent)


#: Les types d'objet auxquels une piece peut se rattacher.
#:
#: Un `objet_type` absent de ce registre est **refuse**, et ce n'est pas une
#: precaution formelle : accepter un type inconnu reviendrait a accepter
#: n'importe quelle chaine, donc a deposer des fichiers rattaches a rien, que
#: nul ecran ne montre et que nulle regle de conservation n'atteint.
REGISTRE: dict[str, Rattachement] = {
    "activite": Rattachement(
        libelle="Activité",
        permission_lecture=PERM.ACT_LEC,
        permission_ecriture=PERM.ACT_SAI,
        visibles=_activites,
    ),
    "courrier": Rattachement(
        # **Ecrire, c'est enregistrer.** La numerisation du pli est le geste du
        # bureau d'ordre, et `ENR` est la permission qui l'ouvre. La lecture,
        # elle, suit le courrier : qui voit le courrier voit ce qui y est joint.
        #
        # Consequence assumee, et la seule : l'agent traitant qui porte `TRA`
        # sans `ENR` ne peut pas joindre de piece a un courrier. Le registre ne
        # sait declarer qu'une permission d'ecriture par type d'objet, et
        # partager le depot entre le bureau d'ordre et l'instruction demande de
        # savoir laquelle des deux mains verse quoi — ce qu'aucun document de
        # cadrage ne dit (A63).
        libelle="Courrier",
        permission_lecture=PERM.LEC,
        permission_ecriture=PERM.ENR,
        visibles=_courriers,
    ),
    "dossier": Rattachement(
        libelle="Dossier",
        permission_lecture=PERM.DOS_LEC,
        permission_ecriture=PERM.DOS_INS,
        visibles=_dossiers,
    ),
    "demande": Rattachement(
        # Le portail ne distingue pas lire d'ecrire : `EXT` ouvre l'espace de
        # l'usager, et c'est le filtre par `deposant` qui borne (ADR 013).
        libelle="Demande d'usager",
        permission_lecture=PERM.EXT,
        permission_ecriture=PERM.EXT,
        visibles=_demandes,
    ),
}

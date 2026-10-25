"""
Le routage direct — la cotation d'office a l'enregistrement.

    « Les factures vont directement chez le DFC, sans passer par le DG. »

C'est l'exigence, et elle est plus etroite qu'un circuit : elle ne decrit aucun
trajet de validation, aucune etape, aucun delai d'escalade. Elle dit vers quelle
structure le courrier part **des sa saisie au bureau d'ordre central**, sans
attendre la cotation de l'autorite.

**Ce module ne deroule donc aucun circuit, et c'est deliberé.** `circuit_etape`
est vide : le trajet reel d'un courrier au Port n'a jamais ete communique (A24),
et brancher le routage direct sur `circuit_regle` aurait fait dependre une regle
connue d'une regle qui ne l'est pas. La table `regle_routage` porte la seule
chose que le client a dite, et rien de plus.

**La regle la plus specifique l'emporte.** La specificite se compte en criteres
renseignes — nature, sens, correspondant — et `priorite` croissante departage le
reste. Le tri est fait ici, en Python, plutot qu'en SQL : trois criteres se
comptent plus lisiblement qu'ils ne se classent dans un `ORDER BY` a base de
`CASE WHEN … IS NOT NULL`, et la table tiendra toujours dans une requete.

La cotation produite est une **vraie cotation**, ecrite par `services.coter()` :
elle porte son rang, elle declenche le passage en structure, elle notifie, elle
s'inscrit au journal. Une voie d'ecriture parallele aurait produit des courriers
routes qui n'apparaissent dans aucun registre de bureau d'ordre.
"""

from courrier.modeles import Courrier
from noyau.parametrage.modeles import RegleRoutage
from noyau.parametres import service as parametres

#: Le routage direct s'eteint sans redeploiement. Le parametre est une
#: **hypothese** : personne n'a confirme que le bureau d'ordre central cote
#: d'office plutot que de soumettre au Directeur general (A69).
CLE_ACTIF = "courrier.routage_direct_actif"


def regle_applicable(courrier: Courrier) -> RegleRoutage | None:
    """
    La regle de routage qui vaut pour ce courrier, s'il y en a une.

    `None` n'est pas un echec : c'est le cas ordinaire. L'absence de regle veut
    dire « ce courrier suit la voie normale, il attend la cotation de
    l'autorite » — jamais « on ne sait pas quoi en faire ». C'est la raison pour
    laquelle `regle_routage` n'a **pas** de regle de repli, a la difference de
    `circuit_regle` : un repli aurait cote d'office tout le courrier du Port a
    une structure unique.
    """
    if not parametres.valeur(CLE_ACTIF, True):
        return None

    candidates = [
        regle
        for regle in RegleRoutage.objects.filter(
            actif=True, invalide_le__isnull=True
        ).select_related("structure", "mention_type")
        if _correspond(regle, courrier)
    ]
    if not candidates:
        return None

    # `-specificite` d'abord : « facture de tel fournisseur » l'emporte sur
    # « toute facture arrivee », sans qu'aucune priorite n'ait a etre tenue a la
    # main. `id` ferme le tri — deux regles egales en tout doivent departager de
    # facon stable, sinon le meme courrier part ailleurs selon l'ordre de la
    # base.
    candidates.sort(key=lambda regle: (-regle.specificite, regle.priorite, regle.pk))
    return candidates[0]


def _correspond(regle: RegleRoutage, courrier: Courrier) -> bool:
    """
    Un critere non renseigne ne filtre rien.

    C'est ce qui fait qu'une regle « toute facture » s'applique quel que soit
    l'expediteur, sans qu'il faille l'ecrire une fois par correspondant.
    """
    if regle.nature_id is not None and regle.nature_id != courrier.nature_id:
        return False
    if regle.sens is not None and regle.sens != courrier.sens:
        return False
    if regle.correspondant_id is not None and regle.correspondant_id != courrier.expediteur_id:
        return False
    return True

"""
Garde de permission pour les routes Ninja.

Le front porte deja des gardes (`ExigePermission` sur chaque route). Ils ne
protegent rien : ils evitent a l'agent d'ouvrir un ecran vide. **La seule
protection reelle est ici.**

Usage :

    @routeur.post("/{id}/suspension", auth=exige(PERM.DEC))
    def suspendre(requete, id: int, saisie: SaisieSuspension): ...

Un endpoint sans `auth=` est un endpoint ouvert. Le test
`test_toute_route_porte_une_authentification` echoue si l'un en manque — c'est
le filet, et il n'est pas facultatif.
"""

from django.http import HttpRequest
from ninja.security import SessionAuth

from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur


class ExigePermission(SessionAuth):
    """Session ouverte **et** au moins une des permissions citees."""

    def __init__(self, *codes: str) -> None:
        super().__init__()
        self.codes = codes

    # `cle: str | None` et non `str` : c'est la signature de `SessionAuth`,
    # et la restreindre violerait la substitution de Liskov — mypy le refuse.
    def authenticate(self, requete: HttpRequest, cle: str | None) -> Utilisateur | None:
        utilisateur = getattr(requete, "user", None)
        if utilisateur is None or not utilisateur.is_authenticated:
            return None
        if self.codes and not possede(utilisateur, *self.codes):
            return None
        return utilisateur


def exige(*codes: str) -> ExigePermission:
    return ExigePermission(*codes)


#: Session ouverte, sans exigence de permission.
#:
#: Cinq usages seulement, et chacun est commente a son point d'appel :
#:
#:  * `/moi` et `/deconnexion` — exiger une permission rendrait l'application
#:    inaccessible a qui n'en porte qu'une seule ;
#:  * les delegations d'un responsable sur lui-meme (§3.4 : « sans avoir a
#:    demander a quiconque »). Ce qui borne le geste n'est pas une permission
#:    d'administration mais la regle « on ne delegue que ce que l'on possede ».
#:  * `GET /referentiels/structures` — l'organigramme est la liste dans
#:    laquelle on choisit la structure vers laquelle on cote, donc hors du
#:    perimetre de l'agent par construction (ADR 007). La derogation s'arrete
#:    a l'organigramme : elle ne s'etend pas aux autres routes `/referentiels`.
#:  * `/pieces/*` — la permission exigee **depend de l'objet auquel on
#:    rattache et du geste** : deposer ou retirer demande la saisie du pilier
#:    (`ACT_SAI`, `DOS_INS`, `EXT`), lister ou telecharger sa lecture
#:    (`ACT_LEC`, `DOS_LEC`, `EXT`). `exige()` ne sait poser ni l'une ni
#:    l'autre question — la premiere depend du corps de la requete. La garde
#:    est portee en entier par `noyau.pieces.services._cible_accessible`, qui
#:    refuse la permission manquante **et** l'objet hors perimetre. Voir
#:    ADR 017, et le couple de permissions dans `noyau/pieces/rattachement.py`.
#:  * `/notifications` (hors `/file`) — une notification est **adressee a une
#:    personne**, et il n'existe pas de permission « lire ce qui m'est
#:    adresse ». En creer une serait pouvoir la retirer a quelqu'un, donc le
#:    laisser dans le silence sans qu'aucun ecran ne le dise. Le filtre est le
#:    destinataire, comme le portail filtre par deposant (ADR 013). L'etat de
#:    la file, lui, exige `ADM_PAR` : c'est de l'exploitation.
#:
#: Tout autre endpoint doit nommer la permission qu'il requiert.
session_seule = ExigePermission()


class PERM:
    """
    Codes de permission, en miroir de la table `permission` et de
    `frontend/src/types/habilitation.ts`.

    Les trois listes doivent rester identiques. Le test
    `test_codes_de_permission_alignes` compare celle-ci a la base ; l'alignement
    avec le front reste manuel, faute de pouvoir importer du TypeScript.
    """

    # Courrier
    LEC = "LEC"
    ENR = "ENR"
    COT = "COT"
    COT_DEL = "COT_DEL"
    AFF = "AFF"
    TRA = "TRA"
    VAL = "VAL"
    TRANS = "TRANS"
    CLO = "CLO"
    REL = "REL"
    IMP = "IMP"
    CONF = "CONF"
    STAT = "STAT"
    #: Tenir le bureau d'ordre de sa structure — accuser reception d'une entree,
    #: prononcer une sortie. Au Port, le bureau d'ordre d'une structure **est**
    #: son point focal. Voir ADR 031.
    BO_STR = "BO_STR"

    # Activites
    ACT_LEC = "ACT_LEC"
    ACT_SAI = "ACT_SAI"
    ACT_VAL = "ACT_VAL"
    #: Recalibrer un avancement declare. Le seul profil DSR la porte — pas le
    #: controle de gestion, qui porte pourtant ACT_VAL : l'exigence dit « seule
    #: la DSR ». Voir ADR 030.
    ACT_REC = "ACT_REC"

    # Gouvernance
    DEC = "DEC"
    INST = "INST"
    DISPO = "DISPO"

    # Performance
    SCORE = "SCORE"
    SCORE_ADM = "SCORE_ADM"
    COCKPIT = "COCKPIT"
    VUE_DG = "VUE_DG"
    VUE_CODIR = "VUE_CODIR"

    # Exploitation
    EXP_SAI = "EXP_SAI"
    EXP_LEC = "EXP_LEC"

    # Dossiers
    DOS_LEC = "DOS_LEC"
    DOS_INS = "DOS_INS"
    DOS_VAL = "DOS_VAL"

    # Archivage et externe
    ARCH = "ARCH"
    EXT = "EXT"

    # Administration
    ADM_ORG = "ADM_ORG"
    ADM_HAB = "ADM_HAB"
    ADM_PAR = "ADM_PAR"
    AUDIT = "AUDIT"
    ADM_TEC = "ADM_TEC"

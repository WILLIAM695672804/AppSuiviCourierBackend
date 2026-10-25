"""
Formes echangees par le pilier habilitation.

Elles sont le miroir de `frontend/src/features/habilitation/api.ts`. Le front
n'est pas encore branche, mais c'est lui le consommateur : concevoir une autre
forme aujourd'hui reviendrait a la traduire demain, et une traduction est un
endroit ou deux verites s'installent.

Convention posee dans `config/api.py` : **sortie en camelCase**. La base est en
snake_case ; les schemas sont le seul endroit ou les deux se croisent.
"""

from datetime import date

from ninja import Schema


class UtilisateurLigne(Schema):
    """Une ligne du registre des comptes."""

    id: int
    nomComplet: str
    initiales: str
    identifiant: str
    structure: str
    poste: str
    profil: str
    etat: str


class ProfilSortie(Schema):
    id: int
    #: Le code du profil — la clef par laquelle le semis et les migrations le
    #: designent. Il n'est pas modifiable : voir `services.modifier_profil`.
    code: str
    libelle: str
    description: str | None
    nombreAgents: int
    #: `systeme` en base — le profil vient du referentiel livre. Depuis
    #: l'ADR 041 il ne bloque plus les permissions, qui se cochent comme celles
    #: de tout autre profil : il dit seulement que ce profil ne se **retire pas**
    #: du catalogue, parce que le semis et les migrations le citent par son code.
    verrouille: bool
    permissions: list[str]


class BasculePermission(Schema):
    permission: str
    accordee: bool


class SaisieCreationProfil(Schema):
    """
    Creation d'un profil — G-02.

    `depuisProfilId` copie les permissions d'un profil existant, y compris
    systeme : c'est l'usage que le refus de `basculer_permission` recommande.
    La copie est faite une fois ; les deux profils divergent ensuite.

    `systeme` n'y figure pas et n'y figurera pas : le drapeau designe le
    referentiel livre, et un profil cree a l'ecran n'en fait pas partie.
    """

    code: str
    libelle: str
    description: str | None = None
    depuisProfilId: int | None = None


class SaisieModificationProfil(Schema):
    """Le code n'y figure pas : le renommer casserait les references du semis,
    des tests et des migrations sans qu'aucune erreur ne se produise avant."""

    libelle: str | None = None
    description: str | None = None


class SaisieInvalidationProfil(Schema):
    motif: str


class PerimetreLigne(Schema):
    """
    Une entree du catalogue des perimetres.

    Le catalogue n'est pas une table : ce sont les **quatre portees** du
    referentiel, presentees avec un libelle. `id` est donc un identifiant de
    referentiel, stable, et non une clef de ligne.

    Les options viennent des permissions des agents concernes, sauf
    `lectureClotures` qui n'a aucune permission correspondante et reste faux —
    voir `services.OPTIONS_PERIMETRE` et docs/questions-ouvertes.md, A14.
    """

    id: int
    libelle: str
    assise: str
    etendue: str
    nombreAgents: int
    inclureDescendants: bool
    voirConfidentiel: bool
    lectureClotures: bool
    statistiquesAgregees: bool


class ProfilPorte(Schema):
    id: int
    libelle: str
    #: `systeme` en base — profil du referentiel livre. Il se retire d'un agent,
    #: et ne se retire pas du catalogue. Voir `ProfilSortie.verrouille`.
    verrouille: bool


class PerimetrePorte(Schema):
    portee: str
    #: Le libelle du referentiel — « Sa structure et ses descendants ».
    libelle: str
    structureId: int | None
    structure: str | None


class FicheCompte(Schema):
    """
    Un compte, avec **ce qui compose ses droits**.

    Distincte d'`UtilisateurLigne`, qui joint les profils en une chaine pour le
    registre : on ne peut pas retirer un profil dont on n'a pas l'identifiant,
    ni changer une portee qu'on ne connait pas. Le registre affiche, cette
    fiche administre.
    """

    id: int
    nomComplet: str
    identifiant: str
    courriel: str | None
    telephone: str | None
    matricule: str | None
    structureId: int | None
    structure: str
    posteId: int | None
    poste: str
    etat: str
    #: Vrai si un mot de passe local est pose. Faux = le compte attend l'annuaire
    #: et ne peut pas ouvrir de session (A20).
    accesLocal: bool
    profils: list[ProfilPorte]
    #: Absent = l'agent ne voit rien. Ne devrait pas arriver par l'API, qui
    #: impose une portee des la creation, mais un compte seme ou repris en base
    #: peut l'etre.
    perimetre: PerimetrePorte | None
    sessionCourrier: str | None


class SaisieCompte(Schema):
    """
    La creation d'un compte.

    `profilId` et `portee` sont **obligatoires** : un compte sans profil ne peut
    rien, un compte sans perimetre ne voit rien. Voir `services.creer_compte`.

    `motDePasse` est provisoire — RF-ADM-02 delegue l'authentification a
    l'annuaire. Omis, le compte existe et attend le SSO.
    """

    identifiant: str
    prenom: str
    nom: str
    structureId: int
    posteId: int
    profilId: int
    portee: str
    #: Par defaut, la structure de l'agent. Interdit pour la portee « toutes ».
    perimetreStructureId: int | None = None
    courriel: str | None = None
    telephone: str | None = None
    matricule: str | None = None
    motDePasse: str | None = None


class SaisieModificationCompte(Schema):
    """Seuls les champs fournis sont touches ; les autres restent."""

    prenom: str | None = None
    nom: str | None = None
    courriel: str | None = None
    telephone: str | None = None
    structureId: int | None = None
    posteId: int | None = None


class SaisieEtatCompte(Schema):
    #: Faux suspend, vrai retablit. Il n'y a pas de suppression : elle trouerait
    #: les pistes d'audit.
    actif: bool


class SaisieProfil(Schema):
    profilId: int


class SaisiePerimetre(Schema):
    """
    `structureId` est absent pour la portee « toutes », obligatoire pour les
    trois autres. Le service refuse les deux erreurs symetriques.
    """

    portee: str
    structureId: int | None = None


class SaisieRattachement(Schema):
    utilisateurId: int


class AgentRattache(Schema):
    id: int
    nomComplet: str
    poste: str
    rattacheLe: str


class SessionSortie(Schema):
    id: int
    libelle: str
    courriersEnCours: int
    agents: list[AgentRattache]


class DelegationSortie(Schema):
    id: int
    titulaire: str
    delegataire: str
    poste: str
    etendue: str
    debut: str
    fin: str
    motif: str
    #: Deduit des dates et de l'invalidation, jamais stocke.
    etat: str


class DelegataireSortie(Schema):
    id: int
    nomComplet: str
    poste: str


class DelegationPossible(Schema):
    """
    Ce que la session peut deleguer, et a qui.

    Le serveur seul repond : il connait les permissions du titulaire. Proposer
    au client une etendue que le serveur refusera ensuite ne ferait que
    deplacer le refus apres la saisie.
    """

    delegataires: list[DelegataireSortie]
    etendues: list[str]


class SaisieDelegation(Schema):
    delegataireId: int
    etendue: str
    debut: date
    fin: date
    motif: str

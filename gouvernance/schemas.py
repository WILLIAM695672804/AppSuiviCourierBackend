"""
Formes echangees par le pilier gouvernance.

Miroir de `frontend/src/features/gouvernance/api.ts`. Le front n'est pas encore
branche, mais c'est lui le consommateur : concevoir une autre forme aujourd'hui
reviendrait a la traduire demain, et une traduction est un endroit ou deux
verites s'installent.

Convention posee dans `config/api.py` : **sortie en camelCase**.

**Les libelles sortent en francais lisible**, accents compris : `etat` vaut
« En retard », pas `en_retard` ; `instance` vaut « Directeur général ». La base,
elle, garde ses codes sans accent. La traduction se fait dans `lecture.py`, une
seule fois.

Le front nomme « décision » ce que la base nomme `engagement` (ADR 006). Les
schemas gardent **le vocabulaire du front sur ses ecrans** — une decision reste
une decision pour qui la lit — tout en sachant que prescription de filiale et
recommandation externe sont le meme objet, avec leurs propres formes de sortie.
"""

from ninja import Schema

# =====================================================================
#  Communs
# =====================================================================


class Compteur(Schema):
    libelle: str
    valeur: int
    note: str
    feu: str


class Identifiant(Schema):
    id: int


# =====================================================================
#  Engagements — le registre des decisions
# =====================================================================


class StructureChargee(Schema):
    id: int
    sigle: str
    libelle: str
    #: Rang 1 : la structure qui rend compte. Meme regle que le chef de file.
    pilote: bool
    avancement: float


class DecisionLigne(Schema):
    """Une ligne du registre. Tout ce qui s'affiche sans ouvrir la fiche."""

    id: int
    #: `engagement.reference`, posee par declencheur — « DEC-2026-0001 ».
    reference: str
    instance: str
    #: La seance dont la decision est issue, en clair : « CODIR du 12 juin 2026 ».
    seance: str
    objet: str
    dateDecision: str
    echeance: str | None
    etat: str
    avancement: float
    feu: str
    structures: list[StructureChargee]
    #: Une decision relancee trois fois est un signal, pas un detail.
    relances: int


class RegistreDecisions(Schema):
    decisions: list[DecisionLigne]
    compteurs: list[Compteur]
    total: int


class JalonSortie(Schema):
    id: int
    libelle: str
    echeance: str
    fait: bool
    dateRealisation: str | None
    structure: str


class ObservationSortie(Schema):
    id: int
    auteur: str
    initiales: str
    poste: str
    date: str
    texte: str
    #: Une relance de la DSR n'est pas une observation ordinaire : elle se voit.
    relance: bool


class OrigineSortie(Schema):
    """
    D'ou vient la decision, telle que l'ecran l'affiche.

    « Instruction verbale » quand aucune seance n'est rattachee : le §17 en fait
    un cas ordinaire, pas une anomalie.
    """

    type: str
    libelle: str
    id: int | None


class Retombee(Schema):
    type: str
    libelle: str
    reference: str
    chemin: str | None


class DecisionDetail(DecisionLigne):
    contexte: str
    origine: OrigineSortie
    jalons: list[JalonSortie]
    observations: list[ObservationSortie]
    #: Ce que la decision a produit. Le lien avec le courrier reste lache.
    retombees: list[Retombee]


# =====================================================================
#  Seances
# =====================================================================


class SeanceLigne(Schema):
    id: int
    reference: str
    type: str
    intitule: str
    date: str
    president: str
    participants: int
    #: « Déposé », « En attente » ou « Hors délai ». Se deduit, ne se stocke pas.
    depot: str
    dateDepot: str | None
    echeanceDepot: str
    decisionsIssues: int
    structure: str


class RegistreSeances(Schema):
    seances: list[SeanceLigne]
    compteurs: list[Compteur]
    total: int


class PointOrdreDuJour(Schema):
    id: int
    rang: int
    point: str
    rapporteur: str


class DocumentSortie(Schema):
    id: int
    nature: str
    libelle: str
    depose: bool
    dateDepot: str | None
    poids: str | None
    deposePar: str | None


class ParticipantSortie(Schema):
    nom: str
    initiales: str
    poste: str
    #: Convoque et present sont deux choses : c'est le lien avec le registre
    #: des disponibilites.
    present: bool


class DecisionIssue(Schema):
    id: int
    reference: str
    objet: str
    etat: str


class SeanceDetail(SeanceLigne):
    ordreDuJour: list[PointOrdreDuJour]
    documents: list[DocumentSortie]
    presents: list[ParticipantSortie]
    decisions: list[DecisionIssue]


# =====================================================================
#  Disponibilite
# =====================================================================


class DisponibiliteLigne(Schema):
    id: int
    responsable: str
    initiales: str
    poste: str
    #: La tete de structure pour qui consolide, le service pour un directeur.
    #: Au-dessus d'un directeur, la sous-structure n'existe pas.
    structure: str
    type: str
    du: str
    au: str
    #: Bornes comprises : du lundi au vendredi fait cinq jours.
    jours: int
    interimaire: str | None
    interimaireInitiales: str | None
    #: Le feu juge la suppleance, pas l'absence.
    feu: str
    enCours: bool
    saisiPar: str


class RegistreDisponibilites(Schema):
    disponibilites: list[DisponibiliteLigne]
    compteurs: list[Compteur]
    #: Absents sans interim a la date du jour. Compte **avant** les filtres :
    #: c'est une alerte, elle ne doit pas disparaitre parce qu'on trie.
    sansInterim: int


# =====================================================================
#  Filiales et representations
# =====================================================================


class OrganeSortie(Schema):
    id: int
    entite: str
    sigle: str
    nature: str
    organe: str
    prochaineSession: str
    etatPreparation: str
    documentsAttendus: int
    documentsRecus: int
    feu: str
    prescriptionsTotal: int
    prescriptionsExecutees: int
    prescriptionsEnRetard: int


class PrescriptionSortie(Schema):
    id: int
    reference: str
    entite: str
    objet: str
    sessionOrigine: str
    echeance: str
    avancement: float
    etat: str
    feu: str


class SuiviFiliales(Schema):
    organes: list[OrganeSortie]
    prescriptions: list[PrescriptionSortie]
    compteurs: list[Compteur]


class RepresentationSortie(Schema):
    id: int
    organisation: str
    sigle: str
    nature: str
    representant: str
    initiales: str
    suppleant: str | None
    mandatDu: str
    mandatAu: str
    reunionsTenues: int
    reunionsParticipees: int
    tauxParticipation: float
    feu: str
    #: Ce que l'institution retire de sa presence. Vide quand rien n'est declare.
    apport: str | None


class RecommandationSortie(Schema):
    id: int
    reference: str
    organisation: str
    objet: str
    emiseLe: str
    echeance: str | None
    structurePilote: str
    avancement: float
    etat: str
    feu: str


class SuiviRepresentations(Schema):
    representations: list[RepresentationSortie]
    recommandations: list[RecommandationSortie]
    compteurs: list[Compteur]


# =====================================================================
#  Conges
# =====================================================================


class PeriodeSortie(Schema):
    id: int
    du: str
    au: str
    jours: int
    etat: str


class LigneConges(Schema):
    id: int
    responsable: str
    initiales: str
    poste: str
    structure: str
    droits: int
    planifies: int
    solde: int
    periodes: list[PeriodeSortie]
    feu: str


class ConflitConges(Schema):
    """
    Deux agents d'une meme **tete de structure** absents en meme temps.

    `structure` porte le code de la tete — DSI, et non DSI-ET : c'est la
    direction qui se retrouve sans encadrement, pas le departement.

    Se calcule, ne se stocke pas : il change des qu'une periode bouge.
    """

    periode: str
    structure: str
    responsables: list[str]


class PlanningConges(Schema):
    annee: int
    lignes: list[LigneConges]
    conflits: list[ConflitConges]
    compteurs: list[Compteur]


# =====================================================================
#  Tableau de bord
# =====================================================================


class RepartitionInstance(Schema):
    instance: str
    total: int
    enRetard: int


class TableauDeBordGouvernance(Schema):
    compteurs: list[Compteur]
    #: Les moins avancees d'abord : une decision a 10 % relancee trois fois est
    #: le vrai signal, pas celle a 95 %.
    aRelancer: list[DecisionLigne]
    depotsEnSouffrance: list[SeanceLigne]
    absencesSansInterim: list[DisponibiliteLigne]
    parInstance: list[RepartitionInstance]


# =====================================================================
#  Ecritures
# =====================================================================


class SaisieDecision(Schema):
    instance: str
    #: Texte libre. Rattache a une seance si la reference correspond exactement,
    #: laisse vide sinon : deviner produirait un rattachement faux et invisible.
    seance: str = ""
    objet: str
    contexte: str = ""
    dateDecision: str
    echeance: str | None = None
    #: Identifiants dans l'ordre : **le premier est la structure pilote**. Au
    #: moins une — un engagement que nul ne porte n'est pas un engagement.
    structures: list[int]


class SaisieAvancement(Schema):
    #: Present dans le corps parce que le front le poste ; le chemin fait foi.
    decisionId: int | None = None
    avancement: float
    observation: str = ""
    jalonsFaits: list[int] = []


class SaisieRelance(Schema):
    decisionId: int | None = None
    motif: str
    #: La structure pilote par defaut : c'est elle qui rend compte.
    structureId: int | None = None


class PointSaisi(Schema):
    point: str
    #: Facultatif : un point peut etre inscrit avant qu'on sache qui le rapporte.
    rapporteurId: int | None = None


class SaisieSeance(Schema):
    type: str
    intitule: str
    date: str
    #: Facultatif : la presidence se decide parfois a l'ouverture de la seance.
    presidentId: int | None = None
    structure: str
    echeanceDepot: str
    ordreDuJour: list[PointSaisi] = []


class SaisieDocument(Schema):
    seanceId: int | None = None
    nature: str
    libelle: str
    nomFichier: str
    poids: str = ""


class SaisieAbsence(Schema):
    responsableId: int
    #: `poste` et `structure` ont disparu de cette saisie le 16 aout 2026. Le
    #: front les envoyait pour son propre affichage, et le service ne les a
    #: jamais ecrits — ils viennent de l'agent. Depuis que le responsable se
    #: choisit dans un selecteur (ADR 020), le front les tient de la meme
    #: source que le serveur, et n'a plus rien a lui reapprendre.
    type: str
    du: str
    au: str
    interimaireId: int | None = None


class SaisieDroitConges(Schema):
    """
    Le droit annuel d'un agent.

    `droitsJours` vient de la DRH et n'est pas calcule ici — l'anciennete, les
    reports et les majorations sont son affaire.
    """

    agentId: int
    annee: int
    droitsJours: int


class SaisiePeriodeConges(Schema):
    droitId: int
    du: str
    au: str


class SaisieArbitrageConges(Schema):
    """
    `etat` porte le libelle accentue de l'ecran — « Validé », « Reporté ».

    `motif` est **obligatoire pour un report** : le service refuse un report nu,
    faute de quoi l'agent resoumettrait la meme periode.
    """

    etat: str
    motif: str | None = None

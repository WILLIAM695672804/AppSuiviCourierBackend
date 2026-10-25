"""
Contrat des ecrans « dossiers a instruire ».

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/dossier/api.ts`.

Deux points de vigilance.

*Les libelles voyagent, pas les codes.* `etat`, `etape`, `type` et `criticite`
sortent avec leurs accents — « Réclamation », « En attente de complément ».
C'est ce que le front affiche tel quel, et ce qu'il renvoie dans ses filtres.
Le stockage, lui, reste sans accent : la conversion se fait dans
`lecture.py` et nulle part ailleurs.

*Le circuit sort en entier*, etapes a venir comprises. Un instructeur doit
savoir qui validera apres lui ; n'envoyer que l'etape courante l'obligerait a
demander, et c'est la question qu'un outil de suivi est cense supprimer.
"""

from ninja import Schema


class Compteur(Schema):
    libelle: str
    valeur: int
    note: str
    feu: str


class Dossier(Schema):
    id: int
    reference: str
    objet: str
    type: str
    demandeur: str
    structure: str
    instructeur: str
    initiales: str
    ouvertLe: str
    echeance: str
    etape: str
    etat: str
    criticite: str
    feu: str
    #: Negatif quand l'echeance est depassee. Le registre l'affiche a la place
    #: de la date : un instructeur cherche ce qui lui reste, pas une date a
    #: soustraire de tete.
    joursRestants: int
    #: La reference du courrier d'origine, sans cle etrangere vers lui. Le
    #: pilier courrier n'est pas en service ; voir A34.
    courrierOrigine: str | None
    courrierOrigineId: int | None


class RegistreDossiers(Schema):
    dossiers: list[Dossier]
    compteurs: list[Compteur]
    total: int


class VersionPiece(Schema):
    version: int
    deposeLe: str
    deposePar: str
    taille: str
    #: La derniere deposee. Les precedentes restent listees — RF-GED-04.
    courante: bool


class PieceDossier(Schema):
    id: int
    nom: str
    format: str
    versions: list[VersionPiece]


class EtapeCircuit(Schema):
    code: str
    libelle: str
    franchie: bool
    #: `null` quand l'etape est franchie sans que le journal en garde la date.
    date: str | None
    acteur: str | None


class Complement(Schema):
    id: int
    objet: str
    demandeLe: str
    demandePar: str
    echeance: str
    recuLe: str | None


class EvenementDossier(Schema):
    id: int
    type: str
    date: str
    auteur: str
    initiales: str
    poste: str
    texte: str
    #: Renseignes sur un retour : d'ou l'on vient, ou l'on retourne. C'est
    #: cette paire qui permet de reconstituer le chemin reel du dossier.
    etapeAvant: str | None
    etapeApres: str | None


class DossierDetail(Dossier):
    contexte: str
    #: Pourquoi ce dossier est arrive ici — RF-BPM-02. Sans cette phrase,
    #: l'affectation dynamique passe pour de l'arbitraire.
    regleAffectation: str
    #: `null` quand la regle appliquee ne porte pas de seuil — et non
    #: « 0 F CFA », qui se lirait comme un seuil que tout dossier franchit.
    seuil: str | None
    etapes: list[EtapeCircuit]
    pieces: list[PieceDossier]
    complements: list[Complement]
    historique: list[EvenementDossier]


class ModeleCourrier(Schema):
    id: int
    code: str
    libelle: str
    typologie: str
    description: str
    #: Derivees du corps, jamais saisies a cote : deux listes divergent.
    variables: list[str]
    #: Le corps **entier**. Un agent qui choisit un modele sur trois lignes de
    #: resume decouvre ce qu'il a envoye apres l'avoir envoye.
    corps: str
    misAJourLe: str
    misAJourPar: str
    utilisations: int


class Bibliotheque(Schema):
    modeles: list[ModeleCourrier]


# =====================================================================
#  Les saisies
# =====================================================================


class SaisieDossier(Schema):
    #: `0` ou absent quand le dossier est un depot direct. Le front envoie `0`
    #: parce que son formulaire lit l'URL ; les deux sont acceptes.
    courrierId: int | None = None
    courrierReference: str = ""
    type: str
    objet: str
    demandeur: str
    echeance: str = ""
    contexte: str = ""
    criticite: str = "Standard"
    montant: int | None = None


class SaisieComplement(Schema):
    objet: str
    echeance: str


class SaisieRetour(Schema):
    etapeCible: str
    #: Obligatoire — RF-BPM-06. La longueur minimale est verifiee au service :
    #: un motif de trois lettres respecte le contrat et ne dit rien.
    motif: str


class SaisieFusion(Schema):
    modeleId: int
    valeurs: dict[str, str] = {}


class Creation(Schema):
    id: int


class CourrierFusionne(Schema):
    id: int
    #: Le texte produit. Il n'est pas stocke : l'ecran en fait ce que l'agent
    #: decide, et un document de plus dont personne ne dit s'il est un projet
    #: ou un envoi n'aide personne.
    texte: str
    modele: str

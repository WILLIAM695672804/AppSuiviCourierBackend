"""
Contrat de l'ecran de parametrage.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/parametrage/api.ts`.

Les champs de comptage — `usage`, `declenchements`, `nombreCourriers`,
`respect90j`, `documents`, `declenchements30j` — sont declares et valent zero :
ils comptent des courriers, et le pilier courrier n'existe pas. Les retirer du
contrat aurait oblige a reprendre le front le jour ou ils s'alimentent.
"""

from datetime import datetime

from ninja import Schema


class ModeleCircuit(Schema):
    id: int
    libelle: str
    #: Phrase construite depuis les regles de selection, jamais saisie : un
    #: libelle a la main cesserait d'etre juste des la premiere regle ajoutee.
    sappliqueA: str
    nombreEtapes: int
    delaiCible: int
    usage: int
    actif: bool


class EtapeCircuit(Schema):
    id: int
    circuitId: int
    rang: int
    libelle: str
    acteur: str
    delaiJours: int
    escalade: str
    alerteAvant: int | None
    bloquante: bool


class RegleSelection(Schema):
    id: int
    #: Rang d'evaluation, recalcule a chaque lecture : la premiere regle qui
    #: correspond gagne, et l'ordre affiche doit etre l'ordre reel.
    ordre: int
    condition: str
    circuit: str
    declenchements: int
    repli: bool


class MentionCotation(Schema):
    id: int
    libelle: str
    delaiAssocie: int | None
    comportement: str
    niveauxAutorises: list[str]
    active: bool


class CorrespondantAdmin(Schema):
    id: int
    libelle: str
    categorie: str
    ville: str
    nombreCourriers: int
    #: Soupcon, jamais une fusion : deux directions departementales du meme
    #: ministere portent legitimement le meme nom normalise.
    doublonPresume: bool


class Engagement(Schema):
    id: int
    libelle: str
    delaiCible: int
    premiereAlerte: int
    respect90j: int


class RubriqueClassement(Schema):
    id: int
    code: str
    libelle: str
    #: Profondeur dans l'arbre, calculee au serveur. 0 pour les rubriques de tete.
    niveau: int
    parentId: int | None
    documents: int
    typologiesAssociees: list[str]


class SeuilAlerte(Schema):
    id: int
    indicateur: str
    perimetre: str
    operateur: str
    valeur: float
    unite: str
    destinataire: str
    canal: str
    actif: bool
    declenchements30j: int


class RegleMetier(Schema):
    """
    Une ligne de la table `parametre` — zone H.

    A ne pas confondre avec `RegleSelection`, qui choisit un circuit d'apres le
    type d'un courrier. Celle-ci est une **regle de gestion** : un delai, un
    seuil, un plafond. Les deux s'appellent « regle » dans la bouche du metier,
    d'ou les deux onglets et les deux noms.

    `estHypothese` double `statut` volontairement : c'est la seule information
    que l'ecran doit rendre impossible a manquer, et un test sur la valeur d'une
    chaine se trompe en silence.
    """

    cle: str
    libelle: str
    valeur: str
    #: `entier`, `decimal`, `texte` ou `booleen`. Commande le controle de saisie
    #: au serveur, et le type de champ a l'ecran.
    typeValeur: str
    domaine: str
    statut: str
    #: Vrai tant que la regle est une invention de la conception.
    estHypothese: bool
    #: La reference de l'arbitrage. Obligatoire pour un acte, vide pour une
    #: hypothese — c'est exactement ce qui les distingue.
    source: str | None
    #: Qui doit trancher. Efface au moment ou l'arbitrage tombe.
    aTrancherPar: str | None
    modifieLe: datetime | None


class SaisieRegleMetier(Schema):
    """
    Change la valeur sans toucher au statut.

    `source` est facultatif pour une hypothese, exige pour un acte : le service
    refuse la modification d'une regle arbitree qui ne cite pas la decision qui
    la change.
    """

    valeur: str
    source: str | None = None


class SaisieArbitrage(Schema):
    """
    Fait passer une hypothese au rang d'acte.

    `source` n'a pas de valeur par defaut, et ce n'est pas un oubli : sans
    reference documentaire, l'arbitrage remplace une invention par une autre en
    lui donnant l'etiquette d'une decision.

    `valeur` est facultatif — le metier confirme souvent l'hypothese telle
    quelle.
    """

    source: str
    valeur: str | None = None


class DonneesParametrage(Schema):
    circuits: list[ModeleCircuit]
    etapes: list[EtapeCircuit]
    regles: list[RegleSelection]
    mentions: list[MentionCotation]
    correspondants: list[CorrespondantAdmin]
    engagements: list[Engagement]
    classement: list[RubriqueClassement]
    seuils: list[SeuilAlerte]
    #: Neuvieme onglet — les regles de gestion parametrables. Servies dans le
    #: meme appel que les huit referentiels, pour la raison ecrite en tete
    #: d'`api.py`.
    reglesMetier: list[RegleMetier]

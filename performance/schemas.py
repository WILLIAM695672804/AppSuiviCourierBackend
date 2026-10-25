"""
Contrat des ecrans de performance — §2 et §3.3.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/performance/api.ts`.

Deux points de vigilance, parce qu'ils portent des chiffres qu'on lit sans
verifier :

 1. `note` sort a **zero** quand le critere n'est pas mesurable, mais son `feu`
    sort a « inconnu ». C'est le feu qui porte l'information : le front affiche
    « non mesuré » sur un feu inconnu, jamais « 0 % ». Rendre `note: null`
    aurait oblige le front a garder deux formes pour un meme champ.
 2. `provisoire` n'est pas decoratif. Un classement de mois en cours n'est pas
    comparable d'une structure a l'autre, et l'ecran doit le dire.
"""

from ninja import Schema

# =====================================================================
#  Matrice et classement
# =====================================================================


class Periode(Schema):
    """La periode observee. `rang` est le mois, la granularite est toujours
    mensuelle : le §2 dit « sur une base mensuelle »."""

    granularite: str
    annee: int
    rang: int


class Compteur(Schema):
    libelle: str
    valeur: float
    note: str
    feu: str


class CritereScore(Schema):
    code: str
    libelle: str
    #: Part dans le score global, en pourcentage. Administre par la DSR, jamais
    #: ecrit dans le code — un directeur peut contester une ponderation, il ne
    #: peut pas contester une constante qu'il ne voit pas.
    poids: int
    note: float
    feu: str


class LigneClassement(Schema):
    rang: int
    #: `null` quand la structure n'etait pas classee le mois precedent : une
    #: fleche verte depuis un rang imaginaire ne se lit pas.
    rangPrecedent: int | None
    structureSigle: str
    structureLibelle: str
    scoreGlobal: float
    feu: str
    criteres: list[CritereScore]


class Matrice(Schema):
    periode: Periode
    provisoire: bool
    lignes: list[LigneClassement]
    compteurs: list[Compteur]
    moyenneInstitution: float


class SousIndicateur(Schema):
    """Ce qui compose une note. C'est ici que le score devient discutable —
    et un score indiscutable ne se corrige jamais."""

    libelle: str
    valeur: str
    cible: str
    taux: float
    feu: str


class CritereDetaille(CritereScore):
    sousIndicateurs: list[SousIndicateur]


class PointHistorique(Schema):
    periode: str
    score: float


class FicheStructure(Schema):
    structureSigle: str
    structureLibelle: str
    periode: Periode
    rang: int
    rangPrecedent: int | None
    totalStructures: int
    scoreGlobal: float
    scorePrecedent: float | None
    feu: str
    moyenneInstitution: float
    criteres: list[CritereDetaille]
    historique: list[PointHistorique]


# =====================================================================
#  Dictionnaire des indicateurs
# =====================================================================


class IndicateurDictionnaire(Schema):
    id: int
    code: str
    libelle: str
    definition: str
    #: Texte affiche en clair, jamais evalue. Voir `modeles.py::Indicateur`.
    formule: str
    source: str
    periodicite: str
    responsable: str
    unite: str
    seuilVert: int
    seuilOrange: int
    #: Libelle du critere alimente, ou `null`. Le dictionnaire couvre tout le
    #: pilotage ; la matrice n'en retient qu'une part.
    critere: str | None
    actif: bool


class NiveauRisque(Schema):
    niveau: int
    libelle: str
    description: str
    conduite: str
    feu: str


class CritereDictionnaire(Schema):
    """Un axe de la matrice. Le formulaire de creation s'en sert pour proposer
    les criteres existants — une liste ecrite dans le front se serait
    desynchronisee au premier critere ajoute."""

    code: str
    libelle: str
    poids: int


class Dictionnaire(Schema):
    criteres: list[CritereDictionnaire]
    indicateurs: list[IndicateurDictionnaire]
    risques: list[NiveauRisque]


# =====================================================================
#  Calendrier officiel de production
# =====================================================================


class LigneCalendrier(Schema):
    id: int
    production: str
    nature: str
    periodicite: str
    #: Formulation litterale : « le 5 du mois suivant ». Elle est construite au
    #: serveur pour que deux ecrans ne la formulent pas differemment.
    echeance: str
    structuresAttendues: int
    responsable: str
    relanceAutomatique: bool
    joursAvantRelance: int | None
    #: Resultat du **dernier cycle clos**, jamais du cycle en cours : une
    #: production due le 5 du mois prochain n'est pas en retard aujourd'hui.
    recus: int
    feu: str


class Calendrier(Schema):
    lignes: list[LigneCalendrier]
    compteurs: list[Compteur]


# =====================================================================
#  Saisies
# =====================================================================


class SaisieIndicateur(Schema):
    code: str
    libelle: str
    definition: str
    formule: str
    source: str
    #: Libelle (« Mensuelle ») et non code : c'est ce que la liste du front
    #: envoie, et le service traduit.
    periodicite: str
    responsable: str
    unite: str = "%"
    seuilVert: int = 85
    seuilOrange: int = 60
    #: Code ou libelle d'un critere existant. `null` pour un indicateur qui
    #: n'alimente pas la matrice — c'est le cas le plus frequent.
    critere: str | None = None


class SaisieProduction(Schema):
    production: str
    nature: str
    periodicite: str
    #: Formulation litterale saisie par la DSR (« le 5 du mois suivant »). Le
    #: service en extrait le jour d'echeance ; il refuse plutot que de deviner.
    echeance: str
    #: Ni `structuresAttendues` ni `responsable` : la ligne est ouverte pour les
    #: structures **reelles** qui entrent au classement, et le responsable en
    #: decoule. Les accepter aurait laisse croire qu'ils decident de quelque
    #: chose. Voir `services.ajouter_production`.
    relanceAutomatique: bool = True
    joursAvantRelance: int | None = None


class Creation(Schema):
    """Ce que le front attend d'une ecriture : l'identifiant, et rien d'autre.
    Il reinvalide ses requetes derriere."""

    id: int

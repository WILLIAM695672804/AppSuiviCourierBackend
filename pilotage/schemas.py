"""
Contrat des restitutions du pilotage.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/pilotage/apiCockpit.ts`, `features/direction/api.ts` et
`features/comite/api.ts`.

**Le point de vigilance de tout ce fichier tient en un mot : `| None`.** Un taux
qui n'a pas pu etre calcule sort a `null` et jamais a zero. Le front affiche
alors « Non mesuré » ; s'il recevait zero, il afficherait « 0 % », c'est-a-dire
un echec la ou il n'y a qu'une absence de mesure. C'est l'ADR 011, et c'est la
raison pour laquelle plusieurs champs que le front typait `number` sont ici
`float | None` : le contrat precedent ne savait pas dire « je ne sais pas ».

La regle ne vaut pas pour les **comptages**. « Zero décision en retard » est une
mesure ; `decisionsEnRetard` est donc un `int` sans nullable, et le restera.
"""

from ninja import Schema

# =====================================================================
#  Le cockpit executif — niveau 1
# =====================================================================


class Alerte(Schema):
    id: int
    criticite: str
    libelle: str
    precision: str
    #: Ou aller pour agir. `null` quand l'ecran n'existe pas encore : un lien
    #: mort coute plus cher qu'une ligne sans lien.
    chemin: str | None = None
    structure: str | None = None


class EngagementDG(Schema):
    id: int
    reference: str
    objet: str
    origine: str
    echeance: str | None = None
    avancement: float
    feu: str
    enRetard: bool


class IndicateurCockpit(Schema):
    libelle: str
    #: Deja formatee par le serveur — « 62 % », « Non mesuré ». Le front ne
    #: recompose rien : la mise en forme d'une mesure absente est une decision
    #: metier, pas une decision d'affichage.
    valeur: str
    variation: str | None = None
    favorable: bool | None = None


class Extreme(Schema):
    sigle: str
    score: float
    feu: str


class Cockpit(Schema):
    periode: str
    executionActivites: float
    decisionsEnRetard: int
    structuresARisque: int
    absencesSansInterim: int
    activitesCritiques: int
    alertes: list[Alerte]
    engagements: list[EngagementDG]
    indicateurs: list[IndicateurCockpit]
    meilleures: list[Extreme]
    fragiles: list[Extreme]


# =====================================================================
#  Le tableau de bord d'une structure — niveaux 2 et 3
# =====================================================================


class BlocTableauStructure(Schema):
    libelle: str
    valeur: str
    note: str
    feu: str


class StructureAccessible(Schema):
    sigle: str
    libelle: str


class LigneATraiter(Schema):
    libelle: str
    precision: str
    feu: str
    chemin: str | None = None


class TableauStructure(Schema):
    structureSigle: str
    structureLibelle: str
    structuresAccessibles: list[StructureAccessible]
    periode: str
    #: `null` quand la structure n'est pas classee : toutes ne le sont pas.
    rang: int | None = None
    totalStructures: int
    scoreGlobal: float | None = None
    feu: str
    activites: list[BlocTableauStructure]
    courrier: list[BlocTableauStructure]
    rituels: list[BlocTableauStructure]
    aTraiter: list[LigneATraiter]


# =====================================================================
#  Le tableau de bord et ses trois perimetres
# =====================================================================


class IndicateurTableau(Schema):
    libelle: str
    valeur: str
    variation: str | None = None
    note: str
    feu: str


class PointSerie(Schema):
    periode: str
    attendues: int
    deposees: int
    decisionsExecutees: int


class LigneRetard(Schema):
    id: int
    reference: str
    objet: str
    structure: str
    etape: str
    retardJours: int
    chemin: str | None = None


class MesureAbsente(Schema):
    """Ce que l'ecran ne mesure pas, et pourquoi — ADR 011."""

    libelle: str
    raison: str


class TableauDeBord(Schema):
    #: Ce que le front a demande, et ce que le serveur a applique. Les deux
    #: sortent : l'ecran doit pouvoir dire « vous voyez votre structure » a qui
    #: a demande l'institution sans y avoir droit.
    perimetreDemande: str
    perimetreApplique: str
    perimetreLibelle: str
    periode: str
    indicateurs: list[IndicateurTableau]
    serie: list[PointSerie]
    retards: list[LigneRetard]
    tauxRespect: float | None = None
    objectifRespect: int
    nonMesure: list[MesureAbsente]


# =====================================================================
#  Statistiques annuelles
# =====================================================================


class IndicateurStatistique(Schema):
    libelle: str
    valeur: str
    note: str
    feu: str


class MoisStatistique(Schema):
    mois: str
    attendues: int
    deposees: int
    decisionsExecutees: int


class StructureStatistique(Schema):
    structure: str
    sigle: str
    volume: int
    ecartMoyen: float | None = None
    respect: float | None = None
    feu: str


class Statistiques(Schema):
    annee: int
    seuilAttendu: int
    indicateurs: list[IndicateurStatistique]
    parMois: list[MoisStatistique]
    parStructure: list[StructureStatistique]
    nonMesure: list[MesureAbsente]


# =====================================================================
#  Analyses croisees
# =====================================================================


class LigneCroisee(Schema):
    sigle: str
    libelle: str
    #: Les quatre mesures du §3.11. Deux d'entre elles sortent aujourd'hui a
    #: `null` faute des piliers correspondants : c'est la raison d'etre du
    #: nullable ici, et le nuage de points n'en trace que deux axes.
    activites: float | None = None
    courrier: float | None = None
    dossiers: float | None = None
    delais: float | None = None
    feu: str
    dispersion: float


class MoyennesCroisees(Schema):
    activites: float | None = None
    courrier: float | None = None
    dossiers: float | None = None
    delais: float | None = None


class Constat(Schema):
    texte: str
    feu: str


class AnalysesCroisees(Schema):
    periode: str
    lignes: list[LigneCroisee]
    moyennes: MoyennesCroisees
    constats: list[Constat]


# =====================================================================
#  Indicateurs cibles du programme
# =====================================================================


class IndicateurProgramme(Schema):
    code: str
    libelle: str
    modeCalcul: str
    source: str
    unite: str
    valeurN: float | None = None
    valeurN1: float | None = None
    #: `null` quand la cible n'a pas ete fixee — voir A32. Le front affiche
    #: « cible non fixée » et non « 0 », qui aurait ete une cible atteinte.
    cible: float | None = None
    cibleMaximum: bool
    echeance: str
    feu: str


class CompteurProgramme(Schema):
    libelle: str
    valeur: int
    note: str
    feu: str


class SuiviProgramme(Schema):
    annee: int
    indicateurs: list[IndicateurProgramme]
    compteurs: list[CompteurProgramme]


# =====================================================================
#  Note de synthese d'instance
# =====================================================================


class LigneClassement(Schema):
    rang: int
    sigle: str
    libelle: str
    score: float
    feu: str


class PointDAttention(Schema):
    titre: str
    texte: str
    feu: str


class SyntheseInstance(Schema):
    instance: str
    seance: str
    dateSeance: str
    producteur: str
    periode: str
    faitsMarquants: list[str]
    executionActivites: float
    decisionsEchues: int
    decisionsExecutees: int
    classement: list[LigneClassement]
    pointsDAttention: list[PointDAttention]


# =====================================================================
#  Les rapports periodiques — D-03
# =====================================================================


class PeriodeRapport(Schema):
    """La periode couverte, bornes comprises. `code` nomme le fichier exporte."""

    granularite: str
    annee: int
    rang: int
    code: str
    libelle: str
    debut: str
    fin: str


class LigneRapport(Schema):
    libelle: str
    valeur: str
    note: str
    feu: str
    #: L'ecart avec la periode precedente, deja formate. `null` des qu'une des
    #: deux mesures manque : une variation contre une absence serait inventee.
    variation: str | None = None


class SectionRapport(Schema):
    titre: str
    lignes: list[LigneRapport]


class Rapport(Schema):
    periode: PeriodeRapport
    #: Vrai quand la periode demandee n'etait pas close et a ete ramenee a la
    #: derniere qui l'est. L'ecran le dit — sinon l'agent croit a un bogue.
    periodeRamenee: bool
    comparaison: str
    perimetre: str
    perimetreLibelle: str
    structureSigle: str
    structuresAccessibles: list[StructureAccessible]
    #: Faux quand la portee ne consolide pas l'institution : le selecteur de
    #: perimetre ne propose alors que la structure.
    peutVoirInstitution: bool
    editeLe: str
    editePar: str
    sections: list[SectionRapport]
    nonMesure: list[MesureAbsente]


# =====================================================================
#  Vues d'ensemble — Direction generale et Comite de direction
# =====================================================================


class Repere(Schema):
    libelle: str
    valeur: str
    note: str | None = None


class SerieMensuelle(Schema):
    mois: str
    valeur: float


class Part(Schema):
    libelle: str
    valeur: float


class CoteChenal(Schema):
    point: str
    cote: float
    garantie: float
    ecart: float
    feu: str
    releveLe: str
    evolution: list[SerieMensuelle]


class SyntheseRecouvrements(Schema):
    periode: str
    tauxGlobal: float
    totalRecouvre: int
    totalExploitation: int
    totalAutresRecettes: int
    parSecteur: list[Part]


class BilanDisponibilite(Schema):
    """Qui est a son poste aujourd'hui, et pourquoi les autres n'y sont pas."""

    aLaDate: str
    effectif: int
    absents: int
    presents: int
    tauxPresence: float
    sansInterim: int
    #: « Presents » en tete, puis un motif d'absence par part.
    parts: list[Part]


class VueEnsembleDirection(Schema):
    institution: str
    actualiseLe: str
    exercice: str
    reperes: list[Repere]
    ecartExecution: list[SerieMensuelle]
    executionParStructure: list[Part]
    retardsParStructure: list[Part]
    respectDelais: list[SerieMensuelle]
    decisionsExecutees: list[SerieMensuelle]
    #: `null` a deux titres : la session ne porte pas `EXP_LEC`, ou rien n'a ete
    #: releve. Un bloc absent ne fuit pas ; un bloc masque a l'affichage, si.
    #: `null` quand la session ne porte pas `DISPO`, ou quand le perimetre ne
    #: rend aucun agent. Meme raisonnement que `chenal`.
    disponibilite: BilanDisponibilite | None = None
    chenal: CoteChenal | None = None
    recouvrements: SyntheseRecouvrements | None = None


class PositionMembre(Schema):
    """La place de la direction du membre au classement du mois."""

    structureSigle: str
    structureLibelle: str
    scoreGlobal: float
    feu: str
    rang: int
    #: `null` au premier mois classe : il n'y a pas de rang d'avant.
    rangPrecedent: int | None = None
    totalStructures: int
    moyenneCollege: float | None = None


class VueEnsembleComite(Schema):
    institution: str
    structureSigle: str | None = None
    actualiseLe: str
    exercice: str
    reperes: list[Repere]
    #: `null` quand le membre ne dirige aucune structure, ou quand la sienne
    #: n'entre pas au classement du mois.
    positionMembre: PositionMembre | None = None
    decisionsParEtat: list[Part]
    activitesParEtat: list[Part]
    evolutionScoreMoyen: list[SerieMensuelle]
    dispersion: list[SerieMensuelle]

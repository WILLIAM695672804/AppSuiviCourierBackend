"""
Formes echangees par le pilier activites.

Miroir de `frontend/src/features/activite/api.ts`. Le front n'est pas encore
branche, mais c'est lui le consommateur : concevoir une autre forme aujourd'hui
reviendrait a la traduire demain, et une traduction est un endroit ou deux
verites s'installent.

Convention posee dans `config/api.py` : **sortie en camelCase**.

**Les libelles sortent en francais lisible**, accents compris : `etat` vaut
« En retard », pas `en_retard`. Le front les affiche tels quels, et le §20
parle d'un tableau de bord lu par le Directeur general. La base, elle, garde ses
codes sans accent. La traduction se fait ici, une seule fois — voir
`services.ETATS_VERS_FRONT`.
"""

from ninja import Schema

# =====================================================================
#  Lecture
# =====================================================================


class StructureAssociee(Schema):
    """Une structure co-responsable d'une activite — ADR 047."""

    sigle: str
    libelle: str


class ActiviteLigne(Schema):
    """Une ligne du registre. Tout ce qui s'affiche sans ouvrir la fiche."""

    id: int
    #: `activite.code`, pose par declencheur — « PAA-DSI-01 ».
    reference: str
    intitule: str
    #: Le libelle **court** de l'axe : c'est lui qui circule, pas le code.
    axe: str
    #: La structure **porteuse** : celle dont le plan tient l'activite.
    structureSigle: str
    structureLibelle: str
    #: Les structures qui en repondent en sus de la porteuse — ADR 047. Elles
    #: voient l'activite et la declarent, sans l'inscrire a leur propre plan.
    structuresAssociees: list[StructureAssociee] = []
    #: Le **point focal**, facultatif : la responsabilite est institutionnelle.
    responsable: str | None
    #: L'identifiant du point focal, en plus de son nom : le nom s'affiche, mais
    #: c'est l'identifiant que le formulaire de modification renvoie (ADR 020).
    #: Sans lui, rouvrir une activite pour la corriger repartait d'un selecteur
    #: vide, et le point focal se perdait a chaque modification.
    responsableId: int | None
    initiales: str | None
    debut: str
    fin: str
    etat: str
    avancement: float
    #: Indicatif seulement : depuis que A2 est tranchee, l'ecart a l'attendu ne
    #: decide plus de l'etat.
    avancementAttendu: float
    feu: str
    tachesFaites: int
    tachesTotal: int
    instructions: int
    #: En retard **et** portant une contrainte echue. Le retard seul ne suffit
    #: pas, sans quoi la moitie du plan serait critique — §20.
    critique: bool


class Compteur(Schema):
    libelle: str
    valeur: int
    note: str
    feu: str


class RegistreActivites(Schema):
    activites: list[ActiviteLigne]
    compteurs: list[Compteur]
    total: int
    #: Les structures presentes dans ce que l'agent voit — pour le filtre.
    #: Ce n'est **pas** une protection : `restreindre()` l'est.
    structures: list[str]


class IndicateurSortie(Schema):
    id: int
    libelle: str
    unite: str
    etatReference: str
    cible: str
    realise: str | None
    #: Part de la cible atteinte. La formule n'est pas arbitree — A4.
    taux: float | None
    releveLe: str | None


class RecalibrageTache(Schema):
    """
    Le desaccord de la DSR sur une tache — ADR 030, descendu a la tache par
    l'ADR 049. Absent tant que la DSR n'a pas contredit la structure.
    """

    valeurDeclaree: float
    valeurRetenue: float
    motif: str
    le: str | None


class TacheSortie(Schema):
    """
    Une tache et sa part de l'activite — ADR 049.

    Toutes les valeurs sont en **points de l'activite** (RG-5) : une tache
    prevue a 30 et declaree a 15 apporte 15 points. `avancementPropre` est la
    seule grandeur exprimee a l'echelle de la tache.
    """

    id: int
    libelle: str
    #: RG-8. `AAAA-MM` : la periode d'une tache se lit au mois.
    moisDebut: str
    moisFin: str
    #: RG-2. Part de l'activite, en points.
    valeurPrevue: float
    #: RG-5, RG-6. Ce que la structure declare, cumulatif, plafonne a la part.
    valeurObtenue: float
    #: Ce qui compte dans l'avancement : le recalibrage s'il y en a un.
    valeurRetenue: float
    #: `valeurRetenue / valeurPrevue x 100`. Affichage seulement : l'activite
    #: additionne des points, jamais des pourcentages de tache.
    avancementPropre: float
    #: La valeur obtenue atteint la part prevue.
    fait: bool
    dateRealisation: str | None
    recalibrage: RecalibrageTache | None = None
    #: **Heritage.** Les taches creees jusqu'au 10/09/2026 portent un agent ;
    #: celles d'aujourd'hui sortent avec la chaine vide, l'application n'en
    #: ecrit plus (ADR 048). Le champ reste pour ne pas effacer de l'ecran ce
    #: que la base garde encore. Aucun ecran ne l'affiche.
    responsable: str


class PieceVie(Schema):
    id: int
    nom: str
    poids: str


class EvenementVie(Schema):
    """
    Une ligne de la fiche de vie — §18.

    Les pieces pendent a l'evenement et non a l'activite : un rapport depose
    sans savoir ce qu'il justifie ne prouve rien.
    """

    id: int
    type: str
    date: str
    auteur: str
    initiales: str
    poste: str
    texte: str
    pieces: list[PieceVie]


class InstructionSortie(Schema):
    id: int
    origine: str
    reference: str | None
    texte: str
    date: str
    auteur: str
    responsable: str
    echeance: str
    levee: bool
    dateLevee: str | None


class SuspensionSortie(Schema):
    motif: str
    reference: str | None
    decidePar: str
    date: str


class Recalibrage(Schema):
    """
    Le desaccord entre le taux declare et le taux retenu — ADR 030.

    Absent de la fiche tant que la DSR n'a pas contredit la structure.

    **Depuis l'ADR 049, c'est une synthese** : la DSR recalibre des taches, et
    le taux retenu de l'activite est la somme de leurs valeurs retenues. Le
    motif et la date sont ceux du dernier recalibrage de tache ; le detail se
    lit tache par tache, dans `TacheSortie.recalibrage`.
    """

    avancementDeclare: float
    avancementRetenu: float
    motif: str
    le: str | None


class ActiviteDetail(ActiviteLigne):
    objectif: str
    etatReferenceGeneral: str
    resultatsAttendus: str
    #: Affiche sans suivi de consommation — decision de cadrage D8.
    budgetValide: float | None
    indicateurs: list[IndicateurSortie]
    taches: list[TacheSortie]
    vie: list[EvenementVie]
    instructionsRattachees: list[InstructionSortie]
    suspension: SuspensionSortie | None
    #: `None` dans le cas ordinaire : il n'y a rien a arbitrer.
    recalibrage: Recalibrage | None = None
    derniereRelance: str | None


class StructureAccessible(Schema):
    sigle: str
    libelle: str


class PlanActionsSortie(Schema):
    annee: int
    structureSigle: str
    structureLibelle: str
    etat: str
    soumisLe: str | None
    valideLe: str | None
    validePar: str | None
    motifRetour: str | None
    activites: list[ActiviteLigne]
    avancementGlobal: float
    budgetTotal: float | None
    structuresAccessibles: list[StructureAccessible]


class PlanResume(Schema):
    structureSigle: str
    structureLibelle: str
    annee: int
    etat: str
    activites: int
    avancementGlobal: float
    budgetTotal: float | None
    soumisLe: str | None


class CorbeillePlans(Schema):
    plans: list[PlanResume]
    compteurs: list[Compteur]


class ObligationSortie(Schema):
    id: int
    intitule: str
    nature: str
    periode: str
    echeance: str
    depose: bool
    dateDepot: str | None
    feu: str
    retardJours: int | None
    structureSigle: str
    ligneCalendrierId: int | None


class RegistreObligations(Schema):
    obligations: list[ObligationSortie]
    compteurs: list[Compteur]
    #: Taux de depot dans les delais sur douze mois.
    ponctualite: float


# =====================================================================
#  Ecriture
# =====================================================================


class Identifiant(Schema):
    """Ce que rend toute ecriture : le front n'attend que `{ id }`."""

    id: int


class SaisieActivite(Schema):
    intitule: str
    axe: str
    objectif: str = ""
    etatReferenceGeneral: str = ""
    resultatsAttendus: str = ""
    #: La periode se saisit au **mois** — `AAAA-MM`. Un plan d'actions annuel
    #: s'ecrit « de mars a decembre » ; le quantieme etait invente. Le serveur
    #: le pose : premier jour du mois pour `debut`, dernier pour `fin`.
    #: `AAAA-MM-JJ` reste accepte, pour les activites deja saisies.
    debut: str
    fin: str
    budgetValide: float | None = None
    #: **Distinct de qui saisit.** Un point focal inscrit les activites de toute
    #: sa direction ; le deduire du compte connecte ferait de lui le responsable
    #: de tout, et rendrait la colonne « responsable » inutilisable.
    #:
    #: L'identifiant et non le nom : le champ etait libre et compare au
    #: `nom_complet` caractere par caractere, ce qui refusait toute abreviation
    #: et ne departageait pas deux homonymes. Voir ADR 020.
    #:
    #: **Facultatif depuis l'ADR 047** : ce qui repond de l'activite, ce sont
    #: les structures. Le point focal reste utile, il n'est plus fondateur.
    responsableId: int | None = None
    #: Les sigles des structures associees, **hors porteuse** — celle-ci vient
    #: du plan et ne se choisit pas. La liste soumise fait foi : ce qui n'y
    #: figure plus est retire (ADR 047).
    structuresAssociees: list[str] = []


class SaisieTache(Schema):
    """
    Une tache, telle qu'elle se saisit — ADR 049.

    **Aucun agent attributaire** (ADR 048) : une tache se rattache a son
    activite, et c'est l'activite qui designe qui en repond. Un
    `responsableId` encore envoye par un front reste en arriere est ignore.

    `id` absent : la tache est a creer. Present : la tache existante est mise a
    jour. Voir `SaisieListeTaches`.
    """

    id: int | None = None
    libelle: str
    #: RG-2. Part de l'activite, en points, au centieme : `0 < x <= 100`.
    valeurPrevue: float
    #: RG-8. `AAAA-MM`. L'annee n'est pas saisie a l'ecran : le selecteur ne
    #: propose que les mois de l'activite (RG-9), et c'est le front qui porte
    #: l'annee avec le mois choisi.
    moisDebut: str
    moisFin: str


class SaisieCreationActivite(SaisieActivite):
    #: RG-1. Au moins une tache, saisies avec l'activite ; RG-3, leurs valeurs
    #: prevues totalisent 100.
    taches: list[SaisieTache]


class SaisieModificationActivite(SaisieActivite):
    #: Alimente la fiche de vie. Une modification sans motif ne s'explique pas
    #: six mois plus tard.
    motif: str


class SaisieIndicateur(Schema):
    libelle: str
    unite: str = ""
    etatReference: str = ""
    cible: str


class SaisieReleve(Schema):
    realise: str


class SaisieListeTaches(Schema):
    """
    La liste des taches d'une activite, **entiere** — ADR 049.

    La liste soumise fait foi, comme pour les structures associees (ADR 047) :
    une tache sans `id` est creee, une tache avec `id` est mise a jour, une
    tache en vigueur absente de la liste est invalidee. C'est la seule forme
    qui permette de controler RG-3 : la somme a 100 ne se verifie pas tache par
    tache, puisque passer de 50/50 a 30/70 fait transiter par 80 ou par 120.

    Remplace l'ajout unitaire (`libelle`, `echeance`, `poids`) : une tache
    ajoutee seule rompait la somme des qu'elle etait creee.
    """

    taches: list[SaisieTache]
    #: Alimente la fiche de vie : redecouper une activite change ce que chaque
    #: declaration a venir voudra dire.
    motif: str


class SaisieAvancement(Schema):
    """
    Ce que le front envoie pour declarer un avancement — **sans piece**.

    Elle portait un champ `pieces: list[{nom, poids}]`, et c'est ce qui a produit
    des lignes de `piece_jointe` sans empreinte ni chemin de stockage : le nom et
    le poids sans le binaire. L'onglet des pieces jointes les listait comme les
    autres, et le clic tombait sur « le fichier est enregistre mais introuvable
    sur le volume », qui accusait l'exploitation d'un fichier n'ayant jamais
    existe.

    Les pieces justificatives d'une declaration passent maintenant par
    `POST /api/pieces` (ADR 017), qui lit le fichier, calcule son empreinte et
    l'ecrit sur le volume. Le lien au geste est porte par l'evenement, via
    `donnees["pieceUid"]`. Voir `docs/pieges.md`.

    **Elle porte sur une tache, jamais sur l'activite** (RG-4, ADR 049).
    L'`avancement` et les `tachesFaites` d'avant sont retires : l'activite est
    une grandeur derivee, et une case cochee n'exprimait qu'un tout ou rien.
    """

    tacheId: int
    #: RG-5. En points de l'activite, `0 <= x <= valeurPrevue` (RG-6).
    #: **Cumulative** : elle remplace la valeur precedente, elle ne s'y ajoute
    #: pas — c'est ainsi que se declarait l'avancement de l'activite.
    valeurObtenue: float
    #: **Obligatoire.** C'est la justification exigee par le §15, celle qui
    #: alimente la fiche de vie et sur laquelle la DSR s'appuie pour
    #: recalibrer. Un avancement sans elle ne se conteste pas — ADR 030.
    observation: str


class SaisieRecalibrage(Schema):
    """
    Ce que la DSR envoie pour retenir, sur une tache, une autre valeur que
    celle declaree — ADR 030, descendu a la tache par l'ADR 049.

    Le recalibrage portait sur l'activite ; il porte desormais sur la tache,
    pour que l'avancement retenu de l'activite reste la somme des valeurs
    retenues de ses taches.

    `valeur` a `None` **leve** le recalibrage : la valeur declaree par la
    structure redevient la valeur retenue. Le motif reste exige dans les deux
    sens — lever un desaccord est une decision autant que le poser.
    """

    tacheId: int
    #: En points de l'activite, `0 <= x <= valeurPrevue`.
    valeur: float | None
    motif: str


class SaisieSuspension(Schema):
    action: str
    motif: str
    reference: str | None = None


class SaisieInstruction(Schema):
    origine: str
    reference: str | None = None
    texte: str
    responsableId: int
    echeance: str


class SaisieLevee(Schema):
    commentaire: str = ""


class SaisieRelance(Schema):
    texte: str


class SaisieDepot(Schema):
    nomFichier: str
    poids: str = ""
    commentaire: str = ""


class SaisieEtatPlan(Schema):
    annee: int
    structureSigle: str
    #: « soumettre » par la structure, « valider » ou « retourner » par le
    #: controle de gestion — jamais par qui a soumis.
    action: str
    motif: str | None = None

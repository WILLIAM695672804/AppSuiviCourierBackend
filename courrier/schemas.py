"""
Formes echangees par le pilier courrier.

Miroir de `frontend/src/types/courrier.ts` et de
`frontend/src/features/courrier/api.ts`. Ces fichiers-la existent depuis les
maquettes et sont consommes par onze ecrans : la forme n'est pas negociable, elle
est deja lue.

Convention posee dans `config/api.py` : **sortie en camelCase**.

**Les vocabulaires ne concordent pas, et c'est ici qu'on les reconcilie.** La
base dit `arrive`, le front dit `ARRIVEE` ; la base a quatre priorites, le front
en a trois. Les tables `*_VERS_FRONT` de `lecture.py` portent la traduction, une
seule fois, comme `gouvernance/lecture.py` le fait pour les instances. Traduire
ailleurs, c'est garantir qu'un jour les deux listes divergeront — et le piege est
sournois : un `str` en face d'un `str` passe toutes les revues de schemas. Voir
`docs/pieges.md`.
"""

from datetime import date, datetime

from ninja import Schema

# =====================================================================
#  Registre
# =====================================================================


class DelaiCourrier(Schema):
    """
    Consommation du delai, calculee par le serveur.

    **Le client ne compte pas les jours ouvres** : c'est une regle metier, elle
    depend du calendrier des jours feries, et deux implementations donneraient
    deux echeances pour le meme courrier.
    """

    joursEcoules: int
    joursAlloues: int
    #: Jours au-dela de l'echeance. `0` tant que le delai est tenu — jamais
    #: negatif : « moins trois jours de depassement » ne veut rien dire, et le
    #: front lit `> 0` pour decider du rouge.
    joursDepassement: int


class CourrierResume(Schema):
    """Une ligne du registre."""

    id: int
    numero: str
    #: `ARRIVEE`, `DEPART` ou `INTERNE`. La base ecrit `arrive` — voir
    #: `SENS_VERS_FRONT`.
    sens: str
    objet: str
    #: Le libelle fige de l'expediteur, tel qu'il figurait a l'arrivee, et non
    #: celui du referentiel aujourd'hui. Voir `Courrier.expediteur_libelle`.
    correspondant: str
    nature: str
    dateReception: date
    #: `ENREGISTRE`, `COTE`, `AFFECTE`… **Deduite, jamais stockee** — voir
    #: `lecture.etape()`.
    etape: str
    #: `NORMALE`, `URGENTE` ou `TRES_URGENTE`.
    priorite: str
    confidentiel: bool
    echeance: date | None
    #: `None` quand aucun delai n'a ete fixe : le front affiche alors une jauge
    #: vide plutot qu'un delai a zero, qui se lirait « echu ».
    delai: DelaiCourrier | None
    #: Les sigles des structures cotees, **dans l'ordre des rangs**. Le premier
    #: est le chef de file, et le front s'appuie dessus (`chefDeFile()`).
    structuresCotees: list[str]


class PageCourriers(Schema):
    """
    Une page du registre.

    `total` et `totalRegistre` ne sont pas redondants : le premier compte ce que
    le filtre retient et sert la pagination, le second compte le registre entier
    et sert le titre de l'ecran. Les confondre ferait dire « 12 courriers » a un
    registre qui en contient huit cents.
    """

    lignes: list[CourrierResume]
    total: int
    totalRegistre: int
    page: int
    taillePage: int


class MesureIndicateur(Schema):
    """
    Un indicateur du bandeau du registre.

    `variation` est un texte et non un nombre : le front l'affiche tel quel, et
    « Non mesuré » y est une valeur legitime. C'est l'ADR 011 — le pilotage nomme
    ce qu'il ne mesure pas — applique a un bandeau.
    """

    valeur: int | str
    variation: str
    #: Douze points, du plus ancien au plus recent. Vide quand la serie n'a pas
    #: de source : une courbe plate inventee se lit comme une mesure.
    serie: list[int]


class IndicateursRegistre(Schema):
    """Les quatre indicateurs du registre — A-02."""

    arrivesAujourdHui: MesureIndicateur
    enAttenteCotation: MesureIndicateur
    delaiMoyenCotation: MesureIndicateur
    horsDelai: MesureIndicateur


# =====================================================================
#  Fiche
# =====================================================================


class AgentNomme(Schema):
    """Un agent cite sur la fiche. Deux champs : on le nomme, on ne le joint pas."""

    id: int
    nomComplet: str


class StructureCotee(Schema):
    """Une structure visee par une cotation, avec son rang."""

    structureId: int
    libelle: str
    rang: int
    #: `rang == 1`. Le chef de file coordonne et centralise la reponse.
    chefDeFile: bool


class CotationLue(Schema):
    """
    Une cotation, telle que la fiche l'affiche.

    `decidePar` et `saisiPar` sont **tous deux** rendus, meme quand ils sont
    egaux : l'ecran doit pouvoir dire « saisi par X pour le Directeur general »,
    et un seul champ aurait attribue la decision a l'agent qui l'a tapee.
    """

    id: int
    mention: str | None
    annotation: str | None
    delaiFixe: date | None
    decidePar: AgentNomme
    decideLe: datetime
    saisiPar: AgentNomme
    saisiLe: datetime
    structures: list[StructureCotee]


class EtapeChronologie(Schema):
    """
    Une etape franchie du circuit, construite depuis le journal.

    **Aucune etape `attendue` n'est rendue aujourd'hui.** Les etapes a venir se
    lisent dans `circuit_etape`, qui est vide : le trajet reel d'un courrier n'a
    jamais ete communique (A24). Fabriquer une suite plausible aurait affiche a
    l'agent un chemin que rien ne fera suivre.
    """

    id: int
    libelle: str
    horodatage: datetime
    #: `None` pour les etapes automatiques — un traitement de nuit n'a pas d'auteur.
    auteur: str | None
    precision: str | None
    #: La consigne portee a cette etape, citee telle quelle.
    instruction: str | None
    #: `faite` ou `courante`. `attendue` n'est jamais emis — voir la docstring.
    etat: str


class Observation(Schema):
    """Une observation portee au fil de discussion du courrier."""

    id: int
    auteur: str
    initiales: str
    fonction: str
    horodatage: datetime
    texte: str


class PieceJointeLue(Schema):
    """Une piece rattachee au courrier."""

    id: int
    nom: str
    #: « PDF », « JPG »… affiche dans la pastille.
    format: str
    #: Deja formatee — « 1,2 Mo ». Le serveur la met en forme parce que le
    #: separateur decimal francais est une regle de presentation, pas de calcul.
    taille: str
    precision: str | None


class ReponseRattachee(Schema):
    """Un courrier de depart rattache a celui-ci."""

    id: int
    numero: str
    objet: str
    version: int
    redigePar: str
    etape: str


class EvenementCourrier(Schema):
    """Une ligne du journal, reduite a ce que la fiche affiche."""

    id: int
    libelle: str
    horodatage: datetime


class MonAffectation(Schema):
    """
    Ce que le lecteur de la fiche a recu, et s'il l'a decharge.

    `accepteLe` a `None` veut dire « le pli m'est attribue, je n'ai pas signe » :
    c'est le seul etat ou le bouton de decharge s'affiche.
    """

    id: int
    affecteLe: datetime
    consigne: str | None
    accepteLe: datetime | None


class TraitementLu(Schema):
    """
    Ce qu'un agent a ecrit du courrier, et ou en est ce texte.

    `statut` porte le code du socle (`brouillon`, `soumis`, `retourne`,
    `valide`), `statutLibelle` la phrase que l'ecran affiche. Les deux, parce
    que le front filtre sur le code et affiche le libelle : traduire cote front
    aurait pose un second vocabulaire a maintenir.
    """

    id: int
    redacteur: str
    redacteurId: int
    structure: str
    version: int
    contenu: str
    statut: str
    statutLibelle: str
    #: L'heure de la restitution au responsable. `None` tant que le texte est
    #: un brouillon — c'est ce qui distingue « en cours » de « rendu ».
    restitueLe: datetime | None
    modifieLe: datetime


class SaisieTraitement(Schema):
    """Le texte du traitement. Un seul champ : l'ecran n'offre pas d'editeur
    riche, et le contenu est enregistre en clair (`contenu_format = 'texte'`)."""

    contenu: str


class SaisieRetourTraitement(Schema):
    """Le motif du retour a l'agent. Obligatoire — voir `services.retourner`."""

    motif: str


class SaisieCloture(Schema):
    """
    La cloture du courrier par le responsable de structure.

    `malgreLesBrouillons` est un **second clic**, pas une option : le premier
    appel refuse quand un agent ecrit encore, en nommant qui, et le responsable
    confirme en connaissance de cause.
    """

    observation: str | None = None
    malgreLesBrouillons: bool = False


class SignalementLu(Schema):
    """Un ecart constate sur le circuit papier — A-12."""

    id: int
    courrierId: int
    reference: str
    #: Le libelle du type, deja traduit. `typeCode` porte le code.
    type: str
    typeCode: str
    gravite: str
    detail: str
    destinataire: str
    emisPar: str
    emisLe: datetime
    #: « Ouvert », « Pris en compte », « Clos ». `etatCode` porte le code.
    etat: str
    etatCode: str
    suiteDonnee: str | None
    #: Calcule par le serveur : seule la structure visee fait avancer l'ecart.
    #: Le front n'a pas a rejouer la regle, et ne peut pas la contourner.
    peutAvancer: bool


class LigneDecharge(Schema):
    """
    Une ligne du cahier de decharge — A-11.

    L'`etat` est **deduit** a la lecture (« Signé », « En attente », « Non
    retourné ») : une colonne aurait cesse d'etre vraie le lendemain, faute d'un
    traitement de nuit pour la reecrire.
    """

    id: int
    courrierId: int
    reference: str
    objet: str
    destinataire: str
    structure: str
    remise: str
    #: Le coursier, quand la structure le note. « — » sinon.
    coursier: str
    recepteur: str
    decharge: str
    etat: str


class SaisieObservation(Schema):
    """Une observation portee au fil. Ni titre ni destinataire : c'est un fil."""

    texte: str


class SaisieDecharge(Schema):
    """
    La signature du cahier.

    Les deux champs sont facultatifs : un pli remis en main propre n'a pas de
    coursier, et une structure qui a cesse de tenir le cahier papier ne doit pas
    etre empechee d'accuser a l'ecran.
    """

    remisPar: str | None = None
    referenceCahier: str | None = None


class SaisieSignalement(Schema):
    """L'ouverture d'un ecart — A-12."""

    type: str
    description: str
    gravite: str = "NOTABLE"
    #: La structure qui devra le traiter. L'emetteur la choisit.
    destinataireStructureId: int


class SaisieAvancementSignalement(Schema):
    """
    Le passage a l'etat suivant.

    `etat` est ce que l'ecran **croit** atteindre. Le serveur le compare a l'etat
    reellement suivant et refuse s'ils different : deux agents qui ouvrent le
    meme signalement voient tous deux « prendre en compte », et le second ne doit
    pas clore sans l'avoir voulu.
    """

    etat: str | None = None
    #: Obligatoire a la cloture. Un ecart clos sans un mot ne se relit pas.
    suiteDonnee: str | None = None


class CourrierDetail(CourrierResume):
    """
    La fiche complete d'un courrier — A-03.

    Herite de `CourrierResume` : le front le fait aussi (`interface CourrierDetail
    extends CourrierResume`), et diverger aurait produit deux formes du meme
    courrier selon l'ecran qui le demande.
    """

    sessionLibelle: str
    referenceExpediteur: str | None
    enregistrePar: str
    nombrePages: int
    nombreAnnexes: int
    delaiJours: int
    #: `CASCADE` ou `PARALLELE`. **Toujours `None` aujourd'hui** : le mode se lit
    #: sur la version de circuit figee au courrier, et aucun circuit ne se
    #: deroule faute d'etapes (A24). Voir `lecture.mode_cotation()`.
    modeCotation: str | None
    cotations: list[CotationLue]
    chronologie: list[EtapeChronologie]
    observations: list[Observation]
    #: L'affectation de **celui qui lit**, s'il en a une — c'est ce qui fait
    #: apparaitre « J'ai reçu ce courrier » a la bonne personne et a elle seule.
    #: `None` pour tous les autres.
    monAffectation: MonAffectation | None
    #: Le traitement de **celui qui lit**, s'il en a ouvert un : c'est ce que
    #: l'ecran de redaction recharge dans sa zone de saisie.
    monTraitement: TraitementLu | None
    #: Les traitements des autres, cloisonnes comme les gestes internes
    #: (ADR 032). Un brouillon n'y figure jamais : seul son auteur le voit.
    traitements: list[TraitementLu]
    #: Les ecarts signales sur ce courrier, reduits a ceux que ce lecteur a le
    #: droit de suivre — il les a emis, ou sa structure est visee.
    signalements: list[SignalementLu]
    piecesJointes: list[PieceJointeLue]
    reponses: list[ReponseRattachee]
    #: Les trois derniers evenements ; le journal complet est dans la tracabilite.
    derniersEvenements: list[EvenementCourrier]
    #: Ce que **cet** agent peut faire sur **ce** courrier, calcule par le
    #: serveur : le front croise cette liste avec ses propres regles d'etape et
    #: de permission, et n'affiche que l'intersection. Le serveur reste seul juge.
    actionsPossibles: list[str]


# =====================================================================
#  Enregistrement
# =====================================================================


class ContexteEnregistrement(Schema):
    """
    Ce que le serveur sait avant que l'agent saisisse.

    Le client ne fabrique ni le numero ni l'horodatage : l'horloge d'un poste
    derive, et un numero calcule cote client serait un numero en double.
    """

    #: Le numero qui sera **probablement** attribue. Probablement, parce qu'entre
    #: cette lecture et l'insertion un autre agent peut enregistrer : le numero
    #: definitif est celui que le declencheur compose. Le champ s'appelle
    #: `numeroPrevu` pour cette raison.
    numeroPrevu: str
    dateArrivee: datetime
    #: Le registre dans lequel l'agent enregistre. Il n'en a qu'un : le
    #: rattachement est exclusif, garanti par le moteur.
    sessionLibelle: str


class SaisieEnregistrement(Schema):
    """
    Ce que l'ecran A-01 envoie.

    Miroir de `frontend/src/features/courrier/schemaEnregistrement.ts`. Les
    controles du front doublent ceux du serveur, ils ne les remplacent pas.
    """

    #: `ARRIVE`, `INTERNE` ou `CONFIDENTIEL` — le registre visé. Le serveur
    #: verifie que l'agent y est rattache : on n'ecrit pas dans le cahier d'un
    #: autre service.
    typeSession: str
    natureId: int
    correspondantId: int
    referenceExpediteur: str = ""
    #: La date portee sur la lettre. Vide quand la piece n'en porte pas — le
    #: serveur retient alors la date de reception.
    dateLettre: str = ""
    nombrePages: int = 1
    objet: str
    #: En **jours ouvres**. Le serveur en tire `date_limite`.
    delaiJours: int = 5
    urgent: bool = False
    reponseAttendue: bool = False
    #: Suites immediates de l'ecran. Aucune des deux n'entre en base :
    #: `coterMaintenant` ouvre la fenetre de cotation cote client, et
    #: `structureDestinataireId` l'y pre-remplit. Acceptees pour que le
    #: formulaire ne soit pas refuse en 422 sur des champs qu'il envoie ;
    #: consignees au journal, qui dit ce que l'agent a demande.
    #:
    #: `inscrireBordereau`, `imprimerEtiquette` et `envoyerAccuse` ont ete
    #: retires le 19 aout 2026 : trois cases cochees par defaut, envoyees, et
    #: ignorees, pour trois gestes qui n'existent pas.
    coterMaintenant: bool = False
    structureDestinataireId: int | None = None


# =====================================================================
#  Cotation et affectation
# =====================================================================


class SaisieCotation(Schema):
    """
    Une cotation a enregistrer.

    `structureIds` est **ordonne** : la premiere structure est chef de file. Ce
    n'est pas une convention d'affichage — le rang est ecrit en base, le
    declencheur du socle recopie le rang 1 sur le courrier, et le registre trie
    dessus.
    """

    mentionTypeId: int | None = None
    annotation: str = ""
    #: Date ISO, ou vide. Le delai que l'autorite impose, quand il differe de
    #: celui de la nature.
    delaiFixe: str | None = None
    #: Le meme delai, exprime en **jours ouvres** — c'est ce que la fenetre de
    #: cotation propose (3, 5 ou 10 jours). Le serveur le convertit en date :
    #: compter les jours ouvres suppose le calendrier des feries, qui est en
    #: base. Ignore quand `delaiFixe` est donne.
    delaiJours: int | None = None
    #: **L'autorite qui a decide**, distincte de l'agent qui saisit. Le Directeur
    #: general cote, l'agent de session enregistre. Voir `Cotation.decide_par`.
    decideParId: int
    decideLe: str
    structureIds: list[int]
    #: La personne designee au suivi, s'il y en a une. C'est la **seconde**
    #: cotation : elle coordonne au-dessus du chef de file et rend compte au
    #: Directeur general. Facultative — tous les courriers n'en ont pas.
    suiviParId: int | None = None
    motifSuivi: str = ""


class SaisieAffectation(Schema):
    """
    Une affectation a un agent.

    La cotation va vers une structure, l'affectation va vers une personne : deux
    actes distincts. Le serveur verifie que l'agent designe releve bien d'une
    structure cotee — affecter hors cotation reviendrait a contourner la decision
    du DG.
    """

    utilisateurId: int
    #: Le front dit « consigne », la base dit `orientations`. La traduction se
    #: fait ici, une fois.
    consigne: str = ""


class SaisieProlongation(Schema):
    """
    Le report d'une echeance, et sa raison.

    Le motif n'a **pas** de valeur par defaut : un report sans raison ne se
    defend pas devant un controle, et le rendre facultatif au schema aurait
    laisse passer la chaine vide.
    """

    #: Date ISO. Ignore `delaiJours` quand elle est donnee.
    nouvelleEcheance: str | None = None
    #: Les jours **ouvres** accordes, comptes depuis l'echeance en vigueur — pas
    #: depuis aujourd'hui. Voir `services.prolonger`.
    delaiJours: int | None = None
    motif: str


class SaisieCorrection(Schema):
    """
    Une correction de saisie — les champs omis restent inchanges.

    Tout est facultatif, et `None` signifie **« ne touche pas »** : un formulaire
    partiel ne doit pas effacer ce qu'il n'affiche pas. Les mentions du registre
    — numero, session, sens, confidentialite, date de reception — n'y figurent
    pas : voir `services.CHAMPS_CORRIGEABLES`.
    """

    objet: str | None = None
    correspondantId: int | None = None
    natureId: int | None = None
    referenceExpediteur: str | None = None
    dateLettre: str | None = None
    nombrePages: int | None = None
    urgent: bool | None = None
    observations: str | None = None
    #: Facultatif, contrairement a la prolongation : la correction porte deja son
    #: avant et son apres au journal, qui dit ce qui a change sans qu'on
    #: l'explique.
    motif: str = ""


# =====================================================================
#  Fiche de vie — A-06
# =====================================================================


class EtapeVie(Schema):
    """
    Une etape de la fiche de vie.

    Les dates sont **deja formatees** — « 14/08/2026 », « 09:12 ». La fiche de vie
    est une piece qui s'imprime et se joint a un dossier : elle doit sortir du
    serveur telle qu'elle sera lue, et non dependre du fuseau du poste qui
    l'affiche.
    """

    id: int
    heure: str
    date: str
    titre: str
    detail: str
    #: « — » quand l'evenement n'a pas d'acteur : un traitement de nuit n'en a pas.
    acteur: str
    #: Le temps ecoule depuis l'etape precedente. **C'est lui qui revele ou le
    #: courrier a attendu** — une liste d'horodatages laisse ce calcul a l'oeil du
    #: lecteur, et trois jours de silence entre deux lignes ne se remarquent pas.
    marge: str
    #: Faux quand l'etape signale un incident : ecart, relance, retour.
    conforme: bool
    #: Etape qui engage l'institution, conservee par le filtre « Jalons ».
    jalon: bool


class LigneResumeVie(Schema):
    """Un chiffre de l'entete. Le ton dit, sans lire les dates, si le délai est tenu."""

    libelle: str
    valeur: str
    #: `neutre`, `succes` ou `alerte`.
    ton: str


class Detenteur(Schema):
    """
    Un agent qui a tenu le courrier, et combien de temps.

    Les detenteurs sont les agents **affectes**, jamais les structures cotees :
    une structure ne detient pas un dossier, elle le confie a quelqu'un. Dire
    « la DAF a détenu le courrier onze jours » ne permet ni de relancer ni de
    comprendre.
    """

    nom: str
    structure: str
    initiales: str
    duree: str


class CourrierLie(Schema):
    """Un courrier rattache, dans un sens ou dans l'autre."""

    reference: str
    titre: str
    chemin: str


class FicheVie(Schema):
    """La fiche de vie d'un courrier — A-06. Le journal, redige pour etre lu."""

    numero: str
    objet: str
    etapes: list[EtapeVie]
    resume: list[LigneResumeVie]
    detenteurs: list[Detenteur]
    lies: list[CourrierLie]


# =====================================================================
#  Compteurs de la navigation
# =====================================================================


class Compteurs(Schema):
    """
    Les trois pastilles de la barre laterale.

    Chacune compte ce que l'agent qui appelle peut voir : les pastilles d'un
    directeur et celles d'un agent de session ne portent pas les memes nombres.
    Un compteur calcule hors perimetre serait une fuite discrete — le nombre dit
    quelque chose meme quand la liste est fermee.
    """

    courriers: int
    cotations: int
    relances: int


# =====================================================================
#  Bureau d'ordre de structure — A-02b
# =====================================================================


class LignePassage(Schema):
    """
    Une ligne du registre du bureau d'ordre : un courrier, une structure, une
    entree, et — quand ils ont eu lieu — un accuse et une sortie.

    `heuresAvantAccuse` est **nul tant que l'accuse n'est pas pose**, et non
    zero : le compteur court toujours, et l'afficher comme une duree acquise
    aurait fait passer un courrier oublie depuis trois jours pour un courrier
    recu a l'instant.
    """

    id: int
    courrierId: int
    numero: str
    objet: str
    correspondant: str
    nature: str | None = None
    structure: str
    structureId: int
    etape: str
    entreLe: datetime
    accuseLe: datetime | None = None
    accusePar: str | None = None
    sortiLe: datetime | None = None
    sortiPar: str | None = None
    #: `reponse`, `retour`, `transmission`, `cloture` ou `autre`.
    motifSortie: str | None = None
    noteSortie: str | None = None
    joursDansLaStructure: int
    heuresAvantAccuse: int | None = None


class SaisieSortie(Schema):
    """
    La sortie d'un courrier de la structure.

    Le motif n'a **pas** de valeur par defaut, et le CHECK
    `passage_sortie_motivee` le tient aussi en base : une sortie sans motif se
    lirait « le courrier a disparu de nos écrans », alors qu'un registre de
    bureau d'ordre existe precisement pour dire par ou les choses sont parties.
    """

    #: `reponse`, `retour`, `transmission`, `cloture` ou `autre`.
    motif: str
    note: str | None = None


# =====================================================================
#  Supervision des delais — le mapping de la DSR
# =====================================================================


class LigneBlocage(Schema):
    """
    Ou est bloque un courrier, et depuis quand.

    `detenteur` et `structure` coexistent parce que l'exigence demande « le
    responsable exact » et que, dans un cas sur trois, il n'existe pas encore :
    un courrier recu par une structure qui ne l'a pas ouvert n'a **personne**
    pour detenteur, et c'est precisement le blocage a voir.
    """

    courrierId: int
    numero: str
    objet: str
    correspondant: str
    etape: str
    echeance: date | None = None
    joursDepassement: int
    detenteur: str | None = None
    structure: str | None = None
    motif: str
    depuis: datetime
    joursImmobilise: int


class CarteBlocages(Schema):
    """
    Le mapping complet de la DSR — tous les courriers en cours, classes par
    immobilisation decroissante.

    `arreteLe` n'est pas decoratif : la carte se lit et s'imprime, et une liste
    de durees sans le moment ou elles ont ete calculees devient fausse le
    lendemain sans que rien ne le dise.
    """

    lignes: list[LigneBlocage]
    total: int
    arreteLe: datetime
    resume: list[LigneResumeVie]


# =====================================================================
#  Suivi et relance — C-02
# =====================================================================


class LigneRelance(Schema):
    """
    Un dossier en cours, vu par celui qui relance.

    `agent` est nul tant que personne n'est nomme, et ce n'est pas un trou dans
    la donnee : c'est le motif de relance le plus frequent — le courrier est
    arrive quelque part et n'a ete confie a personne.
    """

    id: int
    numero: str
    objet: str
    #: Le sigle de la structure qui detient le dossier, ou « Non cotée ».
    structure: str
    #: **Le directeur a qui la relance s'adresse** — celui de la tete de la
    #: structure chef de file, jamais l'agent nomme. « — » quand aucun poste de
    #: tete n'est pourvu au-dessus d'elle : il n'y a alors personne a relancer.
    interlocuteur: str = "—"
    agent: str | None = None
    delai: DelaiCourrier | None = None
    #: L'emission de la derniere relance. `null` quand il n'y en a jamais eu —
    #: l'ecran ecrit alors « jamais », et non une date par defaut.
    derniereRelance: datetime | None = None
    #: 0 : aucune escalade. 1, 2, 3 : niveaux hierarchiques saisis. Deduit du
    #: nombre de relances emises — hypothese A77.
    niveauEscalade: int


class IndicateursRelance(Schema):
    """
    Les quatre cartes du bandeau de C-02.

    Calculees sur **l'ensemble des dossiers en cours** et non sur l'onglet
    affiche : elles repondent a « ou en est le Port », pas a « que montre cette
    liste ».
    """

    horsDelai: int
    #: Ceux qui depassent de plus de `suivi.retard_grave_jours` — hypothese A76.
    horsDelaiGrave: int
    sous48h: int
    structuresConcernees: int
    relancesMois: int
    escalades: int
    #: Part des courriers clos dans leur delai, en pourcentage entier, sur la
    #: fenetre `suivi.fenetre_taux_respect_jours` — hypothese A78.
    tauxRespect: int


class TableauRelance(Schema):
    lignes: list[LigneRelance]
    indicateurs: IndicateursRelance


# =====================================================================
#  Le dossier de traitement et la recherche avancee — C-01, A-14
# =====================================================================


class Instruction(Schema):
    """
    Ce qu'on demande a l'agent, avec qui le demande.

    L'auteur n'est pas un ornement : « traiter en urgence » n'a pas le meme poids
    selon qu'il vient du chef de service ou du Directeur general, et l'ecran le
    met en tete du dossier pour cette raison.
    """

    texte: str
    auteur: str
    initiales: str
    fonction: str
    horodatage: datetime


class TacheDossier(Schema):
    """
    Une etape que l'agent se donne — **pas** le circuit du courrier.

    Sans poids ni echeance, contrairement a `activite.Tache` : ce n'est pas un
    plan d'actions, c'est une liste de courses, et elle n'engage que son auteur.
    """

    id: int
    libelle: str
    faite: bool
    #: Nulle tant que l'etape reste a faire. Decocher la remet a nul.
    faiteLe: datetime | None = None


class NoteDossier(Schema):
    """
    Une note de travail. Distincte de l'observation, qui est publique par
    arbitrage du Port (26 aout 2026) : une note privee ne se lit que par son
    auteur et sa hierarchie.
    """

    id: int
    texte: str
    horodatage: datetime
    privee: bool


class DossierTraitement(Schema):
    """
    Le courrier vu par celui qui le traite.

    `actionsPossibles` est calcule par le serveur et non deduit par le front :
    un bouton propose puis refuse a l'envoi est la panne la plus commune de cet
    ecran. Vide pour un lecteur non affecte — le responsable regarde le dossier
    de son agent sans pouvoir agir a sa place.
    """

    courrier: CourrierResume
    instruction: Instruction | None = None
    echeance: date | None = None
    delai: DelaiCourrier | None = None
    taches: list[TacheDossier]
    notes: list[NoteDossier]
    #: Les autres dossiers de l'agent, pour passer de l'un a l'autre sans revenir.
    autresDossiers: list[CourrierResume]
    actionsPossibles: list[str]


class PortefeuilleAgent(Schema):
    """
    La corbeille personnelle : ce qui est **affecte** a l'agent, et non ce qu'il
    voit. Un directeur qui lit deux cents courriers en a trois sur les bras.
    """

    dossiers: list[CourrierResume]
    aRendre: int
    horsDelai: int
    #: Parti chez le responsable, donc plus dans les mains de l'agent — mais le
    #: delai, lui, continue de courir.
    enVisa: int


class SaisieTache(Schema):
    libelle: str


class SaisieBasculeTache(Schema):
    faite: bool


class SaisieNote(Schema):
    texte: str
    #: Privee par defaut : le doute profite a la discretion. L'agent qui veut
    #: ecrire a tous decoche, et il le fait sciemment.
    privee: bool = True


class SaisieDemandeDelai(Schema):
    joursDemandes: int
    motif: str


class SaisieDecisionDelai(Schema):
    accordee: bool
    #: Obligatoire au refus : un agent qui se voit refuser un report sans motif
    #: redemande.
    reponse: str = ""


class CriteresRecherche(Schema):
    """
    Les criteres de l'ecran A-14, tels que l'agent les saisit.

    Tout est facultatif, et un critere vide ne filtre pas : un formulaire ou rien
    n'est saisi rend le registre entier, plafonne. C'est la reponse juste a
    « cherche tout ».

    `structureId` et `natureId` sont des **chaines** parce que le front y met la
    valeur d'un `<select>`, et que « aucun choix » y vaut `""`. Les typer en
    entiers aurait fait echouer la requete sur le formulaire vierge.
    """

    motsCles: str = ""
    du: str = ""
    au: str = ""
    sessions: list[str] = []
    statuts: list[str] = []
    structureId: str = ""
    natureId: str = ""
    #: Reçu mais sans effet : l'archivage verse des dossiers et ne pose aucun
    #: drapeau sur la ligne de courrier. Question ouverte A79.
    inclureArchives: bool = False


class ResultatRecherche(Schema):
    lignes: list[CourrierResume]
    #: Le compte **avant** plafonnement : l'agent doit savoir que sa recherche
    #: rend plus que ce qu'il lit.
    total: int


class RechercheEnregistreeLue(Schema):
    id: int
    libelle: str
    #: Recalcule a chaque listing, jamais stocke : une recherche enregistree est
    #: une question, pas une reponse.
    nombre: int
    criteres: dict


class SaisieRechercheEnregistree(Schema):
    libelle: str
    criteres: CriteresRecherche


class SaisieRelance(Schema):
    """
    Un lot de dossiers a relancer, et le mot qui l'accompagne.

    La relance se pratique **par lots** — on relance les quatorze retards du
    lundi matin, pas un dossier a la fois — et le motif vaut pour tout le lot :
    c'est le meme rappel adresse a quatorze personnes.
    """

    identifiants: list[int]
    #: Facultatif. Une relance sans motif dit deja l'essentiel — « ce dossier
    #: dépasse son délai » — et exiger une phrase a chaque lot ferait ecrire
    #: quatorze fois la meme.
    motif: str = ""


class BilanRelance(Schema):
    """
    Ce qui est parti, et ce qui ne pouvait pas partir.

    **Un lot est partiel par nature** : sur quatorze retards, deux seront sans
    detenteur ou hors perimetre. Rendre les ecarts avec leur raison permet a
    l'ecran de le dire ligne par ligne, plutot que de refuser le lot entier et
    laisser l'agent deviner lesquelles.
    """

    emises: int
    destinataires: list[str]
    ecartes: list[str]

"""
Le pilier courrier — §3.4 a §3.6, §10, §23.

**Les tables existent depuis le premier jour.** `sql/0001_socle.sql` les a
creees avec le reste du schema : `courrier`, `cotation`, `cotation_structure`,
`affectation`, `traitement`, `transmission`, `relance`, et les deux tables du
circuit. Ce qui manquait, c'est l'etat Django qui les decrit — d'ou la migration
`0001_initial` de cette application, qui n'en cree aucune et se contente de les
declarer (`SeparateDatabaseAndState`), comme `noyau/0001_initial` l'a fait pour
le socle. Voir l'[ADR 003].

Quatre invariants du schema que le code ne doit pas contredire :

 1. **Le numero est attribue par le moteur, jamais par Python.** Le declencheur
    `courrier_numero` (BEFORE INSERT) lit `sequence_numerotation`, l'incremente
    sous verrou de ligne et compose `0001/2026`. Deux agents qui enregistrent en
    meme temps ne peuvent donc pas obtenir le meme numero. Le service insere
    `numero=""` et **relit** la ligne : predire le numero cote Python serait le
    seul moyen de le dupliquer.

 2. **Le numero est unique par SESSION, pas globalement.** Chaque session
    d'enregistrement — arrivee, interne, confidentielle — tient son propre
    registre, comme trois cahiers papier distincts. `0001/2026` peut donc exister
    trois fois.

 3. **`decide_par` n'est pas `saisi_par`.** Le Directeur general cote, l'agent
    de session enregistre. Une colonne unique attribuerait a l'agent une
    decision qu'il n'a pas prise, ce qui vide le journal de sa valeur probante.
    Meme distinction sur `cotation_suivi.designe_par`.

 4. **`courrier` et `cotation` sont historisees au niveau du moteur.** Le
    declencheur `historiser_champs()` **refuse** l'ecriture quand
    `app.utilisateur_id` n'est pas pose. Toute ecriture de `services.py` passe
    donc par `noyau.journal.contexte.acteur()`.

Ce qui n'est pas ici, et pourquoi :

 * *pas de colonne ni de modele « etape ».* Les neuf etapes que le front affiche
   (`ENREGISTRE`, `COTE`, `AFFECTE`…) se **deduisent** de l'existence d'une
   cotation, d'une affectation, d'un traitement et de `statut_courrier`. C'est
   l'arbitrage n° 2 du pilier activites, applique ici : stocker un etat qui
   resulte d'un calcul impose de le recalculer partout ou l'une de ses sources
   change, et garantit qu'un jour les deux se contrediront. Voir
   `lecture.etape()`.
 * *pas de table d'evenements du courrier.* La fiche de vie se lit dans
   `evenement`, filtre sur `courrier_id`. ADR 012.
 * *pas de modele pour `instance_circuit`, `instance_etape` ni `validation`.*
   Ces trois tables sont ancrees sur `circuit_etape`, qui est **vide** : le
   trajet reel d'un courrier n'a jamais ete communique (A24). Les declarer
   maintenant reviendrait a promettre un acheminement que rien ne peut derouler.
 * *pas de `chef_de_file` sur `CotationStructure`.* La colonne existe en base,
   mais elle est `GENERATED ALWAYS AS (rang = 1) STORED` : PostgreSQL refuse
   toute insertion explicite, et l'ORM insere toutes les colonnes qu'il connait.
   Elle est donc absente du modele et lue comme `rang == 1`, ce qu'elle vaut.

[ADR 003]: ../backend/docs/architecture/003-django-proprietaire-du-schema.md
"""

import uuid

from django.contrib.postgres.search import SearchVectorField
from django.db import models

from noyau.identite.modeles import SessionCourrier, Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, MentionType, Nature, Priorite

#: Les trois sens d'un courrier. Le sens et la confidentialite sont **deux
#: colonnes distinctes** : un courrier confidentiel entrant est a la fois arrive
#: et confidentiel, et les confondre aurait rendu impossible le registre des
#: arrivees confidentielles.
SENS_ARRIVE = "arrive"
SENS_DEPART = "depart"
SENS_INTERNE = "interne"
SENS = [
    (SENS_ARRIVE, "Arrive"),
    (SENS_DEPART, "Depart"),
    (SENS_INTERNE, "Interne"),
]

#: Le statut du courrier lui-meme. `cloture` et `cloture_le` sont lies par une
#: contrainte du socle : l'un ne va pas sans l'autre.
STATUT_CREE = "cree"
STATUT_EN_COURS = "en_cours"
STATUT_TRAITE = "traite"
STATUT_CLOTURE = "cloture"
STATUTS = [
    (STATUT_CREE, "Cree"),
    (STATUT_EN_COURS, "En cours"),
    (STATUT_TRAITE, "Traite"),
    (STATUT_CLOTURE, "Cloture"),
]

#: L'etat de la reponse attendue, distinct du statut du courrier : un courrier
#: peut etre en cours de traitement sans qu'aucune reponse ne soit engagee.
REPONSE_NON_ENGAGEE = "non_engagee"
REPONSE_EN_COURS = "en_cours"
REPONSE_EN_SIGNATURE = "en_signature"
REPONSE_SIGNEE = "signe"
STATUTS_REPONSE = [
    (REPONSE_NON_ENGAGEE, "Non engagee"),
    (REPONSE_EN_COURS, "En cours"),
    (REPONSE_EN_SIGNATURE, "En signature"),
    (REPONSE_SIGNEE, "Signe"),
]


class Courrier(models.Model):
    """
    Un courrier inscrit au registre.

    `expediteur_libelle` double `expediteur_id` et n'est pas une redondance : le
    referentiel des correspondants evolue — une raison sociale change, une
    entree est corrigee — et le registre doit continuer de dire sous quel nom le
    courrier est arrive. Meme raison que `circuit_version_id` sur une instance de
    circuit : une piece du registre ne se reecrit pas.
    """

    # `default` cote Python et non cote base : Django envoie toujours la colonne
    # dans son INSERT, ce qui court-circuite le DEFAULT gen_random_uuid() du
    # schema et insere NULL. Meme correctif que sur `PieceJointe`.
    uid = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)

    #: `0001/2026`. Vide a l'insertion : le declencheur `courrier_numero` le
    #: compose. Ne jamais le calculer en Python — voir l'invariant 1.
    numero = models.TextField()
    #: Le numero porte par la piece a son origine, quand elle en a un. Sert a
    #: retrouver un courrier que l'expediteur cite par sa propre reference.
    numero_origine = models.TextField(null=True, blank=True)

    sens = models.TextField(choices=SENS)
    confidentiel = models.BooleanField(default=False)

    session = models.ForeignKey(
        SessionCourrier,
        on_delete=models.PROTECT,
        db_column="session_id",
        related_name="courriers",
    )
    nature = models.ForeignKey(
        Nature,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="nature_id",
        related_name="courriers",
    )

    #: La date portee sur la lettre. Distincte de `date_reception` : un courrier
    #: date du 3 peut arriver le 11, et c'est cet ecart qui fait dire a
    #: l'expediteur qu'il attend depuis huit jours.
    date_courrier = models.DateField()
    date_reception = models.DateField()

    expediteur = models.ForeignKey(
        Correspondant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="expediteur_id",
        related_name="courriers_emis",
    )
    #: Le nom sous lequel le courrier est arrive, fige. Voir la docstring.
    expediteur_libelle = models.TextField()
    destinataire = models.ForeignKey(
        Correspondant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="destinataire_id",
        related_name="courriers_recus",
    )
    destinataire_libelle = models.TextField(null=True, blank=True)

    objet = models.TextField()

    #: Denormalise depuis `cotation_structure` de rang 1 par le declencheur
    #: `cotation_structure_chef_file`. **Jamais ecrit par l'application** : le
    #: moteur le tient, et deux ecritures concurrentes de la meme information
    #: finissent toujours par diverger.
    structure_chef_file = models.ForeignKey(
        Structure,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="structure_chef_file_id",
        related_name="courriers_pilotes",
    )

    original_papier_recu = models.BooleanField(default=False)
    observations = models.TextField(null=True, blank=True)

    priorite = models.ForeignKey(
        Priorite,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="priorite_id",
        related_name="courriers",
    )
    nombre_pieces = models.SmallIntegerField(default=0)

    statut_courrier = models.TextField(choices=STATUTS, default=STATUT_CREE)
    statut_reponse = models.TextField(choices=STATUTS_REPONSE, default=REPONSE_NON_ENGAGEE)

    #: Le delai accorde, en jours ouvres. `date_limite` en est la traduction en
    #: date, calculee une fois a l'enregistrement : recalculer une echeance a
    #: chaque lecture la ferait bouger le jour ou un ferie est ajoute au
    #: calendrier, et une echeance qui bouge n'engage personne.
    delai_reglementaire_jours = models.SmallIntegerField(null=True, blank=True)
    date_limite = models.DateField(null=True, blank=True)

    #: Le courrier auquel celui-ci repond, ou qu'il complete.
    courrier_lie = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="courrier_lie_id",
        related_name="courriers_lies",
    )
    date_signature = models.DateField(null=True, blank=True)

    cloture_le = models.DateTimeField(null=True, blank=True)
    cloture_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="cloture_par",
        related_name="courriers_clotures",
    )
    motif_cloture = models.TextField(null=True, blank=True)

    #: Alimentee par le declencheur `courrier_recherche_maj`, jamais par
    #: l'application. Declaree parce que la recherche du registre s'appuie sur
    #: elle et sur son index GIN ; le NULL que Django envoie a l'insertion est
    #: ecrase par le declencheur, qui est BEFORE INSERT OR UPDATE.
    recherche = SearchVectorField(null=True, editable=False)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "courrier"
        ordering = ["-date_reception", "-id"]
        verbose_name = "courrier"
        verbose_name_plural = "courriers"

    def __str__(self) -> str:
        return f"{self.numero} — {self.objet[:60]}"


class Cotation(models.Model):
    """
    L'**acte** de cotation, et non ses destinataires.

    Le Directeur general cote une fois, eventuellement vers plusieurs
    structures : c'est une seule decision, portee par une seule ligne. Les
    structures visees sont dans `CotationStructure`, avec leur rang.

    `niveau_cotation` et `cotation_parente` portent la cascade : le DG cote a une
    direction (niveau 1), qui cote a l'un de ses services (niveau 2). Une
    cotation de niveau 2 sans parente serait une cotation orpheline — le service
    verrait le courrier sans que rien ne dise qui l'a mis la.
    """

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.PROTECT,
        db_column="courrier_id",
        related_name="cotations",
    )
    mention_type = models.ForeignKey(
        MentionType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="mention_type_id",
        related_name="cotations",
    )
    annotation = models.TextField(null=True, blank=True)
    #: Le delai que la cotation fixe elle-meme, quand l'autorite en impose un
    #: autre que celui de la nature.
    delai_fixe = models.DateField(null=True, blank=True)

    #: L'autorite qui cote. **Ne jamais confondre avec `saisi_par`.**
    decide_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="decide_par",
        related_name="cotations_decidees",
    )
    decide_le = models.DateTimeField()
    #: L'agent qui enregistre. Egal a `decide_par` quand le responsable cote
    #: lui-meme.
    saisi_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="saisi_par",
        related_name="cotations_saisies",
    )
    saisi_le = models.DateTimeField(auto_now_add=True)

    niveau_cotation = models.SmallIntegerField(default=1)
    cotation_parente = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="cotation_parente_id",
        related_name="cotations_filles",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "cotation"
        ordering = ["-decide_le", "-id"]
        verbose_name = "cotation"
        verbose_name_plural = "cotations"

    def __str__(self) -> str:
        return f"Cotation du courrier {self.courrier_id} par {self.decide_par_id}"


class CotationStructure(models.Model):
    """
    Une structure visee par une cotation, avec son rang.

    **Le rang 1 est chef de file** : il coordonne les co-traitantes et centralise
    la reponse. C'est la seule signification du rang, et elle n'est pas
    decorative — le registre trie dessus, et le declencheur
    `cotation_structure_chef_file` recopie le rang 1 sur le courrier.

    La colonne `chef_de_file` de la base est generee (`rang = 1`) et absente de
    ce modele : PostgreSQL refuse qu'on l'insere. Voir l'entete du module.
    """

    cotation = models.ForeignKey(
        Cotation,
        on_delete=models.CASCADE,
        db_column="cotation_id",
        related_name="structures",
    )
    structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        db_column="structure_id",
        related_name="cotations_recues",
    )
    rang = models.SmallIntegerField()

    class Meta:
        db_table = "cotation_structure"
        ordering = ["rang"]
        verbose_name = "structure cotee"
        verbose_name_plural = "structures cotees"

    def __str__(self) -> str:
        return f"{self.structure_id} au rang {self.rang}"

    @property
    def chef_de_file(self) -> bool:
        """Ce que vaut la colonne generee du meme nom."""
        return self.rang == 1


class CotationSuivi(models.Model):
    """
    La **seconde** cotation : la personne designee au suivi du courrier.

    Decision client du 11 aout 2026, A7 tranchee. Elle coordonne au-dessus du
    chef de file et rend compte au Directeur general :

        Cotation pour suivi     <- coordonne tout, rend compte au DG
                 ^
          Chef de file          <- coordonne les co-traitantes
        ^        ^       ^
     Struct.  Struct.  Struct.  <- traitent

    **Une personne, jamais une structure.** C'est ce qui la distingue de la
    cotation operationnelle, et aucune colonne `structure_id` n'existe ici : il
    ne faut pas en ajouter.

    **Une table et non une colonne sur `cotation`** : la designation change — un
    agent part, un autre reprend — et une colonne ecraserait. Savoir qui suivait
    le courrier le jour ou une relance est partie est tout l'objet de la table.
    Un index unique partiel garantit une seule designation ouverte a la fois.

    Consequence pratique : **la relance part a la personne de suivi**, pas au
    chef de file.
    """

    cotation = models.ForeignKey(
        Cotation,
        on_delete=models.CASCADE,
        db_column="cotation_id",
        related_name="suivis",
    )
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="utilisateur_id",
        related_name="courriers_suivis",
    )
    motif = models.TextField(null=True, blank=True)

    designe_le = models.DateTimeField(auto_now_add=True)
    #: L'autorite qui designe. Meme distinction que `decide_par` / `saisi_par`.
    designe_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="designe_par",
        related_name="suivis_designes",
    )
    retire_le = models.DateTimeField(null=True, blank=True)
    retire_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="retire_par",
        related_name="suivis_retires",
    )

    class Meta:
        db_table = "cotation_suivi"
        ordering = ["-designe_le"]
        verbose_name = "cotation pour suivi"
        verbose_name_plural = "cotations pour suivi"

    def __str__(self) -> str:
        return f"Suivi du courrier de la cotation {self.cotation_id} par {self.utilisateur_id}"


class Affectation(models.Model):
    """
    L'affectation d'un courrier a un agent, au sein d'une structure cotee.

    **La cotation va vers une STRUCTURE, l'affectation va vers une PERSONNE.**
    Deux actes distincts, deux acteurs distincts : le DG cote a la direction, le
    directeur affecte a l'un de ses agents. C'est pour cela que l'affectation
    pend a `cotation_structure` et non au courrier — elle n'existe pas sans la
    cotation qui l'autorise.

    Comme la designation de suivi, elle se **date** plutot que de s'effacer :
    `retire_le` clot une affectation sans faire disparaitre le fait qu'elle a
    existe.
    """

    cotation_structure = models.ForeignKey(
        CotationStructure,
        on_delete=models.PROTECT,
        db_column="cotation_structure_id",
        related_name="affectations",
    )
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="utilisateur_id",
        related_name="affectations_courrier",
    )
    #: La consigne donnee a l'agent. Le front l'appelle « consigne », la base
    #: « orientations » : la traduction se fait dans les schemas, une seule fois.
    orientations = models.TextField(null=True, blank=True)
    delai_fixe = models.DateField(null=True, blank=True)

    affecte_le = models.DateTimeField(auto_now_add=True)
    affecte_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="affecte_par",
        related_name="affectations_courrier_prononcees",
    )

    #: **La decharge.** Au Port, l'agent cote signe un cahier pour prouver qu'il
    #: a recu le courrier (entretien du 26 aout 2026). Tant que la decharge
    #: manque, aucun traitement n'est depose — ADR 035.
    accepte_le = models.DateTimeField(null=True, blank=True)
    accepte_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="accepte_par",
        related_name="affectations_courrier_acceptees",
    )
    #: Trace du support papier, qui continue d'etre tenu. Facultatifs tous les
    #: deux : un pli remis en main propre n'a pas de coursier, et une structure
    #: qui a cesse de tenir le cahier ne doit pas etre empechee d'accuser.
    remis_par = models.TextField(null=True, blank=True)
    reference_cahier = models.TextField(null=True, blank=True)
    retire_le = models.DateTimeField(null=True, blank=True)
    retire_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="retire_par",
        related_name="affectations_courrier_retirees",
    )

    class Meta:
        db_table = "affectation"
        ordering = ["-affecte_le"]
        verbose_name = "affectation"
        verbose_name_plural = "affectations"

    def __str__(self) -> str:
        return f"Courrier affecte a {self.utilisateur_id}"

    @property
    def accepte(self) -> bool:
        """L'agent a-t-il signe la decharge ?"""
        return self.accepte_le is not None


class Traitement(models.Model):
    """
    Ce que produit l'agent qui traite le courrier.

    **HYPOTHESE assumee du socle** : ni le cahier des charges ni le BRD ne
    decrivent ce que produit un agent qui traite un courrier. Le commentaire de
    la table le dit. Le modele est declare ici parce que `lecture.etape()` en a
    besoin pour distinguer « affecte » de « en traitement » — pas parce que
    l'ecran de redaction est specifie. Il ne l'est pas.
    """

    STATUT_BROUILLON = "brouillon"
    STATUT_SOUMIS = "soumis"
    STATUT_RETOURNE = "retourne"
    STATUT_VALIDE = "valide"
    STATUTS = [
        (STATUT_BROUILLON, "Brouillon"),
        (STATUT_SOUMIS, "Soumis"),
        (STATUT_RETOURNE, "Retourne"),
        (STATUT_VALIDE, "Valide"),
    ]

    cotation_structure = models.ForeignKey(
        CotationStructure,
        on_delete=models.PROTECT,
        db_column="cotation_structure_id",
        related_name="traitements",
    )
    #: Double le chemin par `cotation_structure` et c'est voulu : le registre
    #: compte les traitements d'un courrier sans traverser deux jointures.
    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.PROTECT,
        db_column="courrier_id",
        related_name="traitements",
    )
    redacteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="redacteur_id",
        related_name="traitements_rediges",
    )
    version = models.SmallIntegerField(default=1)
    contenu = models.TextField(null=True, blank=True)
    contenu_format = models.TextField(default="html")
    statut = models.TextField(choices=STATUTS, default=STATUT_BROUILLON)
    soumis_le = models.DateTimeField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "traitement"
        ordering = ["-cree_le"]
        verbose_name = "traitement"
        verbose_name_plural = "traitements"

    def __str__(self) -> str:
        return f"Traitement {self.version} du courrier {self.courrier_id}"


class SequenceNumerotation(models.Model):
    """
    Le compteur annuel d'une session d'enregistrement.

    **Aucune ecriture Python ne doit toucher cette table.** Elle est incrementee
    par le declencheur `courrier_numero`, sous verrou de ligne, dans la
    transaction d'insertion du courrier. Le modele n'existe que pour la **lire** :
    `GET /courriers/contexte` montre a l'agent le numero qui sera probablement
    attribue, ce qui suppose de lire `dernier_numero` sans le consommer.

    « Probablement » n'est pas une precaution de style : entre la lecture et
    l'insertion, un autre agent peut enregistrer. Le champ que le front affiche
    s'appelle `numeroPrevu` pour cette raison.
    """

    session = models.ForeignKey(
        SessionCourrier,
        on_delete=models.PROTECT,
        db_column="session_id",
        related_name="sequences",
    )
    annee = models.SmallIntegerField()
    dernier_numero = models.IntegerField(default=0)

    class Meta:
        db_table = "sequence_numerotation"
        ordering = ["-annee"]
        verbose_name = "sequence de numerotation"
        verbose_name_plural = "sequences de numerotation"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "annee"], name="sequence_numerotation_session_id_annee_key"
            )
        ]

    def __str__(self) -> str:
        return f"Session {self.session_id} — {self.annee} : {self.dernier_numero}"


# =====================================================================
#  Le bureau d'ordre de structure
# =====================================================================


class PassageStructure(models.Model):
    """
    L'entree et la sortie d'un courrier dans une structure — le registre du
    **bureau d'ordre de la structure**, tenu par son point focal.

    **L'entree n'est pas saisie.** Le declencheur `cotation_structure_passage`
    pose la ligne au moment ou la cotation nomme la structure. C'est la seule
    facon d'obtenir une date d'entree qui ne depende pas de la diligence de
    celui qui tient le registre : mesuree a partir de l'accuse de reception, la
    duree de detention aurait toujours ete flatteuse.

    **L'accuse est distinct de l'entree, et c'est tout l'interet.** L'ecart entre
    `entre_le` et `accuse_le` est le temps mort du bureau d'ordre — celui que
    personne ne voyait, parce que rien ne le mesurait.

    Une seconde cotation vers la meme structure fait un **second passage** : un
    courrier renvoye a la DAF y entre a nouveau. L'unicite porte donc sur la
    ligne de cotation, jamais sur le couple (courrier, structure).
    """

    #: Les cinq facons de sortir. `transmission` couvre le renvoi vers une autre
    #: structure ; `retour`, le renvoi au bureau d'ordre central.
    MOTIFS = [
        ("reponse", "Réponse transmise"),
        ("retour", "Retour au bureau d'ordre central"),
        ("transmission", "Transmis à une autre structure"),
        ("cloture", "Clôturé"),
        ("autre", "Autre"),
    ]

    courrier = models.ForeignKey(
        Courrier, on_delete=models.CASCADE, db_column="courrier_id", related_name="passages"
    )
    structure = models.ForeignKey(
        Structure, on_delete=models.PROTECT, db_column="structure_id", related_name="passages"
    )
    cotation_structure = models.OneToOneField(
        CotationStructure,
        on_delete=models.CASCADE,
        db_column="cotation_structure_id",
        related_name="passage",
    )

    entre_le = models.DateTimeField()
    accuse_le = models.DateTimeField(null=True, blank=True)
    accuse_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="accuse_par",
        related_name="passages_accuses",
    )
    sorti_le = models.DateTimeField(null=True, blank=True)
    sorti_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="sorti_par",
        related_name="passages_sortis",
    )
    motif_sortie = models.TextField(null=True, blank=True, choices=MOTIFS)
    note_sortie = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "passage_structure"
        ordering = ["-entre_le", "-id"]
        verbose_name = "passage en structure"
        verbose_name_plural = "passages en structure"

    def __str__(self) -> str:
        return f"Courrier {self.courrier_id} — {self.structure_id}"

    @property
    def accuse(self) -> bool:
        """Le bureau d'ordre a-t-il reconnu la reception ?"""
        return self.accuse_le is not None

    @property
    def ouvert(self) -> bool:
        """Le courrier est-il encore dans la structure ?"""
        return self.sorti_le is None


# =====================================================================
#  Le fil d'observations, et l'ecart signale
# =====================================================================


class Observation(models.Model):
    """
    Une observation portee au dossier d'un courrier.

    **Tout lecteur ecrit, tout lecteur lit, jamais modifiable** — arbitrage du
    Port, 26 aout 2026. Le modele n'a donc ni `modifie_le` ni `invalide_le` : ce
    ne sont pas des colonnes oubliees, c'est la regle inscrite dans le schema.
    Un fil ou l'on reecrit son message apres coup ne vaut pas comme trace.

    A ne pas confondre avec `Courrier.observations`, qui est la **zone de saisie
    du formulaire d'enregistrement** : un texte unique, sans auteur ni date. Les
    deux coexistent, et `lecture._observations()` ne rend que celui-ci.

    Pas de `structure_id`, a la difference de l'evenement (ADR 032) : le fil est
    commun a toutes les structures cotees. C'est ce que veut dire « tout lecteur
    lit » — le cloisonner aurait produit cinq fils paralleles au lieu d'un.
    """

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        db_column="courrier_id",
        related_name="fil_observations",
    )
    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="auteur_id",
        related_name="observations_courrier",
    )
    texte = models.TextField()
    publie_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "observation_courrier"
        ordering = ["publie_le", "id"]
        verbose_name = "observation"
        verbose_name_plural = "observations"

    def __str__(self) -> str:
        return f"Observation de {self.auteur_id} sur le courrier {self.courrier_id}"


class SignalementEcart(models.Model):
    """
    Un ecart constate sur le circuit papier d'un courrier — A-12.

    **Le signalement vise une structure, jamais une personne.** L'emetteur
    choisit son destinataire (arbitrage du 26 aout 2026) et c'est le responsable
    de cette structure qui le prend en charge — celui qui porte `AFF`. Nommer
    une personne aurait produit un registre bloque le jour ou elle s'absente.

    **Trois etats, deux transitions, un seul sens** : `ouvert` ->
    `pris_en_compte` -> `clos`. Rien ne revient en arriere. Un ecart rouvert est
    un nouvel ecart, sans quoi la duree de prise en charge se remettrait a zero a
    chaque hesitation. La contrainte `signalement_etat_horodate` le tient au
    niveau du moteur.
    """

    ETAT_OUVERT = "ouvert"
    ETAT_PRIS_EN_COMPTE = "pris_en_compte"
    ETAT_CLOS = "clos"
    ETATS = [
        (ETAT_OUVERT, "Ouvert"),
        (ETAT_PRIS_EN_COMPTE, "Pris en compte"),
        (ETAT_CLOS, "Clos"),
    ]

    #: Les cinq types que l'ecran A-12 portait deja. Contraints en base plutot
    #: que libres : un type inconnu ne se voit qu'au moment de compter les
    #: ecarts par type, c'est-a-dire six mois trop tard.
    TYPES = [
        ("PIECE_MANQUANTE", "Pièce manquante"),
        ("PLI_ENDOMMAGE", "Pli endommagé"),
        ("DESTINATAIRE_ERRONE", "Destinataire erroné"),
        ("PLI_NON_RECU", "Pli non reçu"),
        ("DOUBLON", "Doublon d'enregistrement"),
    ]

    GRAVITES = [
        ("MINEURE", "Mineure"),
        ("NOTABLE", "Notable"),
        ("BLOQUANTE", "Bloquante"),
    ]

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        db_column="courrier_id",
        related_name="signalements",
    )
    type_ecart = models.TextField(choices=TYPES)
    gravite = models.TextField(choices=GRAVITES, default="NOTABLE")
    description = models.TextField()
    destinataire_structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        db_column="destinataire_structure_id",
        related_name="signalements_recus",
    )
    #: Figee a l'emission : une mutation ne doit pas reecrire d'ou venait
    #: l'alerte.
    emetteur_structure = models.ForeignKey(
        Structure,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="emetteur_structure_id",
        related_name="signalements_emis",
    )
    etat = models.TextField(choices=ETATS, default=ETAT_OUVERT)

    emis_le = models.DateTimeField(auto_now_add=True)
    emis_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="emis_par",
        related_name="signalements_emis",
    )
    pris_en_compte_le = models.DateTimeField(null=True, blank=True)
    pris_en_compte_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="pris_en_compte_par",
        related_name="signalements_pris_en_compte",
    )
    clos_le = models.DateTimeField(null=True, blank=True)
    clos_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="clos_par",
        related_name="signalements_clos",
    )
    #: Obligatoire a la cloture : un ecart clos sans un mot ne se distingue pas
    #: d'un ecart oublie.
    suite_donnee = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "signalement_ecart"
        ordering = ["-emis_le", "-id"]
        verbose_name = "signalement d'ecart"
        verbose_name_plural = "signalements d'ecart"

    def __str__(self) -> str:
        return f"{self.type_ecart} sur le courrier {self.courrier_id}"


# =====================================================================
#  Les versions d'un traitement
# =====================================================================


class TraitementVersion(models.Model):
    """
    L'etat fige d'un traitement a chaque restitution.

    La table vit au socle depuis le premier jour ; le modele n'est declare
    qu'avec l'ecran de redaction (27 aout 2026). Une ligne est ecrite **a chaque
    restitution**, jamais a l'enregistrement du brouillon : ce qui merite d'etre
    garde est ce que l'agent a rendu, pas chacune de ses frappes.

    L'interet n'apparait qu'au retour du responsable — la version 1 dit ce qui a
    ete rendu la premiere fois, la version 2 ce qui a ete corrige, et l'ecart
    entre les deux est la seule trace de ce qui n'allait pas.
    """

    traitement = models.ForeignKey(
        "courrier.Traitement",
        on_delete=models.CASCADE,
        db_column="traitement_id",
        related_name="versions",
    )
    version = models.SmallIntegerField()
    contenu = models.TextField(null=True, blank=True)
    redacteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="redacteur_id",
        related_name="versions_de_traitement",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "traitement_version"
        ordering = ["-version"]
        verbose_name = "version de traitement"
        verbose_name_plural = "versions de traitement"
        constraints = [
            models.UniqueConstraint(
                fields=["traitement", "version"],
                name="traitement_version_traitement_id_version_key",
            )
        ]

    def __str__(self) -> str:
        return f"Version {self.version} du traitement {self.traitement_id}"


# =====================================================================
#  Pilier suivi — la corbeille de celui qui instruit
# =====================================================================


class TacheTraitement(models.Model):
    """
    Une etape que l'agent se donne sur un courrier.

    **Ce n'est pas le circuit du courrier**, et l'ecran C-01 le dit avec les
    memes mots : « ces etapes ne sont pas le circuit du courrier : ce sont les
    taches que l'agent se donne. Elles n'engagent que lui. »

    A ne pas confondre avec `activite.Tache`, qui pend a une activite et porte un
    **poids** dans le calcul d'avancement. Celle-ci n'a ni poids ni echeance : ce
    n'est pas un plan d'actions, c'est une liste de courses.

    D'ou `utilisateur` : la liste appartient a une personne sur un courrier. Deux
    agents affectes au meme dossier tiennent deux listes — une liste partagee
    serait un circuit qui ne dit pas son nom.
    """

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        db_column="courrier_id",
        related_name="taches_de_traitement",
    )
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="utilisateur_id",
        related_name="taches_de_courrier",
    )
    libelle = models.TextField()
    #: Faite ou non : une seule colonne, et l'etat s'en deduit. Un booleen en
    #: plus de la date aurait permis « faite le 3, non faite ».
    faite_le = models.DateTimeField(null=True, blank=True)
    ordre = models.SmallIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "tache_traitement"
        ordering = ["ordre", "id"]
        verbose_name = "tache de traitement"
        verbose_name_plural = "taches de traitement"

    def __str__(self) -> str:
        return self.libelle


class NoteTraitement(models.Model):
    """
    Ce que l'agent note pour lui sur un courrier.

    **Une table a part, et non un drapeau sur `Observation`.** Le fil
    d'observations est commun par arbitrage du Port — « tout lecteur ecrit, tout
    lecteur lit ». Y poser une colonne `privee` aurait defait cet arbitrage dans
    la table meme qui le porte.

    `privee` decide de qui lit : l'auteur et sa hierarchie, ou tout lecteur du
    courrier. Jamais modifiable, comme le fil : une note reecrite apres coup ne
    vaut pas comme trace.
    """

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        db_column="courrier_id",
        related_name="notes_de_traitement",
    )
    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="auteur_id",
        related_name="notes_de_courrier",
    )
    texte = models.TextField()
    privee = models.BooleanField(default=True)
    publiee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "note_traitement"
        ordering = ["publiee_le", "id"]
        verbose_name = "note de traitement"
        verbose_name_plural = "notes de traitement"

    def __str__(self) -> str:
        return f"Note de {self.auteur_id} sur le courrier {self.courrier_id}"


#: Les trois etats d'une demande de delai. `en_attente` est un **fait** et non
#: une deduction : le responsable qui ouvre sa liste doit pouvoir la trier sans
#: recalculer.
DEMANDE_EN_ATTENTE = "en_attente"
DEMANDE_ACCORDEE = "accordee"
DEMANDE_REFUSEE = "refusee"


class DemandeDelai(models.Model):
    """
    Le report d'echeance que l'agent demande a son responsable.

    La **prolongation** existe deja (`services.prolonger`, sous les permissions
    de cotation) : c'est le geste de celui qui accorde. Celui de celui qui
    demande manquait, et sa demande passait alors par le telephone — ou elle ne
    laissait aucune trace, et ou le delai continuait de courir contre lui.

    Accorder une demande **prolonge le courrier** : les deux gestes se rejoignent
    dans `services.decider_demande_delai`, qui appelle `prolonger()`. Deux
    chemins d'ecriture pour la meme colonne auraient fini par diverger.
    """

    courrier = models.ForeignKey(
        Courrier,
        on_delete=models.CASCADE,
        db_column="courrier_id",
        related_name="demandes_de_delai",
    )
    demandeur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="demandeur_id",
        related_name="demandes_de_delai",
    )
    jours_demandes = models.SmallIntegerField()
    motif = models.TextField()
    demandee_le = models.DateTimeField(auto_now_add=True)
    etat = models.TextField(default=DEMANDE_EN_ATTENTE)
    decidee_le = models.DateTimeField(null=True, blank=True)
    decidee_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="decidee_par",
        related_name="demandes_de_delai_decidees",
    )
    reponse = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "demande_delai"
        ordering = ["-demandee_le", "-id"]
        verbose_name = "demande de delai"
        verbose_name_plural = "demandes de delai"

    def __str__(self) -> str:
        return f"Demande de {self.jours_demandes} j sur le courrier {self.courrier_id}"


class RechercheEnregistree(models.Model):
    """
    Les criteres qu'un agent conserve — la question qu'il repose chaque semaine.

    `criteres` en JSON et non en colonnes : ce sont ceux de l'ecran A-14, et
    l'ecran en gagnera. On les relit en bloc, on ne cherche jamais « les
    recherches qui portent sur la DAF ».

    Supprimee avec le compte (`ON DELETE CASCADE` au schema), contrairement a
    tout le reste du pilier : ce n'est pas une trace, c'est un confort.
    """

    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.CASCADE,
        db_column="utilisateur_id",
        related_name="recherches_enregistrees",
    )
    libelle = models.TextField()
    criteres = models.JSONField()
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recherche_enregistree"
        ordering = ["libelle"]
        verbose_name = "recherche enregistree"
        verbose_name_plural = "recherches enregistrees"
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "libelle"],
                name="recherche_libelle_unique_par_agent",
            )
        ]

    def __str__(self) -> str:
        return self.libelle


#: Les deux natures d'une relance. `automatique` n'est **jamais** ecrite par
#: l'application : aucune regle de declenchement n'a ete communiquee, et les
#: escalades sont ancrees sur `circuit_etape`, qui est vide (A24). La valeur
#: existe au schema depuis `0001` et attend sa regle.
RELANCE_MANUELLE = "manuelle"
RELANCE_AUTOMATIQUE = "automatique"


class Relance(models.Model):
    """
    Une relance emise sur un courrier — le geste de C-02.

    **La table est du socle, le modele arrive le 28 aout 2026.** `relance.py` la
    lisait deja en SQL direct pour compter les relances emises et dater la
    derniere : deux colonnes agregees ne justifiaient pas un modele. Ecrire, si.
    Une ecriture metier passe par `acteur()`, inscrit un evenement et notifie ;
    faire cela au curseur aurait mis la regle hors de portee de l'ORM et des
    declencheurs.

    `destinataire` est **obligatoire au schema**, et c'est la contrainte qui
    structure tout le geste : on ne relance pas un courrier, on relance
    quelqu'un. Quand nul n'est affecte — le motif de relance le plus frequent —
    le destinataire est le responsable de la structure cotee, et
    `services.emettre_relance` refuse plutot que d'inventer une cible.

    `instance_etape` reste nul : le trajet du courrier au Port n'est pas un
    circuit ([ADR 034]), et la colonne vise les relances d'un circuit qui
    n'existe pas.

    [ADR 034]: ../docs/architecture/034-le-trajet-du-courrier-n-est-pas-un-circuit.md
    """

    courrier = models.ForeignKey(
        Courrier,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="courrier_id",
        related_name="relances",
    )
    #: Nul : la table sert aussi les relances d'activite, qui ne portent pas de
    #: courrier. C'est pourquoi tout compte de ce module filtre sur
    #: `courrier_id IS NOT NULL`.
    instance_etape_id = models.BigIntegerField(null=True, blank=True)
    nature = models.TextField(default=RELANCE_MANUELLE)
    emetteur = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="emetteur_id",
        related_name="relances_emises",
    )
    destinataire = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="destinataire_id",
        related_name="relances_recues",
    )
    motif = models.TextField(null=True, blank=True)
    emise_le = models.DateTimeField(auto_now_add=True)
    #: Renseignee le jour ou le destinataire agit. Aucune route ne l'ecrit
    #: encore : « avoir repondu a une relance » n'a pas ete defini, et poser une
    #: date sur la premiere ecriture venue aurait invente la regle.
    reponse_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "relance"
        ordering = ["-emise_le", "-id"]
        verbose_name = "relance"
        verbose_name_plural = "relances"

    def __str__(self) -> str:
        return f"Relance du courrier {self.courrier_id} à {self.destinataire_id}"

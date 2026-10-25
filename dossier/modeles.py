"""
Les dossiers a instruire — §3.6, §3.7 et le perimetre pilote du BRD (§6.1).

« Reception et enregistrement, qualification et affectation, instruction,
validation hierarchique a un ou plusieurs niveaux selon des seuils definis,
notification au demandeur, puis archivage. »

**Cinq tables, et deux qui n'existent pas.**

Ce qui n'est pas ici, et pourquoi :

 * *pas de table d'evenements du dossier.* L'historique de la fiche se lit dans
   le journal du noyau (`evenement`), filtre sur `objet_type = 'dossier'`. Une
   seconde table aurait produit deux histoires du meme dossier, et c'est
   toujours la moins complete qu'on finit par lire. Voir l'ADR 012 ;
 * *pas de colonne `etat`.* « Hors delai », « En attente de complement » et
   « Retourne » se **deduisent** — d'une echeance, d'un complement non recu,
   d'un retour inscrit au journal. Les stocker imposerait de reecrire toutes
   les lignes chaque nuit pour un resultat que la date donne deja. C'est
   l'arbitrage n° 2 du pilier activites, applique ici : voir la vue
   `v_dossier_etat`. Seule l'**etape** est stockee, parce qu'elle resulte d'une
   decision et non d'un calcul.

Le lien avec le courrier est **unidirectionnel et sans cle etrangere** : un
courrier entrant peut donner naissance a un dossier (§3.6), jamais l'inverse.
Le dossier garde le numero du courrier d'origine et son identifiant, sans
contrainte referentielle — le pilier courrier n'est pas en service, et une
contrainte vers une table que personne n'alimente aurait interdit d'ouvrir le
moindre dossier. Voir A34.
"""

from django.db import models

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure

#: Les typologies de dossier. Referentiel **ferme** : c'est le type qui decide
#: de la regle d'affectation et du circuit de validation, et deux libelles
#: saisis a la main pour la meme chose auraient produit deux circuits.
TYPE_DEMANDE = "demande"
TYPE_RECLAMATION = "reclamation"
TYPE_AUTORISATION = "autorisation"
TYPE_REQUETE = "requete"
TYPE_ACTE = "acte"
TYPES = [
    (TYPE_DEMANDE, "Demande"),
    (TYPE_RECLAMATION, "Réclamation"),
    (TYPE_AUTORISATION, "Autorisation"),
    (TYPE_REQUETE, "Requête"),
    (TYPE_ACTE, "Acte"),
]

#: Les cinq etapes du circuit d'instruction, dans l'ordre. Elles sont figees et
#: ne passent pas par le moteur `circuit` du socle : celui-ci est ancre sur
#: `cotation_structure`, donc sur le courrier, et sa selection se fait par sens
#: et par nature de courrier. Voir l'ADR 012.
ETAPE_QUALIFICATION = "qualification"
ETAPE_INSTRUCTION = "instruction"
ETAPE_VALIDATION = "validation"
ETAPE_NOTIFICATION = "notification"
ETAPE_CLOS = "clos"
ETAPES = [
    (ETAPE_QUALIFICATION, "Qualification"),
    (ETAPE_INSTRUCTION, "Instruction"),
    (ETAPE_VALIDATION, "Validation"),
    (ETAPE_NOTIFICATION, "Notification"),
    (ETAPE_CLOS, "Clos"),
]

#: L'ordre du circuit, pour savoir ce qui est franchi et ce qui reste. Un rang
#: numerique plutot que l'ordre de declaration : « retourner a l'etape
#: anterieure » a besoin de comparer deux etapes, pas de les enumerer.
RANG_ETAPES = {
    ETAPE_QUALIFICATION: 1,
    ETAPE_INSTRUCTION: 2,
    ETAPE_VALIDATION: 3,
    ETAPE_NOTIFICATION: 4,
    ETAPE_CLOS: 5,
}

CRITICITE_STANDARD = "standard"
CRITICITE_SENSIBLE = "sensible"
CRITICITE_URGENT = "urgent"
CRITICITES = [
    (CRITICITE_STANDARD, "Standard"),
    (CRITICITE_SENSIBLE, "Sensible"),
    (CRITICITE_URGENT, "Urgent"),
]


class RegleAffectation(models.Model):
    """
    Ce qui decide a quelle structure un dossier arrive — RF-BPM-02.

    « L'affectation est dynamique, decidee par des regles metier : role,
    service, seuil de montant, criticite. »

    La regle porte son **libelle en toutes lettres**, et ce libelle est celui
    que la fiche d'instruction affiche. Ce n'est pas de la decoration : sans la
    phrase qui explique pourquoi ce dossier est arrive ici, l'affectation
    dynamique passe pour de l'arbitraire, et c'est le premier grief formule
    contre ce genre d'outil.

    La regle **la plus specifique l'emporte**, la priorite departageant le
    reste — meme mecanique que `circuit_regle` au socle. Une regle sans type,
    sans criticite et sans seuil est la regle par defaut.
    """

    libelle = models.TextField()
    #: Les trois criteres. `null` signifie « quel que soit » : une regle qui ne
    #: porte que sur le type s'applique a toutes les criticites.
    type_dossier = models.TextField(choices=TYPES, null=True, blank=True)
    criticite = models.TextField(choices=CRITICITES, null=True, blank=True)
    #: Seuil de montant en francs CFA, au-dela duquel la regle s'applique.
    #: Sans montant au dossier, une regle a seuil ne peut pas s'appliquer :
    #: elle est alors ignoree plutot que reputee satisfaite.
    montant_minimum = models.BigIntegerField(null=True, blank=True)
    #: La structure qui instruit quand la regle s'applique.
    structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        db_column="structure_id",
        related_name="regles_affectation",
    )
    #: Le plus petit l'emporte quand deux regles ont la meme specificite.
    priorite = models.SmallIntegerField(default=100)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "regle_affectation"
        ordering = ["priorite", "id"]
        verbose_name = "regle d'affectation"
        verbose_name_plural = "regles d'affectation"

    def __str__(self) -> str:
        return self.libelle

    @property
    def specificite(self) -> int:
        """Combien de criteres la regle porte. Trois l'emporte sur un."""
        return sum(
            1
            for critere in (self.type_dossier, self.criticite, self.montant_minimum)
            if critere is not None
        )


class Dossier(models.Model):
    """
    Un dossier a instruire.

    `regle_affectation_texte` double la cle etrangere, et c'est voulu : la
    regle appliquee est **figee** au moment de l'affectation. L'administrateur
    pouvant reecrire ses regles, une phrase recalculee a la volee reecrirait
    l'histoire — c'est le raisonnement que le socle a deja tenu pour
    `instance_circuit.circuit_version_id`.

    `echeance` ne se suspend pas. Le demandeur qui ne fournit pas ses pieces ne
    dispense pas l'institution de son obligation de reponse : « en attente de
    complement » est un etat du dossier, pas une pause du delai. C'est ce que
    dit l'ecran, et c'est ce que fait la vue.
    """

    reference = models.TextField(unique=True)
    objet = models.TextField()
    type_dossier = models.TextField(choices=TYPES, db_column="type_dossier")
    #: Personne ou entite qui recoit la notification en fin d'instruction. Du
    #: texte libre et non une cle vers `correspondant` : le demandeur d'un
    #: dossier n'est pas necessairement un correspondant du registre courrier,
    #: et forcer sa creation aurait pollue le referentiel. Voir A34.
    demandeur = models.TextField()
    contexte = models.TextField(null=True, blank=True)
    #: Montant en jeu, en francs CFA. Nullable : tous les dossiers n'en portent
    #: pas, et c'est lui qui active les regles a seuil.
    montant = models.BigIntegerField(null=True, blank=True)
    criticite = models.TextField(choices=CRITICITES, default=CRITICITE_STANDARD)

    structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        db_column="structure_id",
        related_name="dossiers",
    )
    instructeur = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="instructeur_id",
        related_name="dossiers_instruits",
    )
    regle_affectation = models.ForeignKey(
        RegleAffectation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="regle_affectation_id",
        related_name="dossiers",
    )
    #: La phrase figee. Voir la docstring de la classe.
    regle_affectation_texte = models.TextField()

    ouvert_le = models.DateField()
    echeance = models.DateField()
    etape = models.TextField(choices=ETAPES, default=ETAPE_QUALIFICATION)
    clos_le = models.DateField(null=True, blank=True)

    #: Le courrier d'origine, sans cle etrangere. Voir la docstring du module.
    courrier_origine_id = models.BigIntegerField(null=True, blank=True)
    courrier_origine_reference = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "dossier"
        ordering = ["echeance", "reference"]
        verbose_name = "dossier"
        verbose_name_plural = "dossiers"
        indexes = [
            models.Index(fields=["structure", "etape"], name="idx_dossier_structure_etape"),
            models.Index(fields=["echeance"], name="idx_dossier_echeance"),
        ]
        constraints = [
            # Un dossier clos porte sa date de cloture, et un dossier qui la
            # porte est clos. Sans cette contrainte, la file de versement
            # oublierait des dossiers clos ou en reclamerait d'ouverts.
            models.CheckConstraint(
                condition=(
                    models.Q(etape=ETAPE_CLOS, clos_le__isnull=False)
                    | ~models.Q(etape=ETAPE_CLOS) & models.Q(clos_le__isnull=True)
                ),
                name="dossier_cloture_coherente",
            ),
            models.CheckConstraint(
                condition=models.Q(echeance__gte=models.F("ouvert_le")),
                name="dossier_echeance_apres_ouverture",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.objet}"


class PieceDossier(models.Model):
    """
    Une piece du dossier — son identite, pas son contenu.

    La piece porte un nom et un format ; ce qui a ete depose vit dans ses
    versions. C'est ce qui permet de dire « le rapport d'expertise » sans avoir
    a choisir de quelle version on parle.

    Pourquoi pas `piece_jointe` du socle : celle-ci est ancree sur
    `courrier_id` et versionnee par chainage (`piece_precedente_id`), ce qui
    oblige a remonter la chaine pour savoir combien de versions existent. Le
    dossier a besoin de l'inverse — une piece, ses versions — et la fiche
    d'instruction affiche les deux ensemble. Voir l'ADR 012.
    """

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        db_column="dossier_id",
        related_name="pieces",
    )
    nom = models.TextField()
    format_fichier = models.TextField(db_column="format_fichier")
    ordre = models.SmallIntegerField(default=0)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "piece_dossier"
        ordering = ["ordre", "nom"]
        verbose_name = "piece du dossier"
        verbose_name_plural = "pieces du dossier"

    def __str__(self) -> str:
        return self.nom


class VersionPiece(models.Model):
    """
    Une version deposee — RF-GED-04, « versionnement sans ecrasement ».

    Rien ne remplace rien : une version depose une ligne de plus. La courante
    est la derniere, et les precedentes restent consultables. Sans cela, on ne
    peut plus dire sur quoi la decision a ete prise, meme deux ans plus tard —
    et c'est precisement ce qu'un contentieux demande.

    `empreinte` est celle du fichier depose. Elle sert la preuve d'integrite du
    versement (RF-GED-09) : une chaine d'empreintes calculee a l'archivage sur
    des fichiers qu'on n'aurait pas empreintes au depot ne prouverait rien.
    """

    piece = models.ForeignKey(
        PieceDossier,
        on_delete=models.CASCADE,
        db_column="piece_id",
        related_name="versions",
    )
    version = models.SmallIntegerField()
    taille_octets = models.BigIntegerField()
    empreinte = models.TextField()
    chemin_stockage = models.TextField()
    depose_le = models.DateTimeField(auto_now_add=True)
    depose_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="depose_par_id",
        related_name="versions_deposees",
    )

    class Meta:
        db_table = "version_piece_dossier"
        ordering = ["piece", "-version"]
        verbose_name = "version d'une piece"
        verbose_name_plural = "versions des pieces"
        constraints = [
            models.UniqueConstraint(
                fields=["piece", "version"],
                name="unicite_version_piece_dossier",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="version_piece_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.piece_id} v{self.version}"


class Complement(models.Model):
    """
    Une piece reclamee au demandeur.

    L'echeance est celle **donnee au demandeur**, et elle n'a rien a voir avec
    l'echeance d'instruction du dossier : demander un complement ne repousse
    pas le delai dont l'institution repond. Les confondre reviendrait a offrir
    a l'instructeur un moyen simple de ne jamais etre en retard.
    """

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        db_column="dossier_id",
        related_name="complements",
    )
    objet = models.TextField()
    demande_le = models.DateField()
    demande_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="demande_par_id",
        related_name="complements_demandes",
    )
    echeance = models.DateField()
    recu_le = models.DateField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "complement_dossier"
        ordering = ["-demande_le", "id"]
        verbose_name = "complement demande"
        verbose_name_plural = "complements demandes"

    def __str__(self) -> str:
        return f"{self.dossier_id} — {self.objet}"


class ModeleCourrier(models.Model):
    """
    Un courrier-type de la bibliotheque — RF-SUI-05, fusion de documents.

    Le **corps entier** est stocke et affiche, jamais un extrait. Un agent qui
    choisit un modele sur trois lignes de resume decouvre ce qu'il a envoye
    apres l'avoir envoye ; c'est un courrier signe par l'institution, il se lit
    avant.

    `variables` liste les champs remplaces a la fusion. La liste est **derivee
    du corps** a l'enregistrement plutot que saisie a cote : deux listes
    divergent, et la premiere fusion qui laisse un `{demandeur}` en clair dans
    un courrier signe est de celles qu'on n'oublie pas.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    typologie = models.TextField()
    description = models.TextField(null=True, blank=True)
    corps = models.TextField()
    actif = models.BooleanField(default=True)
    #: Combien de fusions ont ete produites depuis ce modele. Un compteur et
    #: non un `count()` sur une table de fusions : ce qui interesse
    #: l'administrateur du referentiel, c'est de savoir quel modele ne sert
    #: jamais, pas de rejouer chaque fusion.
    utilisations = models.IntegerField(default=0)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "modele_courrier"
        ordering = ["typologie", "code"]
        verbose_name = "modele de courrier"
        verbose_name_plural = "modeles de courrier"

    def __str__(self) -> str:
        return f"{self.code} — {self.libelle}"


class VueDossierEtat(models.Model):
    """
    L'etat **affiche** d'un dossier — une vue, sans table derriere.

    Cinq etats sont affiches, aucun n'est stocke. « Hors delai » se lit d'une
    date, « En attente de complement » d'un complement non recu, « Retourne »
    d'un retour inscrit au journal, « Clos » de l'etape. Les stocker imposerait
    de reecrire toutes les lignes chaque nuit pour un resultat que la base
    donne deja — c'est l'arbitrage n° 2 du pilier activites, et la meme
    mecanique que `v_activite_etat`.

    L'ordre des cas n'est pas indifferent : **le retard l'emporte sur
    l'attente**. Un dossier hors delai qui attend un complement est d'abord
    hors delai, sans quoi l'instructeur lirait « en attente » et se croirait
    couvert.
    """

    id = models.BigIntegerField(primary_key=True)
    structure_id = models.BigIntegerField()
    etape = models.TextField()
    etat_affiche = models.TextField()
    jours_restants = models.IntegerField()
    complements_en_attente = models.IntegerField()

    class Meta:
        managed = False
        db_table = "v_dossier_etat"

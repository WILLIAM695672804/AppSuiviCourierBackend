"""
Parametrage metier — ce qui se regle sans livraison de code.

Huit referentiels, et la raison d'etre de tous est la meme : l'institution
change ses circuits, ses delais et ses correspondants beaucoup plus souvent
qu'elle ne change de logiciel. Chaque valeur ecrite en dur ici serait une
livraison a chaque reorganisation.

**Six de ces tables existent au socle et n'avaient aucun modele** : circuit,
circuit_version, circuit_etape, circuit_regle, nature, mention_type, priorite,
correspondant. Elles appartiennent au pilier courrier, qui n'est pas commence.
Les modeles sont ecrits ici — et non dans un `courrier/modeles.py` qui
n'existe pas — parce que l'ecran de parametrage, lui, existe deja et doit les
lire. Le jour ou le pilier courrier s'ecrit, il les trouvera faites.

**Deux tables sont neuves** : `rubrique_classement` (RF-GED-07) et
`seuil_alerte` (RF-BI-05, RF-ADM-04). Aucune ne figurait au socle.

Trois principes qui valent pour tout ce fichier :

 1. **Le circuit est versionne, pas modifie.** Un courrier en cours suit la
    version du circuit sous laquelle il est entre. Changer les etapes d'un
    circuit en cours d'annee ferait changer le passe.
 2. **Rien n'est supprime.** `actif` et `invalide_le`, jamais de DELETE : une
    mention retiree du formulaire doit rester lisible sur les cotations de
    l'an dernier.
 3. **Les libelles sortent en clair.** Le front affiche « Escalade au
    supérieur », pas `escalade_vers_poste_id`. La traduction se fait au
    serveur, une fois, pas dans chaque ecran.
"""

from django.contrib.postgres.search import SearchVectorField
from django.db import models

from noyau.organisation.modeles import NiveauHierarchique, Poste, Structure


class Nature(models.Model):
    """
    La nature d'un courrier, et le delai qu'elle emporte.

    `delai_defaut_jours` est ce que l'ecran de parametrage appelle un
    « engagement » : c'est le delai cible de traitement attache a la nature.
    Il n'y a pas de table d'engagement de service separee — un second
    referentiel de delais finirait par contredire celui-ci.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    delai_defaut_jours = models.SmallIntegerField(null=True, blank=True)
    #: Combien de jours avant l'echeance la premiere alerte part. Colonne
    #: neuve : le socle portait le delai cible sans dire quand prevenir, et un
    #: delai qu'on decouvre le jour de son expiration ne sert a rien.
    alerte_avant_jours = models.SmallIntegerField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "nature"
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle


class MentionType(models.Model):
    """
    Les mentions portees a la cotation — « Pour attribution », « Pour avis »…

    Le socle le dit dans un commentaire de table : a cinq cents courriers par
    jour, la saisie libre ne tient pas. Une liste fermee est ce qui rend la
    statistique possible.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    ordre = models.SmallIntegerField(default=0)
    #: Ce que la mention emporte comme delai propre. « Pour avis sous 48 h »
    #: n'a pas le meme poids que « Pour information ».
    delai_jours = models.SmallIntegerField(null=True, blank=True)
    #: Ce qu'elle declenche, en clair — « Ouvre un traitement », « Ne cree
    #: aucune tache ». Un texte et non un code : le comportement reel sera
    #: porte par le pilier courrier, et figer un code maintenant reviendrait a
    #: decider a sa place. Voir A25.
    comportement = models.TextField(null=True, blank=True)
    #: Les codes de niveau hierarchique autorises a porter cette mention. Un
    #: tableau et non une table de liaison : la liste tient en trois codes et
    #: se lit d'un coup d'oeil dans l'ecran d'administration.
    niveaux_autorises = models.JSONField(default=list, blank=True)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "mention_type"
        ordering = ["ordre", "libelle"]

    def __str__(self) -> str:
        return self.libelle


class Priorite(models.Model):
    """L'urgence d'un courrier. `rang` ordonne, `couleur` habille."""

    code = models.TextField(unique=True)
    libelle = models.TextField()
    rang = models.SmallIntegerField()
    couleur = models.TextField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "priorite"
        ordering = ["rang"]

    def __str__(self) -> str:
        return self.libelle


class JourFerie(models.Model):
    """
    Un jour non ouvre declare — table `jour_ferie` du socle.

    **Indispensable au calcul des delais.** L'echeance d'un courrier se compte en
    jours ouvres (`noyau.calendrier.ajouter_jours_ouvres`), et sans cette table
    le calendrier ne connaitrait que les week-ends. Le commentaire du socle est
    explicite : elle « n'existe dans aucun document source : a administrer » —
    aucune ferie du Cameroun n'y est donc semee, parce qu'un calendrier faux
    decale toutes les echeances sans que rien ne le dise.

    La cle primaire est **la date elle-meme**, comme au socle : deux lignes pour
    le meme jour n'ont aucun sens, et une contrainte d'unicite sur une colonne
    par ailleurs unique aurait ete un doublon de la cle.
    """

    date_ferie = models.DateField(primary_key=True)
    libelle = models.TextField()

    class Meta:
        db_table = "jour_ferie"
        ordering = ["date_ferie"]
        verbose_name = "jour ferie"
        verbose_name_plural = "jours feries"

    def __str__(self) -> str:
        return f"{self.date_ferie} — {self.libelle}"


class Correspondant(models.Model):
    """
    Qui ecrit au Port, et a qui le Port ecrit.

    `raison_sociale` **ou** `nom` : une contrainte du socle exige l'un des
    deux. Une personne physique n'a pas de raison sociale, une administration
    n'a pas de prenom, et forcer les deux aurait produit des lignes remplies
    de tirets.
    """

    TYPES = [
        ("externe", "Externe"),
        ("interne", "Interne"),
        ("usager", "Usager"),
        ("administration", "Administration"),
    ]

    type = models.TextField(choices=TYPES)
    raison_sociale = models.TextField(null=True, blank=True)
    #: Sigle usuel — « MINFI », « APN ». Porte au vecteur plein texte au meme
    #: poids que la raison sociale : ce n'est pas une precision sur l'entree,
    #: c'est son autre nom, et c'est celui que l'agent tape en premier.
    sigle = models.TextField(null=True, blank=True)
    nom = models.TextField(null=True, blank=True)
    prenom = models.TextField(null=True, blank=True)
    adresse = models.TextField(null=True, blank=True)
    ville = models.TextField(null=True, blank=True)
    courriel = models.TextField(null=True, blank=True)
    telephone = models.TextField(null=True, blank=True)
    structure = models.ForeignKey(
        Structure, null=True, blank=True, on_delete=models.PROTECT, db_column="structure_id"
    )
    actif = models.BooleanField(default=True)

    #: Vecteur plein texte alimente par le declencheur
    #: `correspondant_recherche_maj`, jamais par l'application. Declare parce que
    #: le selecteur d'expediteur cherche dessus, avec la configuration
    #: `fr_unaccent` : « Impots » doit trouver « Impôts », sans quoi l'agent cree
    #: un doublon plutot que de retrouver l'entree existante.
    #:
    #: Le NULL que Django envoie a l'insertion est sans effet — le declencheur
    #: est BEFORE INSERT OR UPDATE et recalcule le vecteur dans tous les cas.
    recherche = SearchVectorField(null=True, editable=False)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "correspondant"
        ordering = ["raison_sociale", "nom"]

    def __str__(self) -> str:
        return self.raison_sociale or f"{self.nom} {self.prenom or ''}".strip()

    @property
    def designation(self) -> str:
        """Le nom sous lequel l'ecran l'affiche, quel que soit son type."""
        return str(self)


class Circuit(models.Model):
    """Un modele de traitement du courrier. Ses etapes vivent dans ses versions."""

    code = models.TextField(unique=True)
    libelle = models.TextField()
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "circuit"
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle


class CircuitVersion(models.Model):
    """
    Une version publiee d'un circuit.

    **C'est la version qui porte les etapes, pas le circuit.** Un courrier en
    cours suit la version sous laquelle il est entre ; modifier les etapes en
    place ferait changer le passe, et un delai depasse deviendrait tenu.

    `definition_bpmn` est une colonne XML du socle, vide a ce jour. Le BRD
    demande une modelisation « en notation BPMN 2.0 » ; ce qui est mis en
    oeuvre est une liste ordonnee d'etapes, choix assume et affiche a l'ecran.
    La colonne reste : elle accueillera l'export du jour ou un modeleur
    existera.
    """

    MODES = [
        ("directe", "Directe"),
        ("cascade", "Cascade"),
    ]

    circuit = models.ForeignKey(
        Circuit, on_delete=models.CASCADE, db_column="circuit_id", related_name="versions"
    )
    version = models.SmallIntegerField()
    mode_cotation = models.TextField(choices=MODES, default="cascade")
    niveau_max = models.ForeignKey(
        NiveauHierarchique,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="niveau_max_id",
    )
    definition_bpmn = models.TextField(null=True, blank=True)
    publie_le = models.DateTimeField(null=True, blank=True)
    publie_par = models.BigIntegerField(null=True, blank=True)
    motif_modification = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "circuit_version"
        ordering = ["circuit_id", "-version"]
        unique_together = [("circuit", "version")]

    def __str__(self) -> str:
        return f"{self.circuit_id} v{self.version}"


class CircuitEtape(models.Model):
    """
    Une etape d'un circuit, son delai et ce qui se passe a l'echeance.

    Trois colonnes disent qui agit — `poste`, `profil_id`,
    `permission_requise_id` — et elles ne sont pas redondantes : une etape peut
    viser un poste nommement (le DG signe), un profil (un agent
    d'enregistrement quelconque) ou une permission (quiconque peut valider).
    L'ecran rend la plus precise des trois renseignees.

    **`bloquante` porte le circuit accelere** (RF-BPM-10) : seule une etape non
    bloquante peut etre contournee quand l'urgence l'exige. C'est la seule
    definition du contournement, et elle est ici plutot que dans le code du
    pilier — sinon un jour d'urgence deciderait de ce qu'on saute.
    """

    circuit_version = models.ForeignKey(
        CircuitVersion,
        on_delete=models.CASCADE,
        db_column="circuit_version_id",
        related_name="etapes",
    )
    rang = models.SmallIntegerField()
    libelle = models.TextField()
    poste = models.ForeignKey(
        Poste,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="poste_id",
        related_name="etapes_circuit",
    )
    profil_id = models.BigIntegerField(null=True, blank=True)
    permission_requise_id = models.BigIntegerField(null=True, blank=True)
    delai_jours = models.SmallIntegerField(null=True, blank=True)
    #: Jours avant l'echeance auxquels l'alerte part. Colonne neuve, meme
    #: raison que sur `nature` : le socle disait le delai, pas le prealerte.
    alerte_avant_jours = models.SmallIntegerField(null=True, blank=True)
    bloquante = models.BooleanField(default=True)
    condition_regle = models.JSONField(null=True, blank=True)
    escalade_vers_poste = models.ForeignKey(
        Poste,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="escalade_vers_poste_id",
        related_name="etapes_escalade",
    )

    class Meta:
        db_table = "circuit_etape"
        ordering = ["circuit_version_id", "rang"]
        unique_together = [("circuit_version", "rang")]

    def __str__(self) -> str:
        return f"{self.rang}. {self.libelle}"


class CircuitRegle(models.Model):
    """
    Comment le circuit applicable est choisi.

    **La plus specifique l'emporte**, `priorite` departageant les cas
    restants : c'est ce qui permet d'ecrire « cascade partout, sauf
    l'inspection en direct ». Une regle sans aucun critere est le repli — elle
    s'applique quand rien d'autre ne correspond, et un courrier qui n'entrerait
    dans aucun circuit resterait invisible.
    """

    SENS = [
        ("arrive", "Arrivée"),
        ("depart", "Départ"),
        ("interne", "Interne"),
    ]

    circuit = models.ForeignKey(
        Circuit, on_delete=models.PROTECT, db_column="circuit_id", related_name="regles"
    )
    structure = models.ForeignKey(
        Structure, null=True, blank=True, on_delete=models.PROTECT, db_column="structure_id"
    )
    nature = models.ForeignKey(
        Nature, null=True, blank=True, on_delete=models.PROTECT, db_column="nature_id"
    )
    sens = models.TextField(null=True, blank=True, choices=SENS)
    confidentiel = models.BooleanField(null=True, blank=True)
    priorite = models.SmallIntegerField(default=100)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "circuit_regle"
        ordering = ["priorite", "id"]

    def __str__(self) -> str:
        return f"priorité {self.priorite} → circuit {self.circuit_id}"

    @property
    def repli(self) -> bool:
        """Une regle sans aucun critere s'applique a tout ce qui reste."""
        return (
            self.structure_id is None
            and self.nature_id is None
            and self.sens is None
            and self.confidentiel is None
        )


class RegleRoutage(models.Model):
    """
    Le routage direct — « les factures vont directement chez le DFC, sans
    passer par le DG ».

    Une regle de **cotation d'office a l'enregistrement**, et non un circuit :
    elle ne decrit aucun trajet de validation, elle dit vers quelle structure le
    courrier part des sa saisie au bureau d'ordre central.

    **Pourquoi pas `CircuitRegle`.** `CircuitRegle` designe un circuit, et les
    circuits sont ancres sur `CircuitEtape`, qui est vide faute d'avoir jamais
    recu le trajet reel du Port (A24). Y brancher le routage direct aurait fait
    dependre une regle connue d'une regle qui ne l'est pas.

    **La plus specifique l'emporte**, comme pour `CircuitRegle` : la specificite
    se compte en criteres renseignes, `priorite` croissante departageant le
    reste. Une regle sans aucun critere coterait tout le courrier du Port a une
    seule structure — le CHECK `regle_routage_a_un_critere` l'interdit, il n'y a
    donc pas de repli ici, et c'est voulu : l'absence de regle veut dire « le
    courrier suit la voie ordinaire », pas « il part au hasard ».

    `statut` reprend la distinction de `parametre` : une regle inventee par la
    conception ne se confond pas avec une regle transmise par le Port.
    """

    SENS = [
        ("arrive", "Arrivée"),
        ("depart", "Départ"),
        ("interne", "Interne"),
    ]
    STATUTS = [("acte", "Acté"), ("hypothese", "Hypothèse")]

    code = models.TextField(unique=True)
    libelle = models.TextField()

    # Les criteres. Tous facultatifs pris un a un, mais le moteur en exige au
    # moins un — voir la docstring.
    nature = models.ForeignKey(
        Nature, null=True, blank=True, on_delete=models.PROTECT, db_column="nature_id"
    )
    sens = models.TextField(null=True, blank=True, choices=SENS)
    correspondant = models.ForeignKey(
        Correspondant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="correspondant_id",
    )

    # Ce que la regle produit : une cotation vers cette structure, portant cette
    # mention. La mention est facultative — coter sans instruction reste coter.
    structure = models.ForeignKey(
        Structure, on_delete=models.PROTECT, db_column="structure_id", related_name="routages"
    )
    mention_type = models.ForeignKey(
        MentionType, null=True, blank=True, on_delete=models.PROTECT, db_column="mention_type_id"
    )

    priorite = models.SmallIntegerField(default=100)
    actif = models.BooleanField(default=True)
    statut = models.TextField(default="hypothese", choices=STATUTS)
    source = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "regle_routage"
        ordering = ["priorite", "id"]
        verbose_name = "regle de routage direct"
        verbose_name_plural = "regles de routage direct"

    def __str__(self) -> str:
        return f"{self.code} → {self.structure_id}"

    @property
    def specificite(self) -> int:
        """
        Le nombre de criteres renseignes.

        C'est ce qui fait qu'une regle « facture de tel fournisseur » l'emporte
        sur « toute facture arrivee », sans qu'aucune priorite n'ait a etre
        maintenue a la main.
        """
        return sum(
            1
            for critere in (self.nature_id, self.sens, self.correspondant_id)
            if critere is not None
        )


class RubriqueClassement(models.Model):
    """
    Le plan de classement — RF-GED-07.

    L'arborescence metier dans laquelle les documents se rangent. **Distincte
    du referentiel de conservation**, qui dit combien de temps on les garde :
    l'un range, l'autre elimine. Les confondre reviendrait a supprimer un
    dossier parce qu'on a reorganise une rubrique.

    Le rattachement est un arbre libre, comme l'organigramme, et pour la meme
    raison : le nombre d'etages n'est pas connu d'avance et une profondeur
    ecrite en dur serait fausse a la premiere refonte du plan.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, db_column="parent_id"
    )
    #: Les typologies documentaires qui se rangent dans cette rubrique. Un
    #: tableau de textes et non une table de liaison : la typologie n'a pas de
    #: referentiel a ce jour, et en creer un vide n'aiderait personne.
    typologies = models.JSONField(default=list, blank=True)
    ordre = models.SmallIntegerField(default=0)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "rubrique_classement"
        ordering = ["ordre", "code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.libelle}"


class SeuilAlerte(models.Model):
    """
    Une alerte automatique sur depassement de seuil — RF-BI-05, RF-ADM-04.

    **Le destinataire n'est pas facultatif.** Sans lui, une alerte n'est qu'une
    couleur a l'ecran : quelqu'un doit etre prevenu, et c'est ce qui distingue
    un seuil d'un simple affichage conditionnel.

    Le perimetre est un texte et non une cle vers `structure` : un seuil porte
    souvent sur « toutes les directions » ou « les courriers confidentiels »,
    qui ne sont pas des lignes de l'organigramme.
    """

    OPERATEURS = [
        ("superieur", "supérieur à"),
        ("inferieur", "inférieur à"),
    ]
    CANAUX = [
        ("notification", "Notification interne"),
        ("courriel", "Courriel"),
        ("les_deux", "Les deux"),
    ]

    indicateur = models.TextField()
    perimetre = models.TextField(default="Toutes structures")
    operateur = models.TextField(choices=OPERATEURS)
    valeur = models.DecimalField(max_digits=12, decimal_places=2)
    unite = models.TextField(default="")
    #: Le poste prevenu. Un poste et non un agent : la personne change, la
    #: responsabilite reste — meme principe que pour l'organigramme.
    destinataire = models.ForeignKey(
        Poste,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="destinataire_poste_id",
        related_name="seuils",
    )
    #: Reste renseigne quand aucun poste ne convient (« CODIR », qui est une
    #: instance et non un poste).
    destinataire_libelle = models.TextField(null=True, blank=True)
    canal = models.TextField(choices=CANAUX, default="notification")
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "seuil_alerte"
        ordering = ["indicateur"]

    def __str__(self) -> str:
        return f"{self.indicateur} {self.get_operateur_display()} {self.valeur}"

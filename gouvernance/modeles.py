"""
Modeles du pilier gouvernance.

Reflet de `migrations/sql/0001_gouvernance.sql`, jamais sa source : c'est
PostgreSQL qui tient le schema (ADR 003).

**Le modele central est `Engagement`** — ADR 006. Decision d'instance,
prescription de filiale et recommandation d'une organisation exterieure sont un
seul objet, distingue par sa colonne `origine`. Ce sont les memes champs et le
meme suivi ; trois tables jumelles auraient triple chaque regle, et garanti
qu'un jour deux ecrans afficheraient deux chiffres.

La table est l'ancienne `decision_reunion`, livree avec le pilier activites pour
le §19 et renommee. Une decision du CODIR qui suspend une activite reste ainsi
**la meme ligne** que celle que la gouvernance suit.

Deux choses vivent au moteur et ne se reecrivent pas ici :

 * la **reference** (`DEC-2026-0001`, `PRE-…`, `REC-…`) est posee par
   declencheur, sous verrou d'avis ;
 * l'**avancement** d'un engagement est la moyenne de ses structures chargees,
   recalculee par declencheur.

Et l'**etat affiche** ne se stocke pas : il se lit dans `VueEngagementEtat`,
selon l'arbitrage n° 2 comme pour les activites.
"""

import uuid

from django.db import models
from django.db.models import ExpressionWrapper, Q

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.pieces.modeles import PieceJointe

# =====================================================================
#  Seances
# =====================================================================


class Seance(models.Model):
    """
    Reunion, session ou rapport dont la DSR tient le secretariat — §3.3.

    `echeance_depot` n'est pas decorative : un compte rendu rendu trois mois
    plus tard ne sert plus a personne. « Hors delai » se deduit d'elle et de la
    date de depot constatee, et ne se stocke jamais.
    """

    REUNION_DG = "reunion_dg"
    SESSION_CA = "session_ca"
    ASSEMBLEE_GENERALE = "assemblee_generale"
    CODIR = "codir"
    RAPPORT_ACTIVITE = "rapport_activite"
    RAPPORT_SECTORIEL = "rapport_sectoriel"

    TYPES = [
        (REUNION_DG, "Reunion presidee par le DG"),
        (SESSION_CA, "Session du Conseil d'administration"),
        (ASSEMBLEE_GENERALE, "Assemblee generale"),
        (CODIR, "CODIR"),
        (RAPPORT_ACTIVITE, "Rapport d'activite"),
        (RAPPORT_SECTORIEL, "Rapport sectoriel"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference = models.TextField(unique=True)
    type_seance = models.TextField(choices=TYPES)
    intitule = models.TextField()
    date_seance = models.DateField()
    president = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="president_id",
        related_name="seances_presidees",
    )
    #: Borne la visibilite de la seance, comme le plan borne celle d'une activite.
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    echeance_depot = models.DateField()

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "seance"
        ordering = ["-date_seance"]

    def __str__(self) -> str:
        return f"{self.reference} — {self.intitule}"


class SeancePoint(models.Model):
    """Un point de l'ordre du jour."""

    seance = models.ForeignKey(
        Seance, on_delete=models.CASCADE, db_column="seance_id", related_name="points"
    )
    rang = models.SmallIntegerField()
    point = models.TextField()
    rapporteur = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.PROTECT, db_column="rapporteur_id"
    )

    class Meta:
        db_table = "seance_point"
        ordering = ["seance", "rang"]
        verbose_name = "point d'ordre du jour"
        verbose_name_plural = "points d'ordre du jour"


class SeanceParticipant(models.Model):
    """
    Convoque et present sont deux choses.

    Un directeur convoque et absent est precisement ce que la DSR doit voir :
    c'est le lien entre le registre des seances et celui des disponibilites.
    """

    seance = models.ForeignKey(
        Seance, on_delete=models.CASCADE, db_column="seance_id", related_name="participants"
    )
    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, db_column="utilisateur_id"
    )
    present = models.BooleanField(default=True)
    excuse = models.BooleanField(default=False)

    class Meta:
        db_table = "seance_participant"
        verbose_name = "participant a une seance"
        verbose_name_plural = "participants aux seances"


class SeanceDocument(models.Model):
    """
    Ordre du jour, compte rendu, proces-verbal, dossier, rapport.

    Le fichier vit dans `piece_jointe`, comme partout ailleurs : une seconde
    table de pieces aurait fait diverger l'empreinte, le versionnement et la
    reconnaissance optique.
    """

    NATURES = [
        ("ordre_du_jour", "Ordre du jour"),
        ("compte_rendu", "Compte rendu"),
        ("proces_verbal", "Proces-verbal"),
        ("dossier_seance", "Dossier de seance"),
        ("rapport", "Rapport"),
    ]

    seance = models.ForeignKey(
        Seance, on_delete=models.CASCADE, db_column="seance_id", related_name="documents"
    )
    nature = models.TextField(choices=NATURES)
    libelle = models.TextField()
    piece_jointe = models.ForeignKey(
        PieceJointe, null=True, blank=True, on_delete=models.PROTECT, db_column="piece_jointe_id"
    )
    depose_le = models.DateField(null=True, blank=True)
    depose_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="depose_par",
        related_name="documents_deposes",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "seance_document"
        verbose_name = "document de seance"
        verbose_name_plural = "documents de seance"


# =====================================================================
#  Entites exterieures
# =====================================================================


class EntiteExterne(models.Model):
    """
    Filiale ou succursale du PAD — §3.3.

    **La DSR n'y siege pas** : elle prepare les dossiers de session et verifie
    ensuite que ce qui a ete prescrit est execute. D'ou les deux moities de
    l'ecran : l'amont (le dossier est-il pret) et l'aval (la prescription
    est-elle suivie d'effet).
    """

    NATURES = [("filiale", "Filiale"), ("succursale", "Succursale")]

    sigle = models.TextField(unique=True)
    libelle = models.TextField()
    nature = models.TextField(choices=NATURES)
    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "entite_externe"
        ordering = ["sigle"]
        verbose_name = "entite exterieure"
        verbose_name_plural = "entites exterieures"

    def __str__(self) -> str:
        return self.sigle


class OrganeGestion(models.Model):
    """
    Conseil, assemblee ou comite d'une entite.

    `prochaine_session` porte la session **a venir**, une seule a la fois :
    c'est ce que le front suit. Modeliser l'historique des sessions passees
    serait ajouter une table que rien ne lit — les prescriptions portent deja
    leur session d'origine.
    """

    ORGANES = [
        ("conseil_administration", "Conseil d'administration"),
        ("assemblee_generale", "Assemblee generale"),
        ("comite_gestion", "Comite de gestion"),
    ]

    ETATS = [
        ("a_preparer", "A preparer"),
        ("dossier_en_cours", "Dossier en cours"),
        ("dossier_transmis", "Dossier transmis"),
        ("tenue", "Tenue"),
    ]

    entite_externe = models.ForeignKey(
        EntiteExterne,
        on_delete=models.PROTECT,
        db_column="entite_externe_id",
        related_name="organes",
    )
    organe = models.TextField(choices=ORGANES)
    prochaine_session = models.DateField(null=True, blank=True)
    etat_preparation = models.TextField(choices=ETATS, default="a_preparer")
    documents_attendus = models.SmallIntegerField(default=0)
    documents_recus = models.SmallIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "organe_gestion"
        verbose_name = "organe de gestion"
        verbose_name_plural = "organes de gestion"


class OrganisationExterne(models.Model):
    """Organisation ou le PAD est represente — §3.3."""

    NATURES = [
        ("comite_national", "Comite national"),
        ("organisation_portuaire", "Organisation portuaire"),
        ("association_professionnelle", "Association professionnelle"),
        ("groupement", "Groupement"),
    ]

    sigle = models.TextField(unique=True)
    libelle = models.TextField()
    nature = models.TextField(choices=NATURES)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "organisation_externe"
        ordering = ["sigle"]
        verbose_name = "organisation exterieure"
        verbose_name_plural = "organisations exterieures"

    def __str__(self) -> str:
        return self.sigle


class Representation(models.Model):
    """
    Le mandat : qui nous represente, jusqu'a quand, avec quelle assiduite.

    `reunions_tenues` et `reunions_participees` sont **deux compteurs et non une
    table de presences** : aucun ecran ne saisit la presence reunion par
    reunion, et une table que rien n'alimente resterait vide en affichant un
    taux faux.
    """

    organisation_externe = models.ForeignKey(
        OrganisationExterne,
        on_delete=models.PROTECT,
        db_column="organisation_externe_id",
        related_name="representations",
    )
    representant = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="representant_id",
        related_name="representations",
    )
    suppleant = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="suppleant_id",
        related_name="suppleances",
    )
    mandat_du = models.DateField()
    mandat_au = models.DateField()
    reunions_tenues = models.SmallIntegerField(default=0)
    reunions_participees = models.SmallIntegerField(default=0)
    #: Ce que l'institution retire de sa presence. Vide tant que rien n'est
    #: declare : inventer un apport serait pire que le silence.
    apport = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "representation"
        ordering = ["organisation_externe"]


# =====================================================================
#  Engagement — ADR 006
# =====================================================================


class Engagement(models.Model):
    """
    Ce qu'une autorite a decide et qu'il faut suivre jusqu'a son execution.

    **Un seul objet, trois origines** (ADR 006) :

     * `instance` — une decision du conseil, du CODIR, du DG ou de l'assemblee,
       issue d'une seance ;
     * `organe_filiale` — une prescription du conseil ou du comite de gestion
       d'une filiale ;
     * `organisation_externe` — un avis ou une recommandation d'une
       organisation ou le PAD siege.

    Le suivi est identique dans les trois cas : un objet, une echeance, des
    structures internes chargees, un avancement, un etat. Ce qui differe est la
    provenance, et une contrainte du moteur garantit qu'**une et une seule** est
    renseignee — un engagement sans origine ne serait rattachable a aucun ecran.

    La reference et l'avancement viennent de declencheurs. L'etat affiche ne se
    stocke pas : voir `VueEngagementEtat`.
    """

    INSTANCE = "instance"
    ORGANE_FILIALE = "organe_filiale"
    ORGANISATION_EXTERNE = "organisation_externe"

    ORIGINES = [
        (INSTANCE, "Decision d'instance"),
        (ORGANE_FILIALE, "Prescription d'un organe de filiale"),
        (ORGANISATION_EXTERNE, "Recommandation d'une organisation exterieure"),
    ]

    INSTANCES = [
        ("conseil_administration", "Conseil d'administration"),
        ("codir", "CODIR"),
        ("directeur_general", "Directeur general"),
        ("assemblee_generale", "Assemblee generale"),
    ]

    #: Posee par declencheur : `DEC-2026-0001`, `PRE-…`, `REC-…`. Jamais saisie.
    reference = models.TextField(unique=True, null=True, blank=True, editable=False)
    origine = models.TextField(choices=ORIGINES, default=INSTANCE)
    #: Renseignee pour la seule origine `instance` : une recommandation d'une
    #: organisation portuaire n'est pas rendue par le CODIR.
    instance = models.TextField(choices=INSTANCES, null=True, blank=True)

    seance = models.ForeignKey(
        Seance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="seance_id",
        related_name="engagements",
    )
    organe_gestion = models.ForeignKey(
        OrganeGestion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="organe_gestion_id",
        related_name="prescriptions",
    )
    organisation_externe = models.ForeignKey(
        OrganisationExterne,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="organisation_externe_id",
        related_name="recommandations",
    )

    date_engagement = models.DateField()
    objet = models.TextField()
    texte = models.TextField(null=True, blank=True)
    contexte = models.TextField(null=True, blank=True)
    echeance = models.DateField(null=True, blank=True)

    #: L'autorite qui decide. Ne jamais confondre avec `saisie_par`, l'agent qui
    #: consigne — meme regle que `cotation.decide_par`.
    prise_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="prise_par",
        related_name="engagements_pris",
    )
    saisie_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="saisie_par",
        related_name="engagements_saisis",
    )

    #: Moyenne des structures chargees, posee par declencheur. Ne pas ecrire.
    avancement = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    suspendu_le = models.DateTimeField(null=True, blank=True)
    suspendu_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="suspendu_par",
        related_name="engagements_suspendus",
    )
    motif_suspension = models.TextField(null=True, blank=True)
    execute_le = models.DateTimeField(null=True, blank=True)
    execute_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="execute_par",
        related_name="engagements_executes",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "engagement"
        ordering = ["-date_engagement"]

    def __str__(self) -> str:
        return f"{self.reference or '(sans reference)'} — {self.objet}"


class EngagementStructure(models.Model):
    """
    Une structure chargee de l'engagement, et ou elle en est.

    **Rang 1 = structure pilote** : celle qui rend compte. Meme regle que le
    chef de file d'une cotation, et meme raison — sans pilote designe, personne
    ne repond quand l'instance demande ou cela en est.
    """

    engagement = models.ForeignKey(
        Engagement,
        on_delete=models.CASCADE,
        db_column="engagement_id",
        related_name="structures",
    )
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    rang = models.SmallIntegerField()
    #: **Colonne generee par la base** (`rang = 1`), declaree comme telle.
    #: Un `BooleanField` ordinaire serait envoye dans chaque `INSERT` et
    #: PostgreSQL refuserait : « cannot insert a non-DEFAULT value into column
    #: pilote ». `GeneratedField` dit a Django de ne jamais l'ecrire.
    pilote = models.GeneratedField(
        # `ExpressionWrapper` et non un `Q` nu : Django accepte les deux a
        # l'execution, mais `Q` n'est pas une `Expression` et le verificateur
        # de types le refuse a juste titre.
        expression=ExpressionWrapper(Q(rang=1), output_field=models.BooleanField()),
        output_field=models.BooleanField(),
        db_persist=True,
    )
    avancement = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "engagement_structure"
        ordering = ["engagement", "rang"]
        verbose_name = "structure chargee"
        verbose_name_plural = "structures chargees"


class EngagementJalon(models.Model):
    """Une etape datee de l'execution."""

    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, db_column="engagement_id", related_name="jalons"
    )
    structure = models.ForeignKey(
        Structure, null=True, blank=True, on_delete=models.PROTECT, db_column="structure_id"
    )
    libelle = models.TextField()
    echeance = models.DateField()
    fait_le = models.DateField(null=True, blank=True)
    ordre = models.SmallIntegerField(default=1)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "engagement_jalon"
        ordering = ["engagement", "ordre"]
        verbose_name = "jalon d'engagement"
        verbose_name_plural = "jalons d'engagement"


class EngagementObservation(models.Model):
    """
    Le fil de suivi.

    **Une relance de la DSR n'est pas une observation ordinaire** : elle se voit
    et elle se compte. D'ou le drapeau plutot qu'une seconde table — les deux
    s'affichent dans le meme fil, dans l'ordre.
    """

    engagement = models.ForeignKey(
        Engagement,
        on_delete=models.CASCADE,
        db_column="engagement_id",
        related_name="observations",
    )
    texte = models.TextField()
    relance = models.BooleanField(default=False)
    #: **Nul pour une relance automatique** : personne ne l'a signee, et lui
    #: attribuer un agent serait faux. Meme regle que `relance.emetteur_id` pour
    #: le courrier. Une contrainte du moteur garantit qu'une observation sans
    #: auteur est bien une relance — une remarque anonyme n'aurait aucun sens.
    auteur = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.PROTECT, db_column="auteur_id"
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "engagement_observation"
        ordering = ["-cree_le"]
        verbose_name = "observation d'engagement"
        verbose_name_plural = "observations d'engagement"


# =====================================================================
#  Disponibilite et conges
# =====================================================================


class Disponibilite(models.Model):
    """
    Une absence decidee d'un haut responsable — §3.3.

    **Une decision confiee a un directeur en mission n'avancera pas** : c'est ce
    registre qui le dit avant qu'on ne s'en apercoive.

    Une absence **sans interimaire designe** est le point que la DSR doit voir :
    les dossiers de la structure s'arretent. Deux absences ne se chevauchent pas
    pour un meme agent — contrainte d'exclusion GiST, comme pour le rattachement
    a une session courrier.
    """

    TYPES = [
        ("conge_annuel", "Conge annuel"),
        ("mission", "Mission"),
        ("interim", "Interim"),
        ("formation", "Formation"),
        ("absence_exceptionnelle", "Absence exceptionnelle"),
    ]

    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="utilisateur_id",
        related_name="absences",
    )
    type_absence = models.TextField(choices=TYPES)
    du = models.DateField()
    au = models.DateField()
    motif = models.TextField(null=True, blank=True)
    interimaire = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="interimaire_id",
        related_name="interims",
    )
    saisi_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="saisi_par",
        related_name="absences_saisies",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "disponibilite"
        ordering = ["-du"]


class CongeDroit(models.Model):
    """
    Les droits a conges d'un **agent** pour une annee.

    Ouverts par le directeur de sa tete de structure, pour tout son sous-arbre
    — la sous-structure n'existe pas au-dessus de son chef. La DSR conserve
    l'arbitrage du planning des directeurs eux-memes : c'est le meme ecran, vu
    depuis une portee plus large.

    Le nombre de jours **vient de la DRH** : l'anciennete, les reports et les
    majorations sont son affaire. Le calculer ici reviendrait a redire une regle
    dont ce systeme n'est pas depositaire.
    """

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, db_column="utilisateur_id", related_name="conges"
    )
    annee = models.SmallIntegerField()
    droits_jours = models.SmallIntegerField(default=30)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "conge_droit"
        ordering = ["-annee"]
        verbose_name = "droit a conges"
        verbose_name_plural = "droits a conges"


class CongePeriode(models.Model):
    """
    Une periode souhaitee, arbitree, validee ou reportee.

    **A ne pas confondre avec une absence.** `Disponibilite` enregistre une
    absence decidee ; ceci arbitre des souhaits avant qu'ils ne le deviennent.
    C'est l'ecran ou l'on voit qu'un depart prive une direction de toute sa
    ligne hierarchique en meme temps.

    Un report sans motif ne se corrige pas : l'agent resoumettra la meme
    periode. Meme regle que le renvoi d'un plan d'actions.
    """

    SOUHAITE = "souhaite"
    ARBITRE = "arbitre"
    VALIDE = "valide"
    REPORTE = "reporte"

    ETATS = [
        (SOUHAITE, "Souhaite"),
        (ARBITRE, "Arbitre"),
        (VALIDE, "Valide"),
        (REPORTE, "Reporte"),
    ]

    conge_droit = models.ForeignKey(
        CongeDroit, on_delete=models.CASCADE, db_column="conge_droit_id", related_name="periodes"
    )
    du = models.DateField()
    au = models.DateField()
    etat = models.TextField(choices=ETATS, default=SOUHAITE)
    motif_report = models.TextField(null=True, blank=True)
    arbitre_le = models.DateTimeField(null=True, blank=True)
    arbitre_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="arbitre_par",
        related_name="conges_arbitres",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "conge_periode"
        ordering = ["du"]
        verbose_name = "periode de conges"
        verbose_name_plural = "periodes de conges"


# =====================================================================
#  Agregat et vue
# =====================================================================


class AgregatGouvernanceJour(models.Model):
    """
    Alimente par tache planifiee nocturne.

    Meme regle que pour le courrier et les activites : le tableau de bord
    n'agrege jamais a la volee. Et le retard evolue avec le temps sans qu'aucune
    ecriture ne survienne — sans ce recalcul, seuls les engagements que
    quelqu'un a touches paraitraient en retard.
    """

    pk = models.CompositePrimaryKey("jour", "origine", "instance")
    jour = models.DateField()
    origine = models.TextField()
    #: Chaine vide et non nul : la colonne est dans la clef primaire.
    instance = models.TextField(default="")

    nb_total = models.IntegerField(default=0)
    nb_a_lancer = models.IntegerField(default=0)
    nb_en_cours = models.IntegerField(default=0)
    nb_executes = models.IntegerField(default=0)
    nb_en_retard = models.IntegerField(default=0)
    nb_suspendus = models.IntegerField(default=0)
    depots_en_souffrance = models.IntegerField(default=0)
    absences_sans_interim = models.IntegerField(default=0)
    calcule_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agregat_gouvernance_jour"
        verbose_name = "agregat de gouvernance du jour"
        verbose_name_plural = "agregats de gouvernance du jour"


class VueEngagementEtat(models.Model):
    """
    L'etat **affiche** d'un engagement — une vue, pas une table.

    Cinq etats affiches, deux stockes (`suspendu_le`, `execute_le`). Les trois
    autres se deduisent : « en retard » de l'echeance (arbitrage n° 2), « a
    lancer » d'un avancement nul, « en cours » du reste. Les stocker imposerait
    de reecrire toutes les lignes chaque nuit pour un resultat que la date donne
    deja.

    `jalon_echu` distingue un engagement qui prend du retard d'un engagement
    qu'on a oublie — c'est le meme raisonnement que la criticite du §20.
    """

    id = models.BigIntegerField(primary_key=True)
    origine = models.TextField()
    instance = models.TextField(null=True)
    etat_affiche = models.TextField()
    avancement = models.DecimalField(max_digits=5, decimal_places=2)
    relances = models.IntegerField()
    jalon_echu = models.BooleanField()

    class Meta:
        db_table = "v_engagement_etat"
        managed = False
        verbose_name = "etat affiche d'un engagement"
        verbose_name_plural = "etats affiches des engagements"

"""
Modeles du pilier activites.

Ils sont le **reflet** de `migrations/sql/0001_activite.sql`, jamais sa source :
c'est PostgreSQL qui tient le schema (ADR 003). Toute colonne ajoutee ici sans
l'etre en SQL produirait une migration qui recree ce qui existe deja.

Trois choses vivent au moteur et n'ont pas a etre reecrites en Python :

 * le **code** de l'activite (`PAA-<structure>-<numero>`) est pose par le
   declencheur `attribuer_code_activite()`, sous verrou de ligne sur le plan ;
 * l'**avancement** est la somme des valeurs obtenues des taches, posee par
   `maj_avancement_activite()` a chaque ecriture de tache — RG-7, ADR 049.
   Il ne se saisit jamais au niveau de l'activite ;
 * le **taux retenu** (`avancement_retenu`) est une colonne generee :
   `COALESCE(avancement_recalibre, avancement_calcule)`. `avancement_recalibre`
   est lui-meme la somme des valeurs retenues des taches, des qu'une tache est
   recalibree. Le declare et le retenu restent deux colonnes distinctes parce
   que le desaccord entre la structure et la DSR doit rester lisible — ADR 030 ;
 * la **date de realisation** d'une tache suit sa valeur obtenue, par
   `dater_realisation_tache()` ;
 * l'**etat de suspension** suit la table `activite_suspension` par
   `maj_etat_suspension()`. Le code applicatif ne doit **jamais** ecrire
   `activite.etat = 'suspendue'` directement : la suspension est la source,
   l'etat suit.

Et deux choses ne sont pas stockees, conformement a l'arbitrage n° 2 : le
**retard** et l'etat **programmee**. Ils se deduisent des dates, et se lisent
par `VueActiviteEtat`. Une colonne d'etat serait fausse le lendemain de son
ecriture sans qu'aucune ecriture ne survienne.
"""

import uuid

from django.db import models
from django.db.models.functions import Coalesce

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.pieces.modeles import PieceJointe

# =====================================================================
#  Referentiel du plan strategique
# =====================================================================


class AxeStrategique(models.Model):
    """
    Referentiel **ferme**, arrete et communique par la Direction generale le
    11 aout 2026. Le §15 exigeait le rattachement sans jamais donner la liste :
    un champ libre aurait produit quatre orthographes pour un meme axe, et tout
    regroupement par axe — c'est-a-dire la raison d'etre du rattachement —
    aurait ete faux.
    """

    code = models.TextField(unique=True)
    #: Ce qui circule dans les listes et les regroupements.
    libelle_court = models.TextField()
    #: Le libelle officiel, long, affiche sur la fiche seulement.
    libelle = models.TextField()
    ordre = models.SmallIntegerField()

    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "axe_strategique"
        ordering = ["ordre"]
        verbose_name = "axe strategique"
        verbose_name_plural = "axes strategiques"

    def __str__(self) -> str:
        return self.libelle_court


# =====================================================================
#  Exercice et plan d'actions annuel
# =====================================================================


class Exercice(models.Model):
    """
    L'annee de gestion. Table et non colonne : un exercice se clot, et une fois
    clos plus aucune activite ne s'y ajoute. Sans cet etat, rien n'empeche la
    saisie retroactive dans une annee dont les comptes sont rendus.
    """

    annee = models.SmallIntegerField(unique=True)
    ouvert = models.BooleanField(default=True)
    ouvert_le = models.DateTimeField(auto_now_add=True)
    clos_le = models.DateTimeField(null=True, blank=True)
    clos_par = models.BigIntegerField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "exercice"
        ordering = ["-annee"]

    def __str__(self) -> str:
        return str(self.annee)


class PlanActions(models.Model):
    """
    Le plan d'actions annuel : un par structure et par exercice, valide par la
    Direction du Controle de Gestion (§15).

    **Quatre statuts et non deux.** Le modele de donnees v2 prevoyait
    `non_valide` / `valide` ; les ecrans exigent de distinguer ce qui n'a pas
    encore ete soumis de ce qui attend le controle de gestion, et de porter le
    motif d'un renvoi. Un plan renvoye sans motif n'est pas corrige : il est
    resoumis a l'identique.

    **Le cycle lui-meme n'est pas arbitre** — retour arriere, avenant en cours
    d'annee, modification d'un plan valide ne sont decrits par aucun document.
    Voir docs/questions-ouvertes.md, A5.
    """

    BROUILLON = "brouillon"
    SOUMIS = "soumis"
    VALIDE = "valide"
    RETOURNE = "retourne"

    STATUTS = [
        (BROUILLON, "Brouillon"),
        (SOUMIS, "Soumis au controle de gestion"),
        (VALIDE, "Valide"),
        (RETOURNE, "Retourne"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, db_column="exercice_id")
    version = models.SmallIntegerField(default=1)
    statut = models.TextField(choices=STATUTS, default=BROUILLON)

    soumis_le = models.DateTimeField(null=True, blank=True)
    soumis_par = models.BigIntegerField(null=True, blank=True)
    valide_le = models.DateTimeField(null=True, blank=True)
    valide_par = models.BigIntegerField(null=True, blank=True)
    #: Obligatoire au renvoi — contrainte `paa_retour_motive` au moteur.
    motif_retour = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "paa"
        verbose_name = "plan d'actions annuel"
        verbose_name_plural = "plans d'actions annuels"

    def __str__(self) -> str:
        return f"PAA {self.structure} {self.exercice}"


class PlanActionsVersion(models.Model):
    """
    L'historique des soumissions successives.

    `champ_historique` dit quelle colonne a change ; celle-ci dit **pourquoi une
    version entiere a ete refaite**, et c'est cela que lit un controleur de
    gestion.
    """

    plan = models.ForeignKey(
        PlanActions, on_delete=models.CASCADE, db_column="paa_id", related_name="versions"
    )
    version = models.SmallIntegerField()
    statut = models.TextField()
    motif = models.TextField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "paa_version"
        ordering = ["plan", "version"]
        verbose_name = "version de plan"
        verbose_name_plural = "versions de plan"


# =====================================================================
#  Activite
# =====================================================================


class Activite(models.Model):
    """
    Une action inscrite au plan d'actions annuel d'une structure — §15.

    **La structure porteuse n'est pas une colonne** : elle vient du plan
    (`plan.structure_id`). La dupliquer ici ferait exister deux verites, et
    c'est la visibilite de l'activite qui en depend.

    Elle n'est pas la seule pour autant : `ActiviteStructure` porte les
    structures **associees**, celles qui repondent de l'activite sans la tenir
    a leur plan (ADR 047). Le responsable nomme, lui, n'est plus qu'un point
    focal facultatif.

    `budget_valide` et `budget_consomme` sont modelises sans ecran de suivi —
    decision de cadrage D8 : « le suivi budgetaire sort du perimetre de la V1,
    les montants restent modelisables ». La source de `budget_consomme` n'est
    pas determinee : saisie ou reprise depuis le systeme financier.
    """

    EN_COURS = "en_cours"
    REALISEE = "realisee"
    SUSPENDUE = "suspendue"

    ETATS = [
        (EN_COURS, "En cours"),
        (REALISEE, "Realisee"),
        (SUSPENDUE, "Suspendue"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    plan = models.ForeignKey(
        PlanActions, on_delete=models.PROTECT, db_column="paa_id", related_name="activites"
    )
    axe_strategique = models.ForeignKey(
        AxeStrategique, on_delete=models.PROTECT, db_column="axe_strategique_id"
    )
    #: Pose par le declencheur `attribuer_code_activite()`. Jamais saisi.
    code = models.TextField(unique=True, editable=False)
    intitule = models.TextField()
    objectif = models.TextField(null=True, blank=True)
    etat_reference = models.TextField(null=True, blank=True)
    resultats_attendus = models.TextField(null=True, blank=True)
    cible = models.TextField(null=True, blank=True)
    budget_valide = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    budget_consomme = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    #: **Point focal, et non porteur.** La responsabilite est institutionnelle :
    #: elle se lit sur `plan.structure` et `structures_associees` — ADR 047.
    #: Facultatif depuis lors : une activite peut n'avoir que des structures.
    responsable = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="responsable_id",
        related_name="activites_dont_responsable",
        null=True,
        blank=True,
    )
    date_debut = models.DateField()
    date_fin = models.DateField()
    #: Trois etats stockes. « En retard » et « Programmee » se deduisent des
    #: dates — voir `VueActiviteEtat`.
    etat = models.TextField(choices=ETATS, default=EN_COURS)
    #: **Somme des valeurs obtenues des taches** — RG-7, ADR 049. Posee par le
    #: declencheur ; ne jamais l'ecrire depuis le code applicatif. C'est **ce que
    #: la structure declare**, jamais ce que la DSR retient.
    avancement_calcule = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    #: Somme des valeurs **retenues** des taches, des qu'au moins une est
    #: recalibree ; `None` sinon. Pose par le declencheur, comme le precedent.
    #: Le motif, la date et l'auteur vivent sur chaque tache recalibree.
    avancement_recalibre = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    #: **Colonne generee par la base** : `COALESCE(recalibre, calcule)`.
    #: C'est elle qui fait foi partout — tableaux de bord, scores, agregats.
    #:
    #: `GeneratedField` et non `DecimalField` : un champ ordinaire partirait
    #: dans chaque `UPDATE` et PostgreSQL refuserait — « cannot insert a
    #: non-DEFAULT value into column avancement_retenu ». Meme piege que
    #: `EngagementStructure.pilote`.
    avancement_retenu = models.GeneratedField(
        expression=Coalesce("avancement_recalibre", "avancement_calcule"),
        output_field=models.DecimalField(max_digits=5, decimal_places=2),
        db_persist=True,
    )
    derniere_relance_le = models.DateTimeField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "activite"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.intitule}"


class ActiviteStructure(models.Model):
    """
    Une structure **associee** a une activite — ADR 047.

    La table ne porte que les associees. La porteuse reste `plan.structure` et
    n'y figure jamais : l'y ecrire ferait exister deux verites sur la seule
    chose dont depend le rattachement au plan.

    Le retrait est **logique** (`invalide_le`) : savoir qui repondait de
    l'activite au trimestre precedent fait partie de ce que la fiche de vie
    doit pouvoir montrer. L'unicite au moteur est partielle — une structure
    retiree peut etre rattachee de nouveau.
    """

    activite = models.ForeignKey(
        Activite,
        on_delete=models.CASCADE,
        db_column="activite_id",
        related_name="structures_associees",
    )
    structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        db_column="structure_id",
        related_name="activites_associees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "activite_structure"
        verbose_name = "structure associee a une activite"
        verbose_name_plural = "structures associees a une activite"

    def __str__(self) -> str:
        return f"{self.activite.code} — {self.structure}"


# =====================================================================
#  Indicateurs et mesures
# =====================================================================


class ActiviteIndicateur(models.Model):
    """
    Ce que l'activite promet de faire bouger : `valeur_reference` est le point
    de depart constate, `valeur_cible` le point d'arrivee vise.

    Les deux sont numeriques et non textuelles : sans cela aucun taux
    d'atteinte n'est calculable, et le §16 comme le §20 en demandent un.
    Consequence assumee — un indicateur non chiffrable ne se modelise pas ici.
    """

    activite = models.ForeignKey(
        Activite, on_delete=models.CASCADE, db_column="activite_id", related_name="indicateurs"
    )
    libelle = models.TextField()
    unite = models.TextField(null=True, blank=True)
    valeur_reference = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    valeur_cible = models.DecimalField(max_digits=18, decimal_places=4)
    #: Vrai lorsque atteindre la cible signifie **descendre** : un delai, un
    #: taux d'erreur, un encours. Sans ce drapeau, le taux d'atteinte d'un
    #: indicateur decroissant est faux sans que rien ne le signale.
    sens_decroissant = models.BooleanField(default=False)
    ordre = models.SmallIntegerField(default=1)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "activite_indicateur"
        ordering = ["activite", "ordre"]
        verbose_name = "indicateur d'activite"
        verbose_name_plural = "indicateurs d'activite"

    def __str__(self) -> str:
        return self.libelle


class IndicateurMesure(models.Model):
    """
    Un releve date. On n'ecrase jamais la valeur precedente : c'est la suite des
    mesures qui montre une progression, et le §16 demande le niveau
    d'execution, pas seulement le dernier chiffre.

    Un seul releve par jour et par indicateur — deux releves le meme jour
    signifient une correction : elle remplace, elle ne s'ajoute pas.
    """

    activite_indicateur = models.ForeignKey(
        ActiviteIndicateur,
        on_delete=models.CASCADE,
        db_column="activite_indicateur_id",
        related_name="mesures",
    )
    date_mesure = models.DateField()
    valeur_atteinte = models.DecimalField(max_digits=18, decimal_places=4)
    commentaire = models.TextField(null=True, blank=True)
    saisie_par = models.ForeignKey(Utilisateur, on_delete=models.PROTECT, db_column="saisie_par")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "indicateur_mesure"
        ordering = ["-date_mesure"]
        verbose_name = "mesure d'indicateur"
        verbose_name_plural = "mesures d'indicateur"


# =====================================================================
#  Taches
# =====================================================================


class Tache(models.Model):
    """
    Les « taches a realiser » du §15 — **elles seules portent l'avancement**.

    Depuis l'ADR 049, l'activite est une grandeur derivee :

     * chaque tache a une **valeur prevue**, sa part de l'activite en points de
       pourcentage (RG-2), et les taches en vigueur d'une activite totalisent
       exactement 100 (RG-3) ;
     * la structure declare une **valeur obtenue**, dans la meme echelle, et
       cumulative : chaque declaration remplace la precedente (RG-5). Elle ne
       depasse jamais la valeur prevue (RG-6) ;
     * l'avancement de l'activite est la somme brute des valeurs obtenues
       (RG-7), et le declencheur `maj_avancement_activite()` la pose.

    Une tache de valeur prevue 30 qui obtient 15 fait avancer l'activite de
    15 points, sans conversion. Son avancement **propre** — 50 % — n'est qu'un
    affichage : `valeur_obtenue / valeur_prevue`.

    Les bornes de chaque ligne sont au moteur ; la somme a 100 (RG-3) et
    l'inclusion dans la periode de l'activite (RG-9) portent sur plusieurs
    lignes ou deux tables, et vivent dans `services.py`. Voir l'ADR 049.
    """

    activite = models.ForeignKey(
        Activite, on_delete=models.CASCADE, db_column="activite_id", related_name="taches"
    )
    intitule = models.TextField()
    #: **Plus alimente — ADR 048.** L'application n'ecrit plus d'attributaire :
    #: une tache se rattache a son activite, et qui en repond se lit sur
    #: l'activite (structures porteuse et associees, ADR 047). La colonne reste
    #: parce que les taches creees jusqu'au 10/09/2026 la portent, et qu'un
    #: `DROP COLUMN` effacerait la reponse a « qui s'en occupait ? ». Aucun
    #: code ne l'ecrit ; aucun ecran ne l'affiche.
    responsable = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="responsable_id",
        related_name="taches_dont_responsable",
    )
    #: RG-2. Part de la tache dans l'activite, en points : `0 < x <= 100`.
    valeur_prevue = models.DecimalField(max_digits=5, decimal_places=2)
    #: RG-5, RG-6. Ce que la structure declare, cumulatif, `<= valeur_prevue`.
    valeur_obtenue = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    #: Ce que la DSR retient pour cette tache. `None` tant qu'elle n'a pas
    #: contredit la structure — ADR 030. Meme plafond que la valeur obtenue.
    valeur_recalibree = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    #: Obligatoire des que `valeur_recalibree` est pose — contrainte au moteur.
    recalibrage_motif = models.TextField(null=True, blank=True)
    recalibre_le = models.DateTimeField(null=True, blank=True)
    recalibre_par = models.BigIntegerField(null=True, blank=True)
    #: **Colonne generee** : `COALESCE(valeur_recalibree, valeur_obtenue)`.
    #: `GeneratedField`, pour la raison dite sur `Activite.avancement_retenu`.
    valeur_retenue = models.GeneratedField(
        expression=Coalesce("valeur_recalibree", "valeur_obtenue"),
        output_field=models.DecimalField(max_digits=5, decimal_places=2),
        db_persist=True,
    )
    #: RG-8. Premier jour du mois de debut, dernier jour du mois de fin.
    date_debut = models.DateField()
    date_fin = models.DateField()
    #: Posee par `dater_realisation_tache()` le jour ou la valeur obtenue
    #: atteint la valeur prevue ; effacee si elle redescend. Jamais ecrite ici.
    fait_le = models.DateField(null=True, blank=True)
    ordre = models.SmallIntegerField(default=1)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "tache"
        ordering = ["activite", "ordre"]

    def __str__(self) -> str:
        return self.intitule

    @property
    def realisee(self) -> bool:
        """La tache a obtenu toute sa part — ce que la structure declare."""
        return self.valeur_obtenue >= self.valeur_prevue


# =====================================================================
#  Instructions et decisions
# =====================================================================


#  `DecisionReunion` a demenage. La table s'appelle desormais `engagement` et
#  le modele vit dans `gouvernance/modeles.py` : decision d'instance,
#  prescription de filiale et recommandation externe sont un seul objet
#  (ADR 006). Le champ garde ici le nom `decision_reunion`, parce que c'est
#  bien ce qu'il designe DANS CE CONTEXTE — le §19 parle des decisions issues
#  des reunions de coordination.


class InstructionActivite(models.Model):
    """
    Le §17 exige quatre attributs pour une instruction verbale du Directeur
    General : l'activite, la date, le responsable, le delai. Une instruction est
    donc un **engagement date**, pas un commentaire.

    D'ou la levee : tant que `levee_le` est nul, l'instruction pese. Une
    instruction echue et non levee est l'une des deux contraintes qui rendent
    une activite critique (§20).

    Le §19 ajoute les decisions du DG. Meme forme, meme suivi : la colonne
    `origine` les distingue plutot que deux tables jumelles.
    """

    INSTRUCTION_VERBALE = "instruction_verbale"
    DECISION_DG = "decision_dg"

    ORIGINES = [
        (INSTRUCTION_VERBALE, "Instruction verbale"),
        (DECISION_DG, "Decision du Directeur General"),
    ]

    activite = models.ForeignKey(
        Activite, on_delete=models.CASCADE, db_column="activite_id", related_name="instructions"
    )
    origine = models.TextField(choices=ORIGINES, default=INSTRUCTION_VERBALE)
    #: Une decision du DG peut naitre hors reunion ; l'inverse est refuse par
    #: le moteur — une instruction verbale ne nait pas d'une reunion.
    decision_reunion = models.ForeignKey(
        "gouvernance.Engagement",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="decision_reunion_id",
    )
    date_instruction = models.DateField()
    texte = models.TextField()
    responsable = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="responsable_id",
        related_name="instructions_dont_responsable",
    )
    echeance = models.DateField()
    donnee_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="donnee_par",
        related_name="instructions_donnees",
    )
    enregistree_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="enregistree_par",
        related_name="instructions_enregistrees",
    )
    levee_le = models.DateTimeField(null=True, blank=True)
    levee_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="levee_par",
        related_name="instructions_levees",
    )
    commentaire_levee = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "instruction_activite"
        ordering = ["echeance"]
        verbose_name = "instruction sur activite"
        verbose_name_plural = "instructions sur activite"


class DecisionEffet(models.Model):
    """
    Ce qu'une decision peut faire, selon le §19 : modifier le planning, modifier
    les priorites, accelerer une activite, la suspendre, creer des taches.

    `valeur_avant` / `valeur_apres` conservent l'etat de part et d'autre, ce qui
    permet de reconstituer le plan dans sa forme d'origine malgre les decisions
    successives. Sans elles, on saurait qu'une decision a ete prise, jamais ce
    qu'elle a change.
    """

    NATURES = [
        ("planning", "Modification du planning"),
        ("priorite", "Modification des priorites"),
        ("acceleration", "Acceleration"),
        ("suspension", "Suspension"),
        ("creation_tache", "Creation de taches"),
    ]

    decision_reunion = models.ForeignKey(
        "gouvernance.Engagement",
        on_delete=models.CASCADE,
        db_column="decision_reunion_id",
        related_name="effets",
    )
    activite = models.ForeignKey(
        Activite, null=True, blank=True, on_delete=models.PROTECT, db_column="activite_id"
    )
    tache = models.ForeignKey(
        Tache, null=True, blank=True, on_delete=models.PROTECT, db_column="tache_id"
    )
    nature = models.TextField(choices=NATURES)
    valeur_avant = models.JSONField(null=True, blank=True)
    valeur_apres = models.JSONField(null=True, blank=True)
    applique_le = models.DateTimeField(null=True, blank=True)
    applique_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="applique_par",
        related_name="effets_appliques",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "decision_effet"
        verbose_name = "effet de decision"
        verbose_name_plural = "effets de decision"


# =====================================================================
#  Suspension
# =====================================================================


class ActiviteSuspension(models.Model):
    """
    Le §19 fait de la suspension un **etat**, pas un simple effet de decision :
    une activite suspendue n'accepte plus de declaration d'avancement, et elle
    reprend. Il faut donc savoir depuis quand, sur quel motif, par qui — et
    pouvoir lever la suspension sans effacer qu'elle a eu lieu.

    **Cette table est la source, `Activite.etat` en est la consequence** : le
    declencheur `maj_etat_suspension()` s'en charge. Une seule suspension
    ouverte a la fois, garantie par index unique partiel — deux suspensions
    ouvertes rendraient la reprise ambigue, et aucun code applicatif ne tient
    cette garantie sous concurrence.
    """

    activite = models.ForeignKey(
        Activite, on_delete=models.CASCADE, db_column="activite_id", related_name="suspensions"
    )
    #: Facultative : une suspension peut etre prononcee hors reunion.
    decision_reunion = models.ForeignKey(
        "gouvernance.Engagement",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="decision_reunion_id",
    )
    motif = models.TextField()
    suspendu_le = models.DateTimeField(auto_now_add=True)
    suspendu_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="suspendu_par",
        related_name="suspensions_prononcees",
    )
    repris_le = models.DateTimeField(null=True, blank=True)
    repris_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="repris_par",
        related_name="suspensions_levees",
    )
    motif_reprise = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "activite_suspension"
        ordering = ["-suspendu_le"]
        verbose_name = "suspension d'activite"
        verbose_name_plural = "suspensions d'activite"


# =====================================================================
#  Calendrier de production et obligations
# =====================================================================


class CalendrierProduction(models.Model):
    """
    Descriptif fonctionnel §3.3 : la DSR decide « qui alimente quoi, a quelle
    frequence ». Sans ce calendrier, chaque ecran redecrit la meme regle de son
    cote et les deux finissent par diverger.
    """

    NATURES = [
        ("rapport_mensuel", "Rapport mensuel d'activite"),
        ("proces_verbal", "Proces-verbal de reunion"),
        ("rapport_sectoriel", "Rapport sectoriel"),
    ]

    PERIODICITES = [
        ("mensuelle", "Mensuelle"),
        ("trimestrielle", "Trimestrielle"),
        ("semestrielle", "Semestrielle"),
        ("annuelle", "Annuelle"),
    ]

    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    nature = models.TextField(choices=NATURES)
    intitule = models.TextField()
    periodicite = models.TextField(choices=PERIODICITES)
    #: Jour de la periode **suivante** ou le depot est attendu : le rapport de
    #: juillet est du le 5 aout.
    jour_echeance = models.SmallIntegerField(default=5)
    #: Le §3.3 demande des « relances automatiques en cas de non-saisie ». Le
    #: calendrier dit qui depose quoi ; ces deux colonnes disent quand on
    #: rappelle a l'ordre. Sans elles, la relance serait un reglage global,
    #: alors qu'un rapport mensuel et un rapport annuel ne se relancent pas au
    #: meme rythme.
    relance_automatique = models.BooleanField(default=True)
    #: Jours **avant** l'echeance ou la relance part. `None` = a l'echeance.
    jours_avant_relance = models.SmallIntegerField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "calendrier_production"
        verbose_name = "ligne de calendrier de production"
        verbose_name_plural = "calendrier de production"

    def __str__(self) -> str:
        return f"{self.structure} — {self.intitule}"


class Obligation(models.Model):
    """
    L'occurrence : ce que telle structure doit deposer pour telle periode.

    **Engendree depuis le calendrier, jamais saisie a la main** — sinon une
    structure qui ne cree pas son obligation n'est jamais en retard, ce qui est
    exactement l'inverse du but.

    Le retard n'est pas stocke, par coherence avec l'arbitrage n° 2 : une
    obligation est en retard quand `echeance` est passee et `depose_le` nul.
    """

    calendrier_production = models.ForeignKey(
        CalendrierProduction,
        on_delete=models.PROTECT,
        db_column="calendrier_production_id",
        related_name="obligations",
    )
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    intitule = models.TextField()
    periode_libelle = models.TextField()
    periode_debut = models.DateField()
    periode_fin = models.DateField()
    echeance = models.DateField()
    depose_le = models.DateField(null=True, blank=True)
    depose_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="depose_par",
        related_name="obligations_deposees",
    )
    #: Le depot passe par la table de pieces du socle : une seconde table aurait
    #: fait diverger l'empreinte, le versionnement et la reconnaissance optique.
    piece_jointe = models.ForeignKey(
        PieceJointe,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="piece_jointe_id",
    )
    commentaire = models.TextField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "obligation"
        ordering = ["-echeance"]

    def __str__(self) -> str:
        return f"{self.intitule} — {self.periode_libelle}"


# =====================================================================
#  Agregats et vue d'etat
# =====================================================================


class AgregatActiviteJour(models.Model):
    """
    Alimente par tache planifiee nocturne. Meme regle que pour le courrier : le
    tableau de bord du Directeur General (§20) n'agrege jamais la table des
    activites a la volee.

    **Le recalcul nocturne n'est pas une optimisation.** Le retard evolue avec
    le temps sans qu'aucune ecriture ne survienne ; sans lui, seules les
    activites que quelqu'un a touchees paraitraient en retard.
    """

    pk = models.CompositePrimaryKey("structure_id", "exercice_id", "jour")
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, db_column="exercice_id")
    jour = models.DateField()

    nb_total = models.IntegerField(default=0)
    nb_realisees = models.IntegerField(default=0)
    nb_en_cours = models.IntegerField(default=0)
    nb_en_retard = models.IntegerField(default=0)
    nb_suspendues = models.IntegerField(default=0)
    nb_critiques = models.IntegerField(default=0)
    taux_execution = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    budget_valide = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    budget_consomme = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    calcule_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agregat_activite_jour"
        verbose_name = "agregat d'activites du jour"
        verbose_name_plural = "agregats d'activites du jour"


class VueActiviteEtat(models.Model):
    """
    L'etat **affiche** et la contrainte echue — une vue, pas une table.

    Trois etats sont stockes, cinq sont affiches : « programmee » et
    « en_retard » se deduisent des dates (arbitrage n° 2). Les stocker
    imposerait de reecrire toutes les lignes chaque nuit pour un resultat que la
    date donne deja.

    La criticite du §20 se lit ici : `etat_affiche = 'en_retard'` **et**
    `contrainte_echue`. Le retard seul ne suffit pas — sans quoi la moitie du
    plan serait critique et le mot ne trierait plus rien.

    **Attention** — `etat_affiche` applique l'arbitrage n° 2 (date de fin
    depassee), tandis que les ecrans appliquent l'ecart a un avancement attendu.
    Les deux ne designent pas les memes activites : docs/questions-ouvertes.md,
    A2.
    """

    id = models.BigIntegerField(primary_key=True)
    paa_id = models.BigIntegerField()
    structure_id = models.BigIntegerField()
    etat_stocke = models.TextField()
    etat_affiche = models.TextField()
    avancement_calcule = models.DecimalField(max_digits=5, decimal_places=2)
    contrainte_echue = models.BooleanField()

    class Meta:
        db_table = "v_activite_etat"
        managed = False
        verbose_name = "etat affiche d'une activite"
        verbose_name_plural = "etats affiches des activites"

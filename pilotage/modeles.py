"""
Pilotage — les indicateurs cibles du programme, §3.11 et §9 du BRD.

**Deux tables seulement, et aucune ne stocke un tableau de bord.** Le cockpit,
les statistiques et les analyses croisees se recalculent a chaque lecture, pour
la raison de l'ADR 010 : un agregat stocke devient faux des qu'une donnee est
corrigee, sans que rien ne le signale.

Ce qui vit ici est ce que l'agregat ne sait pas deduire :

 * `IndicateurProgramme` — la **cible** et la facon dont l'indicateur se lit.
   Une cible est une decision de gouvernance ; elle ne se calcule pas et ne
   s'ecrit pas dans le code.
 * `MesureProgramme` — la valeur d'une annee **quand elle est rapportee**.
   Beaucoup d'indicateurs du programme viennent de sources exterieures a
   l'application ; celle-ci doit pouvoir les porter sans savoir les calculer.

Un indicateur que l'application sait mesurer n'a pas de ligne dans
`MesureProgramme` : sa valeur est recalculee (voir `pilotage/programme.py`). Une
valeur rapportee prime toujours sur une valeur calculee — c'est le rapporteur
qui engage sa signature, pas le serveur.
"""

from django.db import models


class IndicateurProgramme(models.Model):
    """
    Un indicateur cible du programme, et sa cible.

    `cible` est **nullable**, et beaucoup le sont : les cibles chiffrees du
    programme n'ont pas ete communiquees. Une cible inventee aurait ete lue
    comme un engagement de l'institution ; l'absence de cible se voit et se
    corrige. Voir A32.

    `cible_maximum` distingue « atteindre au moins » de « ne pas depasser ».
    Sans lui, un delai moyen de 3 jours contre une cible de 5 aurait ete
    affiche en rouge.

    `mode_calcul` et `source` sont des textes affiches en clair, jamais
    evalues — meme choix que la formule du dictionnaire des indicateurs, et
    meme raison : une formule fausse qui s'execute produit un chiffre faux sans
    bruit, une formule fausse qui se lit se detecte.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    mode_calcul = models.TextField()
    source = models.TextField()
    unite = models.TextField(default="%")
    cible = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    #: Vrai quand la cible est un plafond a ne pas depasser.
    cible_maximum = models.BooleanField(default=False)
    #: Formulation littérale : « fin d'exercice 2026 ». Le programme fixe des
    #: echeances qui ne sont pas toutes des dates.
    echeance = models.TextField(default="fin d'exercice")
    ordre = models.SmallIntegerField(default=0)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "indicateur_programme"
        ordering = ["ordre", "code"]
        verbose_name = "indicateur cible du programme"
        verbose_name_plural = "indicateurs cibles du programme"

    def __str__(self) -> str:
        return f"{self.code} — {self.libelle}"


class MesureProgramme(models.Model):
    """
    La valeur d'un indicateur pour une annee, telle qu'elle a ete rapportee.

    Une annee sans ligne n'est pas une annee a zero : c'est une annee non
    mesuree, et l'ecran doit le dire. C'est toute la difference que le §3.11
    demande de tenir entre « nous n'avons pas atteint la cible » et « nous ne
    savons pas ou nous en sommes ».
    """

    indicateur = models.ForeignKey(
        IndicateurProgramme,
        on_delete=models.PROTECT,
        db_column="indicateur_programme_id",
        related_name="mesures",
    )
    annee = models.SmallIntegerField()
    valeur = models.DecimalField(max_digits=12, decimal_places=2)
    #: D'ou vient le chiffre, quand il ne vient pas de l'application.
    commentaire = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "mesure_programme"
        ordering = ["-annee"]
        verbose_name = "mesure d'un indicateur du programme"
        verbose_name_plural = "mesures des indicateurs du programme"
        constraints = [
            models.UniqueConstraint(
                fields=["indicateur", "annee"], name="unicite_mesure_programme_annee"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.indicateur_id} — {self.annee}"

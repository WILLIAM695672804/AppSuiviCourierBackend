"""
Performance — la matrice de scoring administratif, §2 et §3.3.

Trois tables seulement, et c'est deliberé : **le score n'est pas stocke**.

Le descriptif definit la matrice comme un agregat mensuel de ce qui se passe
ailleurs — execution des activites, traitement du courrier, conformite aux
rituels. Stocker le resultat de cet agregat aurait cree une seconde verite :
une activite corrigee apres coup laisserait un score faux jusqu'au prochain
recalcul, et personne ne saurait lequel des deux chiffres croire. La matrice se
recalcule a chaque lecture, sur peu de structures et des mois clos. Voir
l'ADR 010.

Ce qui vit ici est donc ce que l'agregat ne sait pas deduire :

 * `Critere` — les axes de la matrice et leur **poids**. Une ponderation est un
   choix de gouvernance, pas une constante : la DSR doit pouvoir decider que
   les rituels comptent double sans qu'on livre du code.
 * `Indicateur` — le dictionnaire du §3.3 : definition, formule, source,
   periodicite, responsable. Ces cinq champs sont ce qui empeche deux
   directions de calculer le meme indicateur de deux facons.
 * `NiveauRisque` — la grille de cotation, maintenue avec le dictionnaire.
"""

from django.db import models

from noyau.organisation.modeles import Structure


class Critere(models.Model):
    """
    Un axe de la matrice, et ce qu'il pese.

    **Le poids est administre, jamais ecrit dans le code.** C'est la seule
    facon pour la DSR de changer ce que l'institution valorise sans livraison,
    et c'est aussi ce qui rend le classement discutable : un directeur peut
    contester une ponderation, il ne peut pas contester une constante qu'il ne
    voit pas.

    Les poids initiaux sont egaux, faute de source. Voir A26.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    #: Part dans le score global, en pourcentage. La somme des criteres actifs
    #: devrait faire 100 ; rien ne le contraint en base, parce qu'une
    #: contrainte rendrait impossible toute modification intermediaire.
    poids = models.SmallIntegerField()
    #: Ordre d'affichage. La matrice les presente toujours dans le meme ordre,
    #: sinon deux captures d'ecran du meme mois ne se comparent pas.
    ordre = models.SmallIntegerField(default=0)
    description = models.TextField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "critere_matrice"
        ordering = ["ordre", "code"]
        verbose_name = "critere de la matrice"
        verbose_name_plural = "criteres de la matrice"

    def __str__(self) -> str:
        return f"{self.libelle} ({self.poids} %)"


class Indicateur(models.Model):
    """
    Une entree du dictionnaire des indicateurs — §3.3.

    « Maintenir le dictionnaire des indicateurs : definition, formule de
    calcul, source, periodicite, responsable. »

    **La formule est un texte affiche en clair, pas une expression evaluee.**
    C'est un choix : une formule executable aurait fait du dictionnaire un
    langage de programmation ouvert a la saisie, avec ce que cela suppose de
    surface d'attaque et de pannes silencieuses. Ce que le §3.3 demande est que
    chacun puisse **lire** comment le chiffre est obtenu — et une formule lue
    par un humain qui ne correspond pas au calcul reel se detecte, alors qu'une
    formule fausse qui s'execute produit un chiffre faux sans bruit.

    `responsable` est un texte et non une cle vers un poste : le responsable
    d'un indicateur est souvent une fonction qui n'a pas de poste au sens de
    l'organigramme (« le contrôle de gestion »).
    """

    PERIODICITES = [
        ("mensuelle", "Mensuelle"),
        ("trimestrielle", "Trimestrielle"),
        ("semestrielle", "Semestrielle"),
        ("annuelle", "Annuelle"),
    ]

    code = models.TextField(unique=True)
    libelle = models.TextField()
    definition = models.TextField()
    formule = models.TextField()
    source = models.TextField()
    periodicite = models.TextField(choices=PERIODICITES, default="mensuelle")
    responsable = models.TextField()
    unite = models.TextField(default="%")
    #: Au-dessus : vert. Le defaut reprend `noyau.feu`, qui vaut tant que le
    #: dictionnaire ne dit pas autre chose — c'est ce que la docstring de
    #: `noyau/feu.py` annonce depuis le debut.
    seuil_vert = models.SmallIntegerField(default=85)
    #: Au-dessus : orange. En dessous : rouge.
    seuil_orange = models.SmallIntegerField(default=60)
    #: Le critere de la matrice que l'indicateur alimente, s'il en alimente un.
    #: Beaucoup n'en alimentent aucun : le dictionnaire couvre tout le pilotage,
    #: la matrice n'en retient qu'une part.
    critere = models.ForeignKey(
        Critere,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="critere_id",
        related_name="indicateurs",
    )
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "indicateur_dictionnaire"
        ordering = ["code"]
        verbose_name = "indicateur du dictionnaire"
        verbose_name_plural = "dictionnaire des indicateurs"

    def __str__(self) -> str:
        return f"{self.code} — {self.libelle}"


class NiveauRisque(models.Model):
    """
    Un echelon de la grille de cotation des risques — §3.3.

    `conduite` est la colonne qui compte : une grille qui cote sans dire ce
    qu'on fait a chaque niveau ne produit qu'un classement de plus. « Niveau 4 :
    critique » n'aide personne ; « Niveau 4 : critique — saisine du CODIR sous
    quinze jours » engage quelqu'un.
    """

    niveau = models.SmallIntegerField(unique=True)
    libelle = models.TextField()
    description = models.TextField()
    conduite = models.TextField()
    #: Couleur associee : vert, orange, rouge. La grille en compte plus que
    #: trois echelons, donc plusieurs niveaux partagent une couleur.
    feu = models.TextField(default="orange")

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "niveau_risque"
        ordering = ["niveau"]
        verbose_name = "niveau de risque"
        verbose_name_plural = "grille de cotation des risques"

    def __str__(self) -> str:
        return f"{self.niveau} — {self.libelle}"


class RelanceProduction(models.Model):
    """
    Une relance envoyee pour une production non deposee — §3.3.

    « … avec relances automatiques en cas de non-saisie. » La table existe pour
    repondre a une question que le calendrier seul ne repond pas : **a-t-on
    relance, et quand**. Sans elle, une structure de bonne foi qui n'a rien
    recu et la DSR qui croit avoir relance n'ont aucun moyen de se departager.

    Elle n'est ecrite par rien a ce jour : l'envoi effectif suppose un canal de
    notification qui n'existe pas. La structure est posee pour que le jour ou
    il existera, la trace parte avec.
    """

    calendrier_production_id = models.BigIntegerField()
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    periode_libelle = models.TextField()
    echeance = models.DateField()
    envoyee_le = models.DateTimeField(auto_now_add=True)
    canal = models.TextField(default="notification")

    class Meta:
        db_table = "relance_production"
        ordering = ["-envoyee_le"]
        verbose_name = "relance de production"
        verbose_name_plural = "relances de production"

    def __str__(self) -> str:
        return f"{self.structure_id} — {self.periode_libelle}"

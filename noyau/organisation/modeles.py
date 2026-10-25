"""
Organigramme — niveaux, structures, postes.

Trois principes du schema qu'il faut connaitre avant de toucher a ces
modeles, sous peine de les casser sans s'en apercevoir :

 1. **Rien n'est supprime.** Une structure ne se modifie pas : on clot la
    ligne en vigueur (`valide_au`) et on en insere une nouvelle. Apres une
    reorganisation, une cotation de 2024 doit rester lisible telle qu'elle
    etait, avec les structures de 2024. D'ou la propriete `en_vigueur` sur
    les gestionnaires, a utiliser partout ailleurs qu'en consultation
    historique.

 2. **Le poste porte la hierarchie, pas l'agent.** La remontee au niveau
    superieur reste juste quand l'occupant change. Ne jamais chainer deux
    utilisateurs entre eux : chainer leurs postes.

 3. **Les niveaux ne sont pas ecrits dans le code.** L'administrateur en
    cree et en supprime ; le nombre d'etapes de cotation en decoule. Toute
    constante du genre `NIVEAU_DIRECTION = 2` est un defaut.
"""

import uuid

from django.db import models


class GestionnaireEnVigueur(models.Manager):
    """Ne renvoie que les lignes en vigueur, c'est-a-dire non closes."""

    def en_vigueur(self) -> models.QuerySet:
        return self.get_queryset().filter(valide_au__isnull=True)


class NiveauHierarchique(models.Model):
    """
    Un etage de l'organigramme, et ce que cet etage autorise.

    Les quatre booleens ne decrivent pas une structure mais un **rang** : que
    l'etage « Direction » porte la signature des courriers depart est une regle
    d'institution, pas une propriete de la DAF. Les ecrire ici est ce qui evite
    la constante `NIVEAU_DIRECTION = 2` que le principe 3 interdit.

    Ils sont administres (`/api/organisation/niveaux`) et pour l'instant lus par
    personne : le pilier courrier, qui les fera jouer, n'existe pas encore.
    C'est assume — les poser apres coup aurait demande de reprendre toutes les
    routes de cotation. Voir A21 dans `docs/questions-ouvertes.md`.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    rang = models.SmallIntegerField(help_text="1 = sommet de l'organigramme.")
    actif = models.BooleanField(default=True)

    #: L'etage sous lequel celui-ci se place. Distinct du rang : le rang
    #: ordonne, le parent dit ce qu'un administrateur a le droit d'imbriquer.
    niveau_parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="niveau_parent_id",
        related_name="niveaux_enfants",
    )

    #: Peut coter un courrier vers un niveau inferieur.
    peut_coter = models.BooleanField(default=False)
    #: Peut recevoir une cotation. Un etage qui ne recoit pas ne travaille pas.
    peut_recevoir_cotation = models.BooleanField(default=True)
    #: Porte la signature des courriers depart (B-04).
    porte_signature = models.BooleanField(default=False)
    #: Apparait comme ligne dans les tableaux statistiques. Un etage trop fin
    #: rendrait le tableau de bord illisible sans rien apprendre.
    ligne_statistiques = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "niveau_hierarchique"
        ordering = ["rang"]
        verbose_name = "niveau hierarchique"
        verbose_name_plural = "niveaux hierarchiques"

    def __str__(self) -> str:
        return f"{self.rang} — {self.libelle}"


class Structure(models.Model):
    """
    Direction, service, division, filiale ou succursale.

    `nature` dit ce qu'est la structure **en droit**, et non sa place dans
    l'organigramme : une filiale et une succursale ont leurs propres organes
    de gestion, dont la DSR suit les sessions et les prescriptions (§3.3 du
    descriptif fonctionnel).

    Et surtout, la nature n'est pas le rang. L'organigramme du Port l'ecrit
    noir sur blanc : le Cabinet du Directeur general est dirige par un chef de
    service, un Departement par un sous-directeur. Le nom de la boite dit la
    nature, la couleur dit le rang, et ce sont deux colonnes — `nature` et
    `niveau_hierarchique`. Les confondre reclasserait la moitie de
    l'institution ; voir `noyau/organisation/donnees/organigramme_pad.py`.
    """

    #: Les douze formes que prend une structure au Port. Les cinq premieres
    #: viennent du socle ; les sept suivantes de la planche d'organigramme
    #: transcrite en 2026 (migration 0017).
    NATURES = [
        ("Direction", "Direction"),
        ("Division", "Division"),
        ("Departement", "Departement"),
        ("Service", "Service"),
        ("Cellule", "Cellule"),
        ("Centre", "Centre"),
        ("Cabinet", "Cabinet"),
        ("Secteur", "Secteur"),
        ("Representation", "Representation"),
        ("Filiale", "Filiale"),
        ("Succursale", "Succursale"),
        # Le Conseil d'administration delibere ; il ne recoit pas de cotation
        # et ne porte aucun poste. Sa nature le dit, pour qu'aucun ecran ne le
        # propose comme destinataire.
        ("Organe", "Organe"),
    ]

    # `default` cote Python et non cote base : Django envoie toujours la
    # colonne dans son INSERT, ce qui court-circuite le DEFAULT
    # gen_random_uuid() du schema et insere NULL.
    uid = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)
    code = models.TextField(help_text="Sigle : DAF, DSI, DSR…")
    libelle = models.TextField()
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, db_column="parent_id"
    )

    #: L'ancetre enfant direct de la Direction generale — l'etage auquel
    #: cette structure se compte. Une tete est sa propre tete. `NULL` pour la
    #: Direction generale et pour les organes deliberants qui la coiffent.
    #:
    #: Materialisee par le declencheur `structure_tete_apres_ecriture`
    #: (migration 0024) et **jamais ecrite par l'ORM** : un `save()` qui la
    #: poserait a la main entrerait en conflit avec le declencheur au prochain
    #: deplacement, et les deux verites divergeraient sans qu'aucune erreur ne
    #: le dise. Voir `noyau/organisation/tete.py`.
    tete = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="tete_id",
        related_name="rattachees",
    )

    niveau_hierarchique = models.ForeignKey(
        NiveauHierarchique, on_delete=models.PROTECT, db_column="niveau_hierarchique_id"
    )
    nature = models.TextField(choices=NATURES, default="Direction")

    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    objects = GestionnaireEnVigueur()

    class Meta:
        db_table = "structure"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.libelle}"

    def descendants(self) -> models.QuerySet["Structure"]:
        """
        La structure et tout son sous-arbre.

        Recursion cote base et non cote Python : l'organigramme du Port
        descend a quatre ou cinq niveaux, et une remontee par boucle
        produirait une requete par noeud. La portee `sous_arbre` du
        perimetre s'appuie dessus a chaque requete de liste.
        """
        from django.db import connection

        with connection.cursor() as curseur:
            curseur.execute(
                """
                WITH RECURSIVE arbre AS (
                    SELECT id FROM structure WHERE id = %s
                    UNION ALL
                    SELECT s.id FROM structure s
                    JOIN arbre a ON s.parent_id = a.id
                    WHERE s.valide_au IS NULL
                )
                SELECT id FROM arbre
                """,
                [self.pk],
            )
            identifiants = [ligne[0] for ligne in curseur.fetchall()]

        return Structure.objects.filter(pk__in=identifiants)


class Poste(models.Model):
    structure = models.ForeignKey(Structure, on_delete=models.PROTECT, db_column="structure_id")
    libelle = models.TextField()
    niveau_hierarchique = models.ForeignKey(
        NiveauHierarchique, on_delete=models.PROTECT, db_column="niveau_hierarchique_id"
    )
    poste_superieur = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="poste_superieur_id",
        related_name="subordonnes",
    )

    #: Le poste de tete de la structure — celui a qui la relance est adressee.
    #:
    #: Un seul en vigueur par structure, tenu par un index unique partiel. Le
    #: deviner par « son superieur est hors de sa structure » etait vrai du
    #: semis et maintenu par rien : trop faible pour porter une decision de
    #: relance.
    est_responsable = models.BooleanField(default=False)

    #: Le profil propose a la creation d'un compte sur ce poste.
    #:
    #: Une proposition, jamais une attribution : `creer_compte` exige un
    #: `profilId` explicite et ne lit pas cette colonne. Un profil qui
    #: s'attribuerait tout seul en suivant l'organigramme donnerait des droits
    #: que personne n'a decides.
    #: Reference par chaine, et non par import : `habilitation` importe
    #: `organisation`, et l'importer en retour fermerait le cycle.
    profil_par_defaut = models.ForeignKey(
        "noyau.Profil",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="profil_par_defaut_id",
        related_name="postes",
    )

    #: Combien d'agents ce poste doit compter. Un poste vacant est un trou dans
    #: le circuit : c'est l'ecart a cet effectif qui le rend visible.
    effectif_prevu = models.SmallIntegerField(default=1)

    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    objects = GestionnaireEnVigueur()

    class Meta:
        db_table = "poste"

    def __str__(self) -> str:
        return self.libelle


class AffectationPoste(models.Model):
    """
    Qui a occupe quel poste, et **entre quelles dates** — F-04.

    `utilisateur.poste` reste la colonne du present : c'est elle que lisent la
    hierarchie, le perimetre `poste` et les selecteurs. Cette table-ci porte
    l'histoire, et repond a la question que la colonne ne peut pas :
    « qui tenait le poste de chef de la DSR le 12 mars ? ». C'est la meme
    raison qui a fait dater `utilisateur_profil` (RNF-TRACE-01) : sans elle,
    une cotation de 2024 se relit avec l'occupant de 2026.

    **Les deux ne peuvent pas diverger** : `services.affecter` ecrit les deux
    dans la meme transaction, et c'est le seul point qui touche
    `utilisateur.poste`. Le jour ou un second appelant l'ecrirait directement,
    l'histoire se trouerait sans qu'aucune erreur ne le signale.

    Un agent n'occupe **qu'un poste a la fois** : `utilisateur.poste` est une
    clef simple, et une seconde ligne ouverte n'aurait aucune traduction dans
    le present. La contrainte le dit en base plutot que dans le service.
    """

    utilisateur = models.ForeignKey(
        "noyau.Utilisateur",
        on_delete=models.PROTECT,
        db_column="utilisateur_id",
        related_name="affectations",
    )
    poste = models.ForeignKey(
        Poste, on_delete=models.PROTECT, db_column="poste_id", related_name="affectations"
    )

    debut = models.DateField()
    #: `None` tant que l'agent tient le poste. Une seule ligne ouverte par agent.
    fin = models.DateField(null=True, blank=True)

    #: Pourquoi l'affectation prend fin — mutation, depart, reorganisation.
    #: Facultatif a l'ouverture, puisqu'il n'y a encore rien a motiver.
    motif = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "affectation_poste"
        ordering = ["-debut", "-id"]
        verbose_name = "affectation a un poste"
        verbose_name_plural = "affectations aux postes"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fin__isnull=True) | models.Q(fin__gte=models.F("debut")),
                name="affectation_fin_apres_debut",
            ),
            models.UniqueConstraint(
                fields=["utilisateur"],
                condition=models.Q(fin__isnull=True),
                name="une_seule_affectation_ouverte_par_agent",
            ),
        ]
        indexes = [
            models.Index(fields=["poste", "-debut"], name="idx_affectation_poste"),
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur_id} → {self.poste_id} ({self.debut})"

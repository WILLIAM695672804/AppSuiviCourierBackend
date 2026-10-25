"""
Habilitation — profils, permissions, delegations.

**Ces modeles ne sont pas ceux de `django.contrib.auth`, et c'est delibere.**
Le systeme de permissions de Django ne connait qu'une question : « cet
utilisateur a-t-il le droit de faire X ? ». Le projet en pose deux :

    les permissions disent QUOI, le perimetre dit SUR QUELLES DONNEES.

Modeliser le second dans Django aurait demande de dupliquer le premier.
Voir docs/architecture/002-permissions-hors-django-auth.md.

Aucun code de permission ne nomme un role. « Attache a la DSR » n'est pas une
permission : c'est un profil, qui en porte plusieurs. Cette distinction est ce
qui permet de deplacer une responsabilite sans toucher au code. Deux
exceptions assumees — VUE_DG et VUE_CODIR — sont commentees dans le schema
SQL, et nulle part ailleurs ce procede ne doit etre repris.
"""

from django.db import models

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure


class Permission(models.Model):
    """
    Un geste, jamais un poste.

    `domaine` correspond a un pilier du descriptif fonctionnel. La liste est
    contrainte cote base ; ajouter un domaine demande une migration, ce qui
    est voulu — un domaine de plus est une decision d'architecture.
    """

    code = models.TextField(unique=True)
    libelle = models.TextField()
    domaine = models.TextField()

    class Meta:
        db_table = "permission"
        ordering = ["domaine", "code"]

    def __str__(self) -> str:
        return self.code


class Profil(models.Model):
    code = models.TextField(unique=True)
    libelle = models.TextField()
    description = models.TextField(null=True, blank=True)
    systeme = models.BooleanField(
        default=False,
        help_text="Profils initiaux, non supprimables. L'administrateur en cree d'autres.",
    )

    permissions = models.ManyToManyField(
        Permission, through="ProfilPermission", related_name="profils"
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "profil"
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle


class ProfilPermission(models.Model):
    """
    Table de liaison a cle primaire composite.

    Le schema ne lui donne pas de colonne `id` : la paire (profil, permission)
    EST la clef. Sans `CompositePrimaryKey`, Django reclamerait un `id` qui
    n'existe pas et toute insertion echouerait sur
    « column profil_permission.id does not exist ».
    """

    pk = models.CompositePrimaryKey("profil_id", "permission_id")
    profil = models.ForeignKey(Profil, on_delete=models.CASCADE, db_column="profil_id")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, db_column="permission_id")

    class Meta:
        db_table = "profil_permission"


class UtilisateurProfil(models.Model):
    """
    Attribution datee.

    Le `retire_le` n'est pas une coquetterie : il permet de repondre a
    « quels droits avait cet agent le 12 mars ? », question que pose tout
    audit serieux (RNF-TRACE-01).
    """

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, db_column="utilisateur_id", related_name="profils"
    )
    profil = models.ForeignKey(Profil, on_delete=models.PROTECT, db_column="profil_id")
    attribue_le = models.DateTimeField(auto_now_add=True)
    attribue_par = models.BigIntegerField(null=True, blank=True)
    retire_le = models.DateTimeField(null=True, blank=True)
    retire_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "utilisateur_profil"


class Delegation(models.Model):
    """
    Remplacement ou delegation temporaire — RF-BPM-04.

    Le beneficiaire agit **au nom** du titulaire : le front l'affiche
    (`delegationDe`), et le journal enregistre les deux (`acteur_id` et
    `agit_pour_id`). Une colonne unique attribuerait au remplacant une
    decision qu'il n'a pas prise.
    """

    NATURES = [("remplacement", "Remplacement"), ("delegation", "Delegation")]

    nature = models.TextField(choices=NATURES)
    titulaire = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="titulaire_id",
        related_name="delegations_accordees",
    )
    beneficiaire = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="beneficiaire_id",
        related_name="delegations_recues",
    )
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    perimetre_structure = models.ForeignKey(
        Structure,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="perimetre_structure_id",
    )
    motif = models.TextField(null=True, blank=True)

    permissions = models.ManyToManyField(
        Permission, through="DelegationPermission", related_name="delegations"
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "delegation"


class DelegationPermission(models.Model):
    """Meme structure que `ProfilPermission` : cle primaire composite."""

    pk = models.CompositePrimaryKey("delegation_id", "permission_id")
    delegation = models.ForeignKey(Delegation, on_delete=models.CASCADE, db_column="delegation_id")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, db_column="permission_id")

    class Meta:
        db_table = "delegation_permission"

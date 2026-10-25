"""
Journalisation — evenements, historique des champs, journal des acces.

Les trois tables existent deja au schema, partitionnees par date, et elles
sont **generiques** (`objet_type` / `objet_id`). C'est un cadeau : la fiche de
vie d'une activite (§18) s'y branche sans creer une seule table.

Repartition des roles, a ne pas confondre :

 * `evenement` — ce que l'application a decide de raconter. Alimentee par le
   code, via `noyau.journal.service.inscrire`. C'est la fiche de vie.
 * `champ_historique` — ce qui a change, colonne par colonne. Alimentee **par
   declencheur**, pas par le code : une modification faite hors application,
   en SQL direct, y figure aussi.
 * `journal_acces` — qui a lu quoi. Chainee par empreinte (RNF-TRACE-01), le
   scellement etant fait par lot en arriere-plan.

Aucun de ces trois modeles n'est modifiable ni supprimable. Ils n'ont
volontairement ni `save()` surcharge ni methode d'edition : une piste d'audit
qu'on peut corriger ne prouve rien.
"""

from django.db import models


class Evenement(models.Model):
    """
    Un fait, rapporte a un objet. La fiche de vie n'est rien d'autre que la
    liste des evenements d'un objet, dans l'ordre ou ils sont survenus.
    """

    objet_type = models.TextField(help_text="« activite », « courrier », « plan_actions »…")
    objet_id = models.BigIntegerField()
    courrier_id = models.BigIntegerField(null=True, blank=True)
    type_evenement = models.TextField()
    libelle = models.TextField()
    detail = models.TextField(null=True, blank=True)

    # Le premier a saisi, le second est celui pour le compte de qui il agit.
    # Deux colonnes et non une : attribuer au remplacant une decision qu'il
    # n'a pas prise viderait le journal de sa valeur probante.
    acteur_id = models.BigIntegerField(null=True, blank=True)
    agit_pour_id = models.BigIntegerField(null=True, blank=True)

    # Dans quelle structure le geste a eu lieu. **NULL est un jalon public** :
    # enregistre, cote, entre, sorti, cloture — ce que toute structure cotee a
    # le droit de lire. Renseignee, la colonne cloisonne : l'instruction interne
    # de la DAF ne se lit pas depuis la DSI, meme si les deux sont cotees sur le
    # meme courrier. Le filtre est dans `courrier.lecture`, pas ici.
    #
    # Distincte de la structure de l'acteur : un agent de la DSR qui ecrit dans
    # le dossier d'une direction n'y transporte pas sa propre structure.
    structure_id = models.BigIntegerField(null=True, blank=True)

    survenu_le = models.DateTimeField(auto_now_add=True)
    donnees = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "evenement"
        managed = False  # table partitionnee : cle primaire composite (id, survenu_le)
        ordering = ["survenu_le"]

    def __str__(self) -> str:
        return f"{self.type_evenement} — {self.objet_type} #{self.objet_id}"


class ChampHistorique(models.Model):
    """Alimentee par declencheur. Le code ne doit jamais y ecrire."""

    table_cible = models.TextField()
    ligne_id = models.BigIntegerField()
    colonne = models.TextField()
    valeur_avant = models.TextField(null=True, blank=True)
    valeur_apres = models.TextField(null=True, blank=True)
    acteur_id = models.BigIntegerField(null=True, blank=True)
    survenu_le = models.DateTimeField()

    class Meta:
        db_table = "champ_historique"
        managed = False
        ordering = ["-survenu_le"]


class JournalAcces(models.Model):
    """
    Qui a consulte quoi — RF-ADM-03 et RNF-TRACE-01.

    `empreinte` reste nulle le temps que le lot de scellement passe. Une ligne
    sans empreinte est une ligne **en attente**, pas une ligne douteuse : ne
    jamais l'interpreter comme une anomalie dans un rapport d'audit.
    """

    ACTIONS = [
        ("consultation", "Consultation"),
        ("liste", "Liste"),
        ("impression", "Impression"),
        ("export", "Export"),
        ("telechargement", "Telechargement"),
    ]

    acteur_id = models.BigIntegerField()
    objet_type = models.TextField()
    objet_id = models.BigIntegerField(null=True, blank=True)
    action = models.TextField(choices=ACTIONS)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    agent_utilisateur = models.TextField(null=True, blank=True)
    survenu_le = models.DateTimeField()
    empreinte = models.TextField(null=True, blank=True)
    empreinte_precedente = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "journal_acces"
        managed = False
        ordering = ["-survenu_le"]

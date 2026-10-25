"""
Pieces jointes.

La table existait, couplee au courrier par `courrier_id`. Elle est generalisee
par la migration 0002 : `objet_type` / `objet_id`, comme `evenement`. Le §18
range les pieces jointes parmi les elements de la fiche de vie d'une activite,
et RF-GED-04 exige le versionnement pour tout document — pas seulement pour
les courriers.

`courrier_id` est conservee : les index et les requetes du pilier courrier s'y
appuient, et la supprimer aurait demande de reecrire du code qui fonctionne.

Deux invariants du schema :

 * **Le binaire n'est jamais en base.** Seul `chemin_stockage` l'est. Le
   commentaire SQL est explicite : « une base contenant les binaires devient
   insauvegardable ».
 * **Une version n'ecrase jamais la precedente** (RF-GED-04). On insere une
   nouvelle ligne qui pointe vers l'ancienne par `piece_precedente`.
"""

import uuid

from django.db import models


class PieceJointe(models.Model):
    CATEGORIES = [
        ("original", "Original"),
        ("annexe", "Annexe"),
        ("reponse", "Reponse"),
        ("accuse", "Accuse de reception"),
        ("justificatif", "Justificatif"),
    ]

    # `default` cote Python et non cote base : Django envoie toujours la
    # colonne dans son INSERT, ce qui court-circuite le DEFAULT
    # gen_random_uuid() du schema et insere NULL.
    uid = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)

    # Rattachement generique, ajoute par la migration 0002.
    objet_type = models.TextField(null=True, blank=True)
    objet_id = models.BigIntegerField(null=True, blank=True)
    courrier_id = models.BigIntegerField(null=True, blank=True)

    nom_fichier = models.TextField()
    nom_original = models.TextField()
    extension = models.TextField(null=True, blank=True)
    taille_octets = models.BigIntegerField()
    type_mime = models.TextField(null=True, blank=True)

    # RF-GED-09 : preuve d'integrite. Calculee a l'enregistrement, jamais apres.
    empreinte_sha256 = models.TextField()
    chemin_stockage = models.TextField()

    categorie = models.TextField(choices=CATEGORIES, default="annexe")
    version = models.SmallIntegerField(default=1)
    piece_precedente = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="piece_precedente_id",
        related_name="versions_suivantes",
    )

    texte_reconnu = models.TextField(null=True, blank=True, help_text="Sortie de l'OCR — RF-IA-01.")

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "piece_jointe"
        ordering = ["-cree_le"]
        verbose_name = "piece jointe"
        verbose_name_plural = "pieces jointes"

    def __str__(self) -> str:
        return f"{self.nom_original} (v{self.version})"

    @property
    def poids_lisible(self) -> str:
        """« 1,2 Mo ». Le front affiche cette forme, pas des octets."""
        octets = float(self.taille_octets)
        for unite in ("o", "Ko", "Mo", "Go"):
            if octets < 1024 or unite == "Go":
                return f"{octets:.1f}".replace(".0", "").replace(".", ",") + f" {unite}"
            octets /= 1024
        return f"{self.taille_octets} o"

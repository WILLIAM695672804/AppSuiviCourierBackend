"""
Perimetre — le second axe d'habilitation.

Les permissions disent QUOI ; le perimetre dit SUR QUELLES DONNEES. Les deux
sont independants, et c'est ce qui permet a un point focal et au chef de la
DSR de porter tous deux `ACT_SAI` sans voir la meme chose.

**Attention au vocabulaire.** La base et le front ne nomment pas les portees
de la meme facon. La correspondance est etablie une seule fois, ici, dans
`PORTEE_VERS_FRONT` — nulle part ailleurs :

    base            front                        signification
    propre          poste                        ce que l'agent traite lui-meme
    structure       structure                    sa structure, sans les filles
    sous_arbre      structure_et_descendants     sa structure et ce qui en depend
    toutes          institution                  tout, sans restriction

Traduire ailleurs, c'est garantir qu'un jour les deux listes divergeront.
"""

from django.db import models

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure

PORTEE_PROPRE = "propre"
PORTEE_STRUCTURE = "structure"
PORTEE_SOUS_ARBRE = "sous_arbre"
PORTEE_TOUTES = "toutes"

PORTEE_VERS_FRONT = {
    PORTEE_PROPRE: "poste",
    PORTEE_STRUCTURE: "structure",
    PORTEE_SOUS_ARBRE: "structure_et_descendants",
    PORTEE_TOUTES: "institution",
}


class Perimetre(models.Model):
    PORTEES = [
        (PORTEE_PROPRE, "Ce que l'agent traite lui-meme"),
        (PORTEE_STRUCTURE, "Sa structure"),
        (PORTEE_SOUS_ARBRE, "Sa structure et ses descendants"),
        (PORTEE_TOUTES, "Toute l'institution"),
    ]

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, db_column="utilisateur_id", related_name="perimetres"
    )
    structure = models.ForeignKey(
        Structure, null=True, blank=True, on_delete=models.PROTECT, db_column="structure_id"
    )
    portee = models.TextField(choices=PORTEES)

    valide_du = models.DateField()
    valide_au = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "perimetre"

    def __str__(self) -> str:
        return f"{self.utilisateur} — {self.portee}"

    @property
    def portee_front(self) -> str:
        return PORTEE_VERS_FRONT[self.portee]

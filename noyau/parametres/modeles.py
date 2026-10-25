"""
Parametres des regles de gestion.

**Pourquoi cette table existe.** L'analyse des trois documents de reference a
etabli que plusieurs regles appliquees par l'application n'ont **aucune source
documentaire** : elles ont ete inventees par la conception, faute de reponse du
metier. Les principales, pour le pilier « activites » :

 * le mode de calcul de l'avancement attendu (lineaire sur la periode) ;
 * le seuil d'ecart qui fait basculer une activite « en retard » (10 points) ;
 * la definition d'une activite « critique » ;
 * la formule du taux d'atteinte d'un indicateur.

Les coder en dur aurait rendu leur correction impossible sans redeploiement, et
— plus grave — aurait fait passer une hypothese pour une decision. Elles vivent
donc ici, avec pour chacune la mention de son absence de source et de qui doit
trancher.

Voir docs/regles/activite-parametres.md et docs/questions-ouvertes.md.

**Ne jamais lire cette table directement depuis un service.** Passer par
`noyau.parametres.service.valeur()`, qui met en cache : une regle relue a
chaque ligne d'un registre de deux cents activites, c'est deux cents requetes.
"""

from django.db import models


class Parametre(models.Model):
    TYPES = [
        ("entier", "Entier"),
        ("decimal", "Decimal"),
        ("texte", "Texte"),
        ("booleen", "Booleen"),
    ]

    STATUTS = [
        ("acte", "Acte par le metier"),
        ("hypothese", "Hypothese de travail — sans source documentaire"),
    ]

    cle = models.TextField(unique=True, help_text="activite.seuil_retard_points")
    libelle = models.TextField()
    valeur = models.TextField()
    type_valeur = models.TextField(choices=TYPES, default="entier")

    domaine = models.TextField(help_text="Pilier concerne : activite, courrier…")

    statut = models.TextField(
        choices=STATUTS,
        default="hypothese",
        help_text="Une hypothese n'est pas une decision : elle attend une reponse du metier.",
    )
    source = models.TextField(
        null=True,
        blank=True,
        help_text="Reference documentaire — « CDC §15 », « Decision D8 ». Vide si aucune.",
    )
    a_trancher_par = models.TextField(
        null=True, blank=True, help_text="DSR, contrôle de gestion, Direction generale…"
    )

    modifie_le = models.DateTimeField(auto_now=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "parametre"
        ordering = ["domaine", "cle"]

    def __str__(self) -> str:
        return f"{self.cle} = {self.valeur}"

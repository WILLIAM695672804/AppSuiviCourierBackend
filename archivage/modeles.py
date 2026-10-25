"""
L'archivage — le sort des dossiers une fois clos.

Trois exigences le fondent :

 * **RF-GED-06** : durees de conservation par typologie, et application du sort
   final — conservation, destruction, tri ;
 * **RF-ADM-05** : ces durees sont administrees par un profil dedie, « avec
   validation par le service des archives » ;
 * **RF-GED-09** : export d'un dossier avec preuve d'integrite, empreinte
   numerique et horodatage.

La distinction qui structure tout : la **duree d'utilite administrative** (DUA)
court a partir de la cloture et dit combien de temps le dossier reste utile au
service ; le **sort final** dit ce qu'on en fait ensuite. Confondre les deux
revient a detruire des dossiers encore utiles, ou a conserver indefiniment ce
qui aurait du etre elimine — les deux sont des fautes, et la seconde coute
autant que la premiere.

**Rien ne se detruit depuis l'application.** Le sort final se propose, il ne
s'execute pas : la destruction d'archives publiques suppose un visa que le
logiciel n'a pas a donner. Aucune methode de ce module ne supprime de ligne.

Ce qui n'est **pas** ici : la file des dossiers a verser. Elle n'est pas une
table mais une **lecture** — les dossiers clos sans versement, joints a leur
regle de conservation. La stocker aurait cree une seconde liste a tenir a jour,
et c'est toujours celle-la qui oublie un dossier.
"""

from django.db import models

from dossier.modeles import Dossier
from noyau.identite.modeles import Utilisateur

#: Ce qu'on fait du dossier une fois la DUA expiree. Referentiel **ferme** :
#: ce sont les trois sorts de la pratique archivistique, et un quatrieme saisi
#: a la main serait un sort que personne ne saurait executer.
SORT_CONSERVATION = "conservation"
SORT_DESTRUCTION = "destruction"
SORT_TRI = "tri"
SORTS = [
    (SORT_CONSERVATION, "Conservation définitive"),
    (SORT_DESTRUCTION, "Destruction"),
    (SORT_TRI, "Tri"),
]

ETAT_A_VERSER = "a_verser"
ETAT_EN_COURS = "en_cours"
ETAT_VERSE = "verse"
ETATS_VERSEMENT = [
    (ETAT_A_VERSER, "À verser"),
    (ETAT_EN_COURS, "En cours"),
    (ETAT_VERSE, "Versé"),
]

#: L'algorithme d'empreinte. Une constante et non un champ libre : une chaine
#: d'integrite dont chaque maillon utiliserait un algorithme different ne se
#: verifie pas d'un bout a l'autre.
ALGORITHME = "SHA-256"


class RegleConservation(models.Model):
    """
    Combien de temps on garde, et ce qu'on en fait ensuite — RF-GED-06.

    La regle porte son **fondement juridique**. Sans lui elle n'est pas
    opposable : un archiviste a qui l'on demande pourquoi un dossier a ete
    detruit au bout de cinq ans repond par un texte, pas par une capture
    d'ecran de l'application.

    Le **visa du service des archives** (RF-ADM-05) est ce qui rend la regle
    applicable. Une regle saisie mais non visee existe, se lit, et ne decide de
    rien : elle apparait en attente. Appliquer une DUA que le service des
    archives n'a pas vue reviendrait a lui retirer sa competence par voie
    logicielle.
    """

    typologie = models.TextField(unique=True)
    description = models.TextField()
    #: Duree d'utilite administrative, en annees a compter de la cloture.
    dua = models.SmallIntegerField()
    sort_final = models.TextField(choices=SORTS)
    #: Le texte qui fonde la duree. Voir la docstring de la classe.
    fondement_juridique = models.TextField()
    #: Combien de pieces la typologie attend. Sert a dire, au versement, ce qui
    #: manque — un dossier incomplet verse est un dossier perdu.
    pieces_attendues = models.SmallIntegerField(default=0)

    validee_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="validee_par_id",
        related_name="regles_conservation_visees",
    )
    validee_le = models.DateField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "regle_conservation"
        ordering = ["typologie"]
        verbose_name = "regle de conservation"
        verbose_name_plural = "regles de conservation"
        constraints = [
            # Une DUA de zero annee signifierait « detruire le jour de la
            # cloture ». Ce n'est pas une duree d'utilite administrative,
            # c'est l'absence de conservation, et cela se decide ailleurs.
            models.CheckConstraint(
                condition=models.Q(dua__gte=1, dua__lte=100),
                name="dua_plausible",
            ),
            # Le visa et sa date vont ensemble : une regle visee sans date ne
            # permet pas de dire depuis quand elle s'applique.
            models.CheckConstraint(
                condition=(
                    models.Q(validee_par__isnull=True, validee_le__isnull=True)
                    | models.Q(validee_par__isnull=False, validee_le__isnull=False)
                ),
                name="visa_conservation_complet",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.typologie} — {self.dua} ans"

    @property
    def visee(self) -> bool:
        return self.validee_le is not None


class Versement(models.Model):
    """
    Le versement d'un dossier clos aux archives.

    Une ligne par dossier verse, creee au versement et **jamais avant** : la
    file des dossiers a verser se lit dans les dossiers clos sans versement,
    elle ne se stocke pas.

    `anomalies_acceptees` garde la trace d'un versement fait malgre une
    anomalie non bloquante. C'est la difference entre un fonds propre et un
    fonds dont on sait ce qui manque — et cette phrase-la, c'est l'archiviste
    qui devra la tenir devant un auditeur, pas l'application.
    """

    dossier = models.OneToOneField(
        Dossier,
        on_delete=models.PROTECT,
        db_column="dossier_id",
        related_name="versement",
    )
    regle = models.ForeignKey(
        RegleConservation,
        on_delete=models.PROTECT,
        db_column="regle_id",
        related_name="versements",
    )
    #: La DUA et le sort final **figes au versement**. La regle peut changer
    #: ensuite ; ce qui a ete verse l'a ete sous la regle d'alors, et un fonds
    #: dont les echeances se recalculent au gre du referentiel n'est plus un
    #: fonds. Meme raisonnement que `instance_circuit.circuit_version_id`.
    dua_appliquee = models.SmallIntegerField()
    sort_final_applique = models.TextField(choices=SORTS)
    #: Date a laquelle la DUA expire et ou le sort final s'applique. Calculee
    #: au versement a partir de la cloture : elle est **opposable**, donc elle
    #: se lit et ne se recalcule pas.
    echeance_sort_final = models.DateField()

    etat = models.TextField(choices=ETATS_VERSEMENT, default=ETAT_EN_COURS)
    observation = models.TextField(null=True, blank=True)
    anomalies_acceptees = models.BooleanField(default=False)

    verse_le = models.DateTimeField(null=True, blank=True)
    verse_par = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="verse_par_id",
        related_name="versements_effectues",
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "versement"
        ordering = ["echeance_sort_final", "id"]
        verbose_name = "versement"
        verbose_name_plural = "versements"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(etat=ETAT_VERSE, verse_le__isnull=False)
                    | ~models.Q(etat=ETAT_VERSE) & models.Q(verse_le__isnull=True)
                ),
                name="versement_date_coherente",
            ),
        ]

    def __str__(self) -> str:
        return f"versement {self.dossier_id}"


class MaillonIntegrite(models.Model):
    """
    Un maillon de la chaine d'empreintes — RF-GED-09.

    Chaque etape scelle l'etat du dossier a ce moment, et **inclut l'empreinte
    du maillon precedent**. C'est ce chainage qui fait la preuve : une
    empreinte isolee prouve qu'un fichier n'a pas bouge, une chaine prouve
    qu'aucune etape n'a ete retiree entre deux autres.

    Le maillon est en **ecriture seule** : aucun service de ce depot ne le
    modifie ni ne le supprime. Une chaine d'integrite qu'on peut reecrire ne
    prouve rien, et c'est exactement ce qu'un auditeur cherchera a savoir.
    """

    versement = models.ForeignKey(
        Versement,
        on_delete=models.PROTECT,
        db_column="versement_id",
        related_name="maillons",
    )
    rang = models.SmallIntegerField()
    etape = models.TextField()
    horodatage = models.DateTimeField(auto_now_add=True)
    #: Empreinte du contenu scelle, chainee au maillon precedent.
    empreinte = models.TextField()
    #: L'empreinte du maillon de rang inferieur. `null` sur le premier.
    empreinte_precedente = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "maillon_integrite"
        ordering = ["versement", "rang"]
        verbose_name = "maillon de la chaine d'integrite"
        verbose_name_plural = "maillons de la chaine d'integrite"
        constraints = [
            models.UniqueConstraint(
                fields=["versement", "rang"],
                name="unicite_maillon_versement",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.versement_id} #{self.rang} — {self.etape}"

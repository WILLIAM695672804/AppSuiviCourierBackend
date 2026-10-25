"""
Prevenir quelqu'un — RF-SUI-03, RF-ADM-04.

## Deux tables, et la separation n'est pas decorative

`notification` est **le message** : ce dont on previent, qui on previent, et
si la personne l'a lu. Elle existe des que l'evenement metier survient, et elle
ne depend d'aucun reseau.

`envoi_notification` est **la tentative de sortie** : une ligne par canal
sortant, avec son etat, ses tentatives et son erreur. Elle depend, elle, de
choses que l'institution ne maitrise pas — un serveur SMTP, une passerelle SMS.

Une seule table aurait melange les deux, et le melange coute : une notification
dont l'envoi echoue doit rester **lue dans l'application**, sinon la panne du
serveur de messagerie devient une perte d'information. Le canal interne n'a
donc pas de ligne d'envoi ; il est la notification elle-meme.

## Ce que l'etat d'un envoi dit vraiment

Trois etats, dont un que la plupart des files n'ont pas :

 * `en_attente` — pas encore depile ;
 * `envoye` — remis au transport, qui l'a accepte ;
 * `echoue` — le transport a refuse, et le compteur de tentatives dit combien
   de fois ;
 * `sans_transport` — **aucun transport n'est branche pour ce canal**. Ce n'est
   pas un echec : c'est un aveu. Le SMS n'a pas de passerelle (A48), et le
   courriel n'en a une que si l'institution a tranche A51. Confondre ce cas
   avec `echoue` ferait relancer indefiniment des envois qui n'ont nulle part
   ou aller, et masquerait ce qui manque reellement.

## Ce qui n'est pas ici

Aucune purge. Une notification lue reste ; sa duree de conservation est une
question ouverte (A51) et non une valeur inventee dans une tache planifiee.
"""

from django.db import models

from noyau.identite.modeles import Utilisateur

#: Les canaux. Le canal interne est servi par l'application elle-meme et ne
#: produit aucune ligne d'envoi — il est toujours actif, pour tout le monde, et
#: c'est ce qui fait qu'aucune notification ne se perd quand le reseau tombe.
CANAL_INTERNE = "interne"
CANAL_COURRIEL = "courriel"
CANAL_SMS = "sms"
CANAUX = [
    (CANAL_INTERNE, "Notification interne"),
    (CANAL_COURRIEL, "Courriel"),
    (CANAL_SMS, "SMS"),
]

#: Ce qu'une notification pese pour celui qui la recoit. Deux valeurs et pas
#: cinq : une echelle fine se remplit d'elle-meme par le haut, et tout finit
#: « urgent ».
IMPORTANCE_INFORMATION = "information"
IMPORTANCE_ALERTE = "alerte"
IMPORTANCES = [
    (IMPORTANCE_INFORMATION, "Information"),
    (IMPORTANCE_ALERTE, "Alerte"),
]

ETAT_EN_ATTENTE = "en_attente"
ETAT_ENVOYE = "envoye"
ETAT_ECHOUE = "echoue"
ETAT_SANS_TRANSPORT = "sans_transport"
ETATS = [
    (ETAT_EN_ATTENTE, "En attente"),
    (ETAT_ENVOYE, "Envoyé"),
    (ETAT_ECHOUE, "Échoué"),
    (ETAT_SANS_TRANSPORT, "Sans transport"),
]


class Notification(models.Model):
    """
    Ce dont un agent ou un usager est prevenu.

    Le destinataire est un **utilisateur** et non un poste : un poste ne lit
    pas. Les seuils d'alerte (`seuil_alerte`) visent bien un poste, et c'est le
    service qui traduit le poste en ses occupants du jour — la responsabilite
    reste au poste, la lecture revient a la personne.

    `lien` est un chemin du front (`/dossiers/42`), pas une URL absolue :
    l'application ne connait pas le domaine sous lequel elle est servie, et une
    URL ecrite en base survivrait mal a un changement d'adresse.
    """

    destinataire = models.ForeignKey(
        Utilisateur,
        on_delete=models.CASCADE,
        db_column="destinataire_id",
        related_name="notifications",
    )

    #: Le code de l'evenement qui l'a produite — `dossier_retourne`,
    #: `courrier_cote`. Sert au filtrage et aux preferences de l'usager.
    type_notification = models.TextField()
    libelle = models.TextField()
    detail = models.TextField(default="")
    importance = models.TextField(choices=IMPORTANCES, default=IMPORTANCE_INFORMATION)

    #: Rattachement generique, comme `evenement` et `piece_jointe`. Nullable :
    #: une notification peut annoncer quelque chose qui n'est pas un objet
    #: (« votre mot de passe expire dans trois jours »).
    objet_type = models.TextField(null=True, blank=True)
    objet_id = models.BigIntegerField(null=True, blank=True)
    lien = models.TextField(null=True, blank=True)

    #: Nul tant que la notification n'a pas ete ouverte. Une date et non un
    #: booleen : savoir *quand* une alerte a ete lue est ce qui permet de dire
    #: si elle a ete lue a temps.
    lu_le = models.DateTimeField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    #: L'agent a l'origine de l'acte notifie. Nul quand c'est le systeme —
    #: une echeance qui tombe n'a pas d'auteur.
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        ordering = ["-cree_le", "-id"]
        indexes = [
            # L'index qui porte la cloche : les non-lues d'un destinataire,
            # demandees a chaque chargement d'ecran par chaque agent connecte.
            models.Index(
                fields=["destinataire", "lu_le"],
                name="notification_destinataire_idx",
            ),
        ]
        verbose_name = "notification"
        verbose_name_plural = "notifications"

    def __str__(self) -> str:
        return f"{self.destinataire_id} — {self.libelle}"


class EnvoiNotification(models.Model):
    """
    Une tentative de sortie, par un canal donne.

    `adresse` est recopiee au moment de la mise en file, et non relue au moment
    de l'envoi : c'est l'adresse a laquelle on a voulu ecrire ce jour-la. Un
    usager qui change de courriel ne doit pas rendre incomprehensible le
    bordereau des envois passes.

    `tentatives` compte les passages du depileur, pas les secondes. Une file
    qui compterait le temps plutot que les essais ne saurait pas dire si elle a
    reessaye.
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        db_column="notification_id",
        related_name="envois",
    )
    canal = models.TextField(choices=CANAUX)
    adresse = models.TextField(default="")
    etat = models.TextField(choices=ETATS, default=ETAT_EN_ATTENTE)
    tentatives = models.SmallIntegerField(default=0)
    envoye_le = models.DateTimeField(null=True, blank=True)
    #: Ce que le transport a repondu quand il a refuse. Conservee telle quelle,
    #: sans reformulation : un message d'erreur reecrit ne se cherche plus.
    erreur = models.TextField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "envoi_notification"
        ordering = ["cree_le", "id"]
        constraints = [
            # Un seul envoi par canal et par notification. Sans cette
            # contrainte, un depileur relance deux fois enverrait deux
            # courriels pour le meme fait, et c'est ainsi qu'une institution
            # apprend a ignorer ses propres messages.
            models.UniqueConstraint(
                fields=["notification", "canal"],
                name="envoi_notification_unique_par_canal",
            ),
        ]
        indexes = [
            models.Index(fields=["etat", "cree_le"], name="envoi_notification_file_idx"),
        ]
        verbose_name = "envoi de notification"
        verbose_name_plural = "envois de notification"

    def __str__(self) -> str:
        return f"{self.canal} — {self.etat}"

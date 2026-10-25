"""
Portail usagers — ce que l'exterieur depose, et ce qu'il en sait.

Le §3.13 donne trois capacites a l'usager : deposer une demande et suivre son
avancement, etre notifie sur le canal de son choix, et echanger de facon
dematerialisee dans le cadre d'un marche, d'une convention ou d'un reporting.

**Ce qui n'est pas stocke.** L'etat d'une demande — deposee, a l'etude,
complement attendu, decision rendue, close — ne figure dans aucune colonne. Il
se deduit de quatre faits : le service instructeur est-il designe, un complement
est-il en attente, une decision est-elle rendue, la demande est-elle close.
C'est l'ADR 010 applique ici : une colonne `etat` a cote de ces quatre faits
aurait fini par les contredire, et c'est l'usager qui aurait lu la contradiction.

**Ce qui est stocke et ne se deduit de rien** : la date de reponse annoncee. Le
delai par defaut vit en base (`portail.delai_reponse_jours`), mais la date
promise est figee au depot. Un delai raccourci plus tard ne doit pas rendre en
retard des demandes deposees sous l'ancien regime — ni un delai rallonge effacer
un retard deja constitue. C'est le meme raisonnement que pour l'echeance d'un
dossier (A38).

**Le vocabulaire.** Aucune de ces tables ne porte le mot « cotation »,
« structure pilote » ni « etape ». L'usager lit « votre demande est a l'etude au
service juridique ». Les mots de l'institution restent dans l'institution.
"""

from django.db import models

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure

#: Les quatre natures de demande ouvertes au public. Referentiel **ferme** :
#: c'est le type qui oriente vers le service competent, et deux orthographes
#: d'un meme type produiraient deux files d'attente.
TYPE_DEMANDE = "Demande"
TYPE_RECLAMATION = "Réclamation"
TYPE_AUTORISATION = "Autorisation"
TYPE_REQUETE = "Requête"
TYPES_DEMANDE = [
    (TYPE_DEMANDE, "Demande — autorisation, information, document"),
    (TYPE_RECLAMATION, "Réclamation — contestation, litige"),
    (TYPE_AUTORISATION, "Autorisation — occupation, travaux, accès"),
    (TYPE_REQUETE, "Requête — révision d'une décision"),
]

#: Canaux de notification. « Portail seulement » n'est pas l'absence de
#: notification : l'usager est prevenu, mais il doit venir lire.
CANAL_COURRIEL = "Courriel"
CANAL_SMS = "SMS"
CANAL_PORTAIL = "Portail seulement"
CANAUX = [
    (CANAL_COURRIEL, "Courriel"),
    (CANAL_SMS, "SMS"),
    (CANAL_PORTAIL, "Portail seulement"),
]

#: Les trois cadres d'echange dematerialise nommes par le §3.13.
NATURE_MARCHE = "Marché public"
NATURE_CONVENTION = "Convention"
NATURE_REPORTING = "Reporting réglementaire"
NATURES_ECHANGE = [
    (NATURE_MARCHE, "Marché public"),
    (NATURE_CONVENTION, "Convention"),
    (NATURE_REPORTING, "Reporting réglementaire"),
]


class DemandeUsager(models.Model):
    """
    Une demande deposee par un usager, une entreprise ou une administration.

    `deposant` est un compte du portail — profil `EXTERNE`, permission `EXT`. La
    demande lui appartient : c'est cette colonne, et elle seule, qui decide de ce
    qu'il voit. Le perimetre par structure du socle ne s'applique pas ici, un
    usager n'appartenant a aucune structure du port (ADR 013).

    `service_instructeur` est nullable et le reste tant que la demande n'est pas
    orientee. L'usager lit alors « en cours d'orientation » — ce qui est vrai —
    plutot qu'un service choisi par defaut, qui l'enverrait telephoner au mauvais
    guichet.
    """

    reference = models.TextField(unique=True)
    type = models.TextField(choices=TYPES_DEMANDE, default=TYPE_DEMANDE)
    objet = models.TextField()
    contexte = models.TextField()

    deposant = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="deposant_id",
        related_name="demandes_portail",
    )
    deposee_le = models.DateField()
    #: Ce que l'institution s'est engagee a tenir, fige au depot. Voir la
    #: docstring du module.
    reponse_attendue_le = models.DateField()

    service_instructeur = models.ForeignKey(
        Structure,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column="service_instructeur_id",
        related_name="demandes_portail",
    )

    #: Date de la decision rendue, et son sens en clair pour l'usager. Les deux
    #: vont ensemble : une decision sans texte n'est pas une reponse.
    decision_le = models.DateField(null=True, blank=True)
    decision = models.TextField(null=True, blank=True)

    clos_le = models.DateField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)
    invalide_le = models.DateTimeField(null=True, blank=True)
    invalide_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "demande_usager"
        ordering = ["-deposee_le", "-id"]
        verbose_name = "demande d'usager"
        verbose_name_plural = "demandes d'usagers"
        indexes = [
            models.Index(fields=["deposant", "-deposee_le"], name="idx_demande_deposant"),
        ]
        constraints = [
            # Une reponse promise avant le depot serait tenue d'avance. Le cas
            # arrive quand une date est saisie a la main plutot que calculee.
            models.CheckConstraint(
                condition=models.Q(reponse_attendue_le__gte=models.F("deposee_le")),
                name="reponse_attendue_apres_depot",
            ),
            # Une decision est une date **et** un texte, ou rien.
            models.CheckConstraint(
                condition=(
                    models.Q(decision_le__isnull=True, decision__isnull=True)
                    | models.Q(decision_le__isnull=False, decision__isnull=False)
                ),
                name="decision_datee_et_motivee",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.objet}"


class ComplementDemande(models.Model):
    """
    Une piece reclamee a l'usager, avec sa date limite.

    Table a part plutot que deux colonnes sur la demande : une demande peut
    reclamer deux fois, et l'historique des reclamations est ce qui permet de
    dire, plus tard, que l'usager avait ete prevenu. La fiche n'en montre qu'un
    — le dernier non satisfait — mais elle les conserve tous.

    `satisfait_le` porte la date a laquelle la piece est arrivee. Tant qu'elle
    est nulle, la demande est « en attente de complement » : c'est de cette
    colonne que l'etat se deduit, et de nulle part ailleurs.
    """

    demande = models.ForeignKey(
        DemandeUsager,
        on_delete=models.CASCADE,
        db_column="demande_id",
        related_name="complements",
    )
    objet = models.TextField()
    demande_le = models.DateField()
    avant_le = models.DateField()
    satisfait_le = models.DateField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "complement_demande"
        ordering = ["-demande_le", "-id"]
        verbose_name = "complément demandé"
        verbose_name_plural = "compléments demandés"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(avant_le__gte=models.F("demande_le")),
                name="complement_delai_positif",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.objet} — avant le {self.avant_le}"


class MessagePortail(models.Model):
    """
    Un message echange sur une demande, dans un sens ou dans l'autre.

    L'auteur est un compte, pas une etiquette : « Vous » et « Institution » se
    deduisent a la lecture, en comparant l'auteur au deposant. Stocker le sens
    aurait fait porter a la donnee un point de vue — celui du lecteur — qui n'est
    pas le sien.
    """

    demande = models.ForeignKey(
        DemandeUsager,
        on_delete=models.CASCADE,
        db_column="demande_id",
        related_name="messages",
    )
    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="auteur_id",
        related_name="messages_portail",
    )
    texte = models.TextField()

    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_portail"
        ordering = ["cree_le", "id"]
        verbose_name = "message du portail"
        verbose_name_plural = "messages du portail"

    def __str__(self) -> str:
        return f"{self.demande_id} — {self.texte[:40]}"


class PieceDemande(models.Model):
    """
    Une piece jointe a une demande du portail.

    Pas la `piece_jointe` du socle, ancree sur `courrier_id`, ni la
    `piece_dossier` du pilier dossiers : une demande d'usager n'est ni un
    courrier ni un dossier d'instruction, et le jour ou elle devient l'un des
    deux, c'est une piece **de plus**, versee par l'institution.

    `message` est nullable : une piece deposee au moment du depot initial
    n'accompagne aucun message.
    """

    demande = models.ForeignKey(
        DemandeUsager,
        on_delete=models.CASCADE,
        db_column="demande_id",
        related_name="pieces",
    )
    message = models.ForeignKey(
        MessagePortail,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_column="message_id",
        related_name="pieces",
    )
    nom = models.TextField()
    #: Taille telle qu'annoncee par le deposant, en clair (« 1,2 Mo »). Le
    #: stockage du fichier lui-meme n'est pas de ce pilier — voir A45.
    taille = models.TextField()
    deposee_le = models.DateField()
    depose_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="depose_par_id",
        related_name="pieces_portail",
    )

    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "piece_demande"
        ordering = ["-deposee_le", "-id"]
        verbose_name = "pièce d'une demande"
        verbose_name_plural = "pièces des demandes"

    def __str__(self) -> str:
        return self.nom


class EvenementNotifiable(models.Model):
    """
    Ce dont l'usager peut etre prevenu — referentiel ferme.

    `obligatoire` est la colonne qui compte. Deux evenements ne se coupent pas :
    la demande de complement et la decision rendue. Ce sont les deux moments ou
    le silence coute un dossier — l'un ouvre un delai de forclusion, l'autre
    ouvre un delai de recours — et laisser l'usager les desactiver reviendrait a
    le laisser organiser sa propre forclusion.

    La regle vit **ici** et non dans le front. L'ecran grise les deux cases ;
    c'est un confort, pas une garantie : un appel direct a la route les couperait
    tout aussi bien si le serveur ne refusait pas.
    """

    cle = models.TextField(unique=True)
    libelle = models.TextField()
    obligatoire = models.BooleanField(default=False)
    ordre = models.SmallIntegerField(default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "evenement_notifiable"
        ordering = ["ordre", "cle"]
        verbose_name = "événement notifiable"
        verbose_name_plural = "événements notifiables"

    def __str__(self) -> str:
        return f"{self.cle} — {self.libelle}"


class PreferenceNotification(models.Model):
    """
    Le canal choisi par un usager, et ses coordonnees.

    Une ligne par compte, creee a la premiere consultation. L'absence de ligne
    n'est pas une absence de preference : c'est le reglage par defaut, courriel,
    qui est celui du compte.

    `telephone` est nullable et le canal SMS le suppose : le service refuse de
    choisir SMS sans numero, plutot que de basculer silencieusement sur le
    courriel. Un usager qui croit etre prevenu par SMS et ne l'est pas est dans
    une situation pire que celui qui sait qu'il ne l'est pas.
    """

    utilisateur = models.OneToOneField(
        Utilisateur,
        on_delete=models.CASCADE,
        db_column="utilisateur_id",
        related_name="preference_portail",
    )
    courriel = models.EmailField()
    telephone = models.TextField(null=True, blank=True)
    canal = models.TextField(choices=CANAUX, default=CANAL_COURRIEL)

    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "preference_notification"
        verbose_name = "préférence de notification"
        verbose_name_plural = "préférences de notification"

    def __str__(self) -> str:
        return f"{self.utilisateur_id} — {self.canal}"


class PreferenceEvenement(models.Model):
    """
    Le choix d'un usager pour un evenement donne.

    Ne portent une ligne que les evenements **coupes** ? Non : une ligne par
    couple, avec son booleen. Le stockage des seuls refus aurait rendu
    indistinguables « jamais regle » et « refuse », et le jour ou un evenement
    passe actif par defaut, tous les refus anciens seraient devenus des accords.
    """

    preference = models.ForeignKey(
        PreferenceNotification,
        on_delete=models.CASCADE,
        db_column="preference_id",
        related_name="evenements",
    )
    evenement = models.ForeignKey(
        EvenementNotifiable,
        on_delete=models.CASCADE,
        db_column="evenement_id",
        related_name="preferences",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        db_table = "preference_evenement"
        ordering = ["evenement__ordre"]
        verbose_name = "préférence par événement"
        verbose_name_plural = "préférences par événement"
        constraints = [
            models.UniqueConstraint(
                fields=["preference", "evenement"],
                name="unicite_preference_evenement",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.evenement_id} — {'actif' if self.actif else 'coupé'}"


class EchangeDematerialise(models.Model):
    """
    Un cadre d'echange ouvert a un partenaire : marche, convention, reporting.

    Ce n'est pas une demande : l'initiative vient de l'institution, l'objet est
    contractuel, et ce qui est attendu est **compte** — cinq pieces d'un dossier
    de candidature, deux avenants, un reporting trimestriel.

    `attendus` est un nombre et non une liste de pieces nommees. C'est une
    limite assumee de ce premier etat : le §3.13 demande de savoir ou en est le
    depot, pas de tenir le bordereau piece a piece. Voir A46.

    L'etat — « Ouvert », « En attente de votre dépôt », « Clos » — ne figure
    dans aucune colonne : il se deduit de `clos_le` et du compte des pieces
    deposees. ADR 010.
    """

    reference = models.TextField(unique=True)
    intitule = models.TextField()
    nature = models.TextField(choices=NATURES_ECHANGE, default=NATURE_MARCHE)
    partenaire = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="partenaire_id",
        related_name="echanges_portail",
    )
    ouvert_le = models.DateField()
    echeance = models.DateField(null=True, blank=True)
    #: Nombre de pieces attendues du partenaire.
    attendus = models.SmallIntegerField(default=1)
    clos_le = models.DateField(null=True, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "echange_dematerialise"
        ordering = ["-ouvert_le", "-id"]
        verbose_name = "échange dématérialisé"
        verbose_name_plural = "échanges dématérialisés"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attendus__gte=1),
                name="echange_attend_au_moins_une_piece",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.intitule}"


class PieceEchange(models.Model):
    """
    Une piece deposee dans le cadre d'un echange.

    Table distincte de `piece_demande` : les deux ne portent pas le meme objet,
    et une colonne nullable de plus sur l'une d'elles aurait rendu possible une
    piece rattachee aux deux — ou a aucun.
    """

    echange = models.ForeignKey(
        EchangeDematerialise,
        on_delete=models.CASCADE,
        db_column="echange_id",
        related_name="pieces",
    )
    nom = models.TextField()
    taille = models.TextField()
    deposee_le = models.DateField()
    depose_par = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        db_column="depose_par_id",
        related_name="pieces_echange",
    )

    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "piece_echange"
        ordering = ["-deposee_le", "-id"]
        verbose_name = "pièce d'un échange"
        verbose_name_plural = "pièces des échanges"

    def __str__(self) -> str:
        return self.nom

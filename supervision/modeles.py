"""
Supervision technique — ce que le serveur mesure de lui-meme.

**Deux tables, et une decision qui les explique** (ADR 014) : la supervision
rend ce que le serveur **traverse**, et declare le reste. Elle ne simule ni
sonde externe, ni supervision d'infrastructure.

 * `MesureRequete` est un **agregat horaire**. Une ligne par (methode, chemin
   normalise, heure), avec le compte des appels, celui des echecs, et la
   repartition des durees par tranches. Une ligne par requete aurait produit
   des dizaines de millions de lignes pour repondre a une question — « le p95
   tient-il sous deux secondes ? » — a laquelle six compteurs suffisent.

 * `Integration` porte ce que le BRD exige de brancher sur des systemes tiers.
   C'est une table declarative, et elle l'assume : son etat est tenu a la main
   par l'administrateur technique, faute d'une sonde qui interroge chaque
   systeme. Voir A48.

**Ce qui n'est pas ici.** Aucune table d'incidents. Un incident se **deduit**
des heures degradees : la ou le taux d'echec depasse le seuil, sur les mesures
ci-dessus. Une table d'incidents saisis a la main aurait porte un second recit,
alimente par personne — le depot n'expose aucun ecran pour l'ecrire — et un
ecran d'incidents toujours vide se lit comme une plateforme sans panne.
"""

from django.db import models

#: Les bornes des tranches de duree, en millisecondes. La derniere tranche est
#: ouverte. Elles sont choisies autour de l'engagement du BRD — 2 000 ms au p95,
#: RNF-PERF-01 — pour que la reponse a « l'engagement est-il tenu ? » ne depende
#: pas d'une interpolation : une requete est d'un cote ou de l'autre de 2 000.
BORNES_MS = [200, 500, 1000, 2000, 5000]

#: Etats d'une integration. `En construction` n'est pas une panne : c'est une
#: exigence du BRD qui n'est pas encore livree, et l'ecran doit les distinguer.
ETAT_CONNECTE = "Connecté"
ETAT_DEGRADE = "Dégradé"
ETAT_NON_CONNECTE = "Non connecté"
ETAT_CONSTRUCTION = "En construction"
ETATS_INTEGRATION = [
    (ETAT_CONNECTE, "Connecté"),
    (ETAT_DEGRADE, "Dégradé"),
    (ETAT_NON_CONNECTE, "Non connecté"),
    (ETAT_CONSTRUCTION, "En construction"),
]

TYPES_INTEGRATION = [
    ("Annuaire", "Annuaire d'entreprise"),
    ("Messagerie", "Messagerie et SMS"),
    ("Système financier", "Système financier"),
    ("ERP", "Progiciel de gestion"),
    ("Portail usagers", "Portail usagers"),
]


class MesureRequete(models.Model):
    """
    Un agregat horaire des requetes servies — RNF-PERF-01 et RNF-DISP-01.

    Le **chemin est normalise** : `/api/dossiers/412` et `/api/dossiers/7`
    comptent sur la meme ligne, `/api/dossiers/{id}`. Sans cette normalisation,
    une table par identifiant aurait rendu la mesure illisible et son volume
    ingerable.

    Les tranches remplacent le stockage des durees. Le p95 s'en deduit comme la
    **borne haute** de la tranche qui contient le 95e centile : on ne pretend
    pas au millieme de seconde, et l'approximation va toujours dans le sens
    defavorable a l'engagement. Un engagement contractuel se verifie ainsi, pas
    par une moyenne flatteuse.

    `echecs` compte les reponses 5xx. Les 4xx n'en sont pas : un 404 sur une
    demande d'un autre usager est le systeme qui fonctionne, et les compter
    aurait fait chuter la disponibilite a chaque refus legitime.
    """

    methode = models.CharField(max_length=10)
    chemin = models.TextField()
    #: Debut de l'heure mesuree, en UTC. La minute et la seconde sont a zero.
    heure = models.DateTimeField()

    appels = models.IntegerField(default=0)
    echecs = models.IntegerField(default=0)
    #: Somme des durees, pour la moyenne. Le p50 et le p95 viennent des tranches.
    duree_totale_ms = models.BigIntegerField(default=0)
    duree_max_ms = models.IntegerField(default=0)

    #: Repartition par tranches — voir `BORNES_MS`.
    sous_200 = models.IntegerField(default=0)
    sous_500 = models.IntegerField(default=0)
    sous_1000 = models.IntegerField(default=0)
    sous_2000 = models.IntegerField(default=0)
    sous_5000 = models.IntegerField(default=0)
    au_dela = models.IntegerField(default=0)

    class Meta:
        db_table = "mesure_requete"
        ordering = ["-heure", "chemin"]
        verbose_name = "mesure de requête"
        verbose_name_plural = "mesures de requêtes"
        constraints = [
            models.UniqueConstraint(
                fields=["methode", "chemin", "heure"],
                name="unicite_mesure_par_heure",
            ),
        ]
        indexes = [
            models.Index(fields=["-heure"], name="idx_mesure_heure"),
        ]

    def __str__(self) -> str:
        return f"{self.methode} {self.chemin} — {self.heure:%Y-%m-%d %H}h : {self.appels} appels"


class Integration(models.Model):
    """
    Un systeme tiers auquel la plateforme doit se brancher — RF-ADM-02, §3.10.

    Table **declarative**, et c'est une limite assumee : rien n'interroge les
    systemes cites. L'etat est celui que l'administrateur technique constate.
    Le jour ou une sonde existera, elle alimentera `derniere_synchronisation`
    et `erreurs_24h` — les colonnes sont la, vides, plutot que des chiffres
    inventes. Voir A48.

    Le semis initial porte les integrations **exigees** par le BRD et non
    livrees. Les afficher « Non connecté » est la verite ; ne pas les afficher
    du tout aurait laisse croire qu'il n'y a rien a brancher.
    """

    systeme = models.TextField(unique=True)
    type = models.TextField(choices=TYPES_INTEGRATION)
    protocole = models.TextField()
    etat = models.TextField(choices=ETATS_INTEGRATION, default=ETAT_NON_CONNECTE)
    #: Ce qui manque, ou ce que l'integration fait. Affiche tel quel.
    note = models.TextField(null=True, blank=True)
    #: Exigence du BRD qui la demande — « RF-ADM-02 ». Une integration sans
    #: source est une integration que personne n'a demandee.
    exigence = models.TextField(null=True, blank=True)

    derniere_synchronisation = models.DateTimeField(null=True, blank=True)
    latence_ms = models.IntegerField(null=True, blank=True)
    volume_dernier_passage = models.IntegerField(null=True, blank=True)
    erreurs_24h = models.IntegerField(default=0)

    ordre = models.SmallIntegerField(default=0)
    actif = models.BooleanField(default=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integration"
        ordering = ["ordre", "systeme"]
        verbose_name = "intégration"
        verbose_name_plural = "intégrations"

    def __str__(self) -> str:
        return f"{self.systeme} — {self.etat}"

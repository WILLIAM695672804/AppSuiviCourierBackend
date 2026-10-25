"""
Formes echangees par la tracabilite.

Miroir de `frontend/src/features/tracabilite/api.ts`.

Les libelles sont **accentues** ici et sans accent partout ailleurs dans le
backend : ce sont des valeurs affichees, pas des identifiants. « Paramétrage »
est ce que l'ecran montre et ce que le filtre renvoie ; le code, lui, s'ecrit
`parametre_modifie`.
"""

from ninja import Schema


class Compteur(Schema):
    """Un chiffre de tete d'ecran, deja formate. L'ecran n'agrege rien."""

    libelle: str
    valeur: str
    note: str
    ton: str


class Champ(Schema):
    libelle: str
    valeur: str


class Difference(Schema):
    """
    Une valeur avant, une valeur apres.

    C'est la difference entre « quelqu'un a modifie le delai » et « le delai est
    passe de 72 h a 48 h ». Vient de `champ_historique`, alimentee par
    declencheur — donc y compris pour une modification faite hors application.
    """

    champ: str
    avant: str
    apres: str


class EvenementJournal(Schema):
    id: int
    heure: str
    date: str
    #: Famille d'affichage, jamais le `type_evenement` brut. Voir
    #: `lecture.FAMILLES`.
    type: str
    libelle: str
    #: Reference du courrier concerne. Toujours `None` tant que le pilier
    #: courrier n'existe pas : on ne fabrique pas de reference.
    courrier: str | None
    courrierId: int | None
    auteur: str
    initiales: str
    poste: str
    champs: list[Champ]
    differences: list[Difference]


class JournalEvenements(Schema):
    compteurs: list[Compteur]
    evenements: list[EvenementJournal]


class ChampAcces(Schema):
    libelle: str
    valeur: str
    #: Colore la valeur en rouge. Porte sur le champ, pas sur la ligne.
    alerte: bool


class LigneActivite(Schema):
    libelle: str
    valeur: str
    #: Deja formatee en pourcentage (« 42% ») : c'est une largeur de barre.
    part: str
    alerte: bool


class AccesJournal(Schema):
    id: int
    heure: str
    date: str
    agent: str
    initiales: str
    poste: str
    objet: str
    #: La session courrier de l'agent, ou « — ». Un agent hors session n'est
    #: pas une anomalie : la plupart des postes n'en ont pas.
    session: str
    action: str
    #: « Conforme » ou « Signalé ». Calcule, jamais stocke — voir
    #: `lecture._signaler`.
    controle: str
    champs: list[ChampAcces]
    #: **Pourquoi** l'acces est signale, ou pourquoi il ne l'est pas. Une
    #: pastille sans explication ne produit qu'un soupcon.
    motif: str
    alerte: bool
    activite: list[LigneActivite]


class JournalAcces(Schema):
    acces: list[AccesJournal]
    signales: int


class TableTracee(Schema):
    """Une table portant le declencheur d'historisation, et son volume."""

    cle: str
    libelle: str
    #: Rendu meme a zero : une table livree mais jamais modifiee doit figurer au
    #: selecteur. L'omettre ferait croire qu'elle n'est pas tracee.
    modifications: int


class ModificationChamp(Schema):
    """
    Une colonne qui a change — I-03.

    A ne pas confondre avec `EvenementJournal` : celui-ci dit ce que
    l'application a **fait**, celle-la ce qui a **changé**. Les deux tables sont
    alimentees par des chemins independants, et c'est ce qui rend `horsApplication`
    possible.
    """

    id: int
    date: str
    heure: str
    #: Le nom SQL de la table. L'ecran affiche `tableLibelle`, mais un auditeur
    #: qui recoupe avec la base a besoin du nom reel.
    table: str
    tableLibelle: str
    ligneId: int
    #: Le nom de la colonne, tel qu'il est en base. Non traduit — voir
    #: `lecture.historique_champs`.
    colonne: str
    avant: str
    apres: str
    auteur: str
    initiales: str
    poste: str
    #: **Aucun evenement applicatif n'explique cette modification.** C'est la
    #: ligne qu'un auditeur regarde en premier : correction en base, script de
    #: reprise, intervention hors application.
    horsApplication: bool


class HistoriqueChamps(Schema):
    tables: list[TableTracee]
    modifications: list[ModificationChamp]
    #: Combien, parmi les modifications rendues, n'ont aucun evenement
    #: correspondant. Porte sur ce qui est affiche, pas sur la table entiere.
    horsApplication: int

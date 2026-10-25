"""
Contrat des ecrans du portail usagers.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/portail/api.ts`.

Deux ecarts au front tel qu'il etait ecrit, tous deux dans le sens du serveur :

 * `MesDemandes` porte `delaiReponseJours`. Le front annoncait « trente jours »
   en dur dans le texte du formulaire de depot. Un delai annonce avant le depot
   est un engagement : il doit venir de la ou il est regle, sinon la promesse
   affichee et la date calculee divergent au premier arbitrage.
 * `EvenementPreference` porte `obligatoire`. Le front tenait la liste des deux
   notifications non desactivables dans une constante. Elle vit desormais en
   base, et l'ecran la lit.
"""

from ninja import Schema

# =====================================================================
#  Mes demandes
# =====================================================================


class DemandeUsagerSortie(Schema):
    id: int
    reference: str
    objet: str
    type: str
    deposeeLe: str
    #: Ce que l'institution s'est engagee a tenir, fige au depot.
    reponseAttendueLe: str
    etat: str
    #: Vrai quand le portail attend quelque chose de l'usager. C'est le seul
    #: critere de tri de l'ecran.
    actionAttendue: bool
    serviceInstructeur: str


class MesDemandes(Schema):
    demandes: list[DemandeUsagerSortie]
    identite: str
    #: Le delai annonce **avant** le depot. Voir la docstring du module.
    delaiReponseJours: int


# =====================================================================
#  Le suivi d'une demande
# =====================================================================


class EtapeUsager(Schema):
    libelle: str
    franchie: bool
    date: str | None = None
    #: Formulee pour l'usager, jamais dans le vocabulaire de l'institution.
    explication: str


class PieceSortie(Schema):
    nom: str
    taille: str


class MessageSortie(Schema):
    id: int
    #: « Vous » ou « Institution ». Deduit de l'auteur, pas stocke.
    auteur: str
    nom: str
    date: str
    texte: str
    pieces: list[PieceSortie]


class PieceDemandeSortie(Schema):
    id: int
    nom: str
    taille: str
    deposeeLe: str
    parVous: bool


class ComplementAttendu(Schema):
    objet: str
    avantLe: str


class DemandeUsagerDetail(DemandeUsagerSortie):
    contexte: str
    etapes: list[EtapeUsager]
    messages: list[MessageSortie]
    pieces: list[PieceDemandeSortie]
    #: `null` quand rien n'est reclame.
    complementAttendu: ComplementAttendu | None = None


# =====================================================================
#  Preferences de notification
# =====================================================================


class EvenementPreference(Schema):
    cle: str
    libelle: str
    actif: bool
    #: Vrai pour la demande de complement et la decision rendue. Le serveur les
    #: rallume quoi qu'on lui envoie.
    obligatoire: bool


class Preferences(Schema):
    courriel: str
    telephone: str | None = None
    canal: str
    evenements: list[EvenementPreference]


# =====================================================================
#  Echanges dematerialises
# =====================================================================


class EchangeSortie(Schema):
    id: int
    reference: str
    intitule: str
    nature: str
    ouvertLe: str
    echeance: str | None = None
    attendus: int
    deposes: int
    etat: str


class Echanges(Schema):
    echanges: list[EchangeSortie]


# =====================================================================
#  Entrees
# =====================================================================


class PieceSaisie(Schema):
    nom: str
    taille: str = ""


class SaisieDemande(Schema):
    type: str
    objet: str
    contexte: str
    pieces: list[PieceSaisie] = []


class SaisieMessage(Schema):
    demandeId: int
    texte: str
    pieces: list[PieceSaisie] = []


class SaisiePreferences(Schema):
    courriel: str
    telephone: str | None = None
    canal: str
    #: Les cles **retenues**. Celles qui manquent sont coupees — sauf les
    #: obligatoires, que le serveur rallume.
    evenements: list[str] = []


class Creation(Schema):
    id: int

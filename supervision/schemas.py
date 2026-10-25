"""
Contrat des deux ecrans de supervision.

Convention de sortie du depot : **camelCase**, en miroir de
`frontend/src/features/supervision/api.ts`.

Un point de vigilance : `p50Ms` et `p95Ms` sont des **majorants par tranche**,
pas des mesures au millieme de seconde. Le serveur ne conserve pas les durees
requete par requete — il compte des tranches (voir `supervision/modeles.py`).
Un p95 rendu a 2 000 ms signifie « 95 % des appels sont passes sous deux
secondes », pas « le 95e appel le plus lent a duré 2 000 ms ».
"""

from ninja import Schema


class ServicePlateforme(Schema):
    nom: str
    role: str
    etat: str
    #: Disponibilite constatee sur trente jours glissants, en pourcentage. Zero
    #: quand rien n'est mesure — c'est le feu « inconnu » qui porte la nuance.
    disponibilite: float
    tempsReponseMs: int
    feu: str


class Incident(Schema):
    id: int
    debut: str
    fin: str | None = None
    gravite: str
    service: str
    resume: str
    impact: str
    resolution: str | None = None
    dureeMinutes: int | None = None


class PerformanceEcran(Schema):
    #: Le chemin de l'API, tel qu'il figure dans les journaux du serveur.
    ecran: str
    appels24h: int
    p50Ms: int
    p95Ms: int
    feu: str


class Compteur(Schema):
    libelle: str
    valeur: str
    note: str
    feu: str


class PlanReprise(Schema):
    #: `null` : aucun test de reprise n'a jamais eu lieu. Ce n'est pas zero.
    dernierTest: str | None = None
    dureeRepriseMinutes: int | None = None
    cibleMinutes: int
    feu: str


class Supervision(Schema):
    disponibilite30j: float
    cibleDisponibilite: float
    services: list[ServicePlateforme]
    incidents: list[Incident]
    performances: list[PerformanceEcran]
    compteurs: list[Compteur]
    pra: PlanReprise


class EtatSso(Schema):
    actif: bool
    fournisseur: str
    protocole: str
    domaines: list[str]
    comptesAnnuaire: int
    comptesLocaux: int
    dernierImport: str | None = None
    #: Le chiffre qui compte : tant qu'il n'est pas nul, le SSO est une porte
    #: parmi deux.
    connexionsSso7j: int
    connexionsLocales7j: int
    feu: str


class Integration(Schema):
    id: int
    systeme: str
    type: str
    protocole: str
    etat: str
    derniereSynchronisation: str | None = None
    latenceMs: int | None = None
    volumeDernierPassage: int | None = None
    erreurs24h: int
    feu: str
    note: str | None = None


class Integrations(Schema):
    sso: EtatSso
    integrations: list[Integration]
    compteurs: list[Compteur]

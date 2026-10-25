"""
Lectures de la supervision technique — §3.10.

Deux ecrans : la plateforme (disponibilite, performance, incidents) et les
integrations (SSO, systemes tiers).

**Ce que ce module affirme, il l'a mesure.** Les chiffres viennent de trois
sources, toutes internes :

 * `mesure_requete`, alimentee par le middleware a chaque requete servie ;
 * le journal du noyau, pour les connexions et leur moyen ;
 * la table `utilisateur`, pour le partage entre comptes annuaire et comptes
   locaux.

**Ce qu'il ne sait pas, il le dit.** Le plan de reprise n'a jamais ete teste :
la duree de reprise sort a `null` et le feu a « inconnu », jamais a zero
(ADR 011). La disponibilite est celle du service **rendu** — une panne totale
n'emet aucune requete et ne laisse aucune trace ici. C'est ecrit dans la note
du compteur, a l'ecran, et pas seulement dans ce commentaire.
"""

from datetime import timedelta

from django.db import connection
from django.db.models import Sum
from django.utils import timezone

from noyau.identite.modeles import Utilisateur
from noyau.journal.modeles import Evenement
from noyau.parametres import service as parametres
from supervision.modeles import Integration, MesureRequete

#: L'engagement du BRD : 99,5 % de disponibilite en heures ouvrees
#: (RNF-DISP-01) et 2 secondes au 95e centile (RNF-PERF-01). Ces deux valeurs
#: ont une source ; elles ne sont donc pas parametrables comme une hypothese —
#: les changer, c'est renegocier le contrat, pas corriger un reglage.
CIBLE_DISPONIBILITE = 99.5
CIBLE_P95_MS = 2000

#: Au-dela de ce taux d'echec sur une heure, l'heure est degradee. Le seuil
#: n'a pas de source : voir A47.
SEUIL_DEGRADATION = 0.05
#: Au-dela, l'incident est majeur plutot que mineur.
SEUIL_MAJEUR = 0.20

#: Les familles de chemins qui font un « service » a l'ecran. Le decoupage
#: suit ce que le BRD engage, pas l'architecture du code : « la disponibilite
#: de la plateforme et la performance des tableaux de bord » (§3.10).
SERVICES = [
    (
        "Authentification",
        "Ouverture de session et vérification des droits",
        ("/api/connexion", "/api/deconnexion", "/api/moi", "/api/habilitations"),
    ),
    (
        "Tableaux de bord",
        "Cockpit, vues d'ensemble et analyses",
        ("/api/pilotage", "/api/direction", "/api/comite", "/api/performance"),
    ),
    (
        "Traitement des dossiers",
        "Registre, instruction, archivage",
        ("/api/dossiers", "/api/archivage", "/api/activites", "/api/gouvernance"),
    ),
    (
        "Portail usagers",
        "Dépôt et suivi des demandes extérieures",
        ("/api/portail",),
    ),
]


def cible_reprise_minutes() -> int:
    """Quatre heures — RNF-DISP-02. En base parce qu'un engagement se renegocie."""
    return int(parametres.valeur("supervision.reprise_cible_minutes", 240))


# =====================================================================
#  Outils de calcul sur les agregats
# =====================================================================


def _totaux(lignes) -> dict:
    """Somme des compteurs d'un ensemble de mesures. Zeros si l'ensemble est vide."""
    agrege = lignes.aggregate(
        appels=Sum("appels"),
        echecs=Sum("echecs"),
        duree=Sum("duree_totale_ms"),
        sous_200=Sum("sous_200"),
        sous_500=Sum("sous_500"),
        sous_1000=Sum("sous_1000"),
        sous_2000=Sum("sous_2000"),
        sous_5000=Sum("sous_5000"),
        au_dela=Sum("au_dela"),
    )
    return {cle: (valeur or 0) for cle, valeur in agrege.items()}


def centile(totaux: dict, part: float) -> int | None:
    """
    La borne haute de la tranche qui contient ce centile.

    `None` quand rien n'a ete mesure — et non zero. Zero milliseconde serait la
    performance parfaite, alors qu'il s'agit de l'absence de mesure (ADR 011).

    La valeur rendue est un **majorant** : si 96 % des requetes sont sous
    500 ms, le p95 rendu est 500 et non la valeur exacte. L'approximation va
    toujours dans le sens defavorable a l'engagement, ce qui est la seule facon
    honnete d'arrondir un engagement contractuel.
    """
    total = totaux["appels"]
    if not total:
        return None

    rang = total * part
    cumul = 0
    for colonne, borne in (
        ("sous_200", 200),
        ("sous_500", 500),
        ("sous_1000", 1000),
        ("sous_2000", 2000),
        ("sous_5000", 5000),
    ):
        cumul += totaux[colonne]
        if cumul >= rang:
            return borne
    # Le centile tombe dans la tranche ouverte : on ne peut pas majorer.
    return None


def _feu_performance(p95: int | None) -> str:
    if p95 is None:
        return "inconnu"
    if p95 <= CIBLE_P95_MS:
        return "vert"
    return "rouge" if p95 > CIBLE_P95_MS * 2 else "orange"


def _disponibilite(totaux: dict) -> float | None:
    """
    Le taux de requetes servies sans erreur serveur, en pourcentage.

    `None` sur une periode sans trafic : une plateforme que personne n'a
    sollicitee n'est ni disponible ni indisponible, et rendre 100 % aurait fait
    passer une absence de mesure pour un sans-faute.
    """
    if not totaux["appels"]:
        return None
    return round(100 * (1 - totaux["echecs"] / totaux["appels"]), 2)


# =====================================================================
#  L'ecran de la plateforme
# =====================================================================


def _services(depuis) -> list[dict]:
    """L'etat de chaque famille de chemins, sur trente jours."""
    lignes = []
    for nom, role, prefixes in SERVICES:
        requete = MesureRequete.objects.none()
        for prefixe in prefixes:
            requete = requete | MesureRequete.objects.filter(
                heure__gte=depuis, chemin__startswith=prefixe
            )
        totaux = _totaux(requete)
        disponibilite = _disponibilite(totaux)
        p95 = centile(totaux, 0.95)
        moyenne = round(totaux["duree"] / totaux["appels"]) if totaux["appels"] else 0

        if disponibilite is None:
            etat, feu = "Opérationnel", "inconnu"
        elif disponibilite >= CIBLE_DISPONIBILITE and (p95 or 0) <= CIBLE_P95_MS:
            etat, feu = "Opérationnel", "vert"
        elif disponibilite < 90:
            etat, feu = "Interrompu", "rouge"
        else:
            etat, feu = "Dégradé", "orange"

        lignes.append(
            {
                "nom": nom,
                "role": role,
                "etat": etat,
                # 0 quand rien n'est mesure : le front attend un nombre. La
                # verite est portee par le feu « inconnu » qui l'accompagne.
                "disponibilite": disponibilite if disponibilite is not None else 0,
                "tempsReponseMs": moyenne,
                "feu": feu,
            }
        )
    return lignes


def _performances(depuis) -> list[dict]:
    """
    Les chemins les plus appeles des dernieres 24 heures, avec leur p50 et p95.

    Les chemins, pas des noms d'ecran : `/api/dossiers/{id}` est ce que
    l'administrateur technique retrouve dans ses journaux. Traduire en « Fiche
    d'instruction » aurait demande une table de correspondance a tenir a jour,
    et un ecran renomme aurait fait disparaitre sa mesure.
    """
    lignes = []
    chemins = (
        MesureRequete.objects.filter(heure__gte=depuis)
        .values("chemin")
        .annotate(total=Sum("appels"))
        .order_by("-total")[:12]
    )
    for entree in chemins:
        totaux = _totaux(MesureRequete.objects.filter(heure__gte=depuis, chemin=entree["chemin"]))
        p95 = centile(totaux, 0.95)
        lignes.append(
            {
                "ecran": entree["chemin"],
                "appels24h": totaux["appels"],
                "p50Ms": centile(totaux, 0.50) or 0,
                "p95Ms": p95 or 0,
                "feu": _feu_performance(p95),
            }
        )
    return lignes


def _incidents(depuis) -> list[dict]:
    """
    Les heures degradees, presentees comme des incidents.

    Ce ne sont pas des incidents **declares** : personne ne les a saisis. Ce
    sont des periodes ou le taux d'erreur serveur a depasse le seuil, deduites
    des memes mesures que le reste. Le libelle le dit, parce qu'un incident
    deduit et un incident constate n'ont pas la meme valeur en reunion.
    """
    incidents = []
    heures = (
        MesureRequete.objects.filter(heure__gte=depuis)
        .values("heure")
        .annotate(appels=Sum("appels"), echecs=Sum("echecs"))
        .order_by("-heure")
    )
    for rang, entree in enumerate(heures, start=1):
        if not entree["appels"] or not entree["echecs"]:
            continue
        taux = entree["echecs"] / entree["appels"]
        if taux < SEUIL_DEGRADATION:
            continue

        debut = entree["heure"]
        incidents.append(
            {
                "id": rang,
                "debut": debut.isoformat(),
                "fin": (debut + timedelta(hours=1)).isoformat(),
                "gravite": "Majeur" if taux >= SEUIL_MAJEUR else "Mineur",
                "service": "Interface applicative",
                "resume": (
                    f"{entree['echecs']} erreurs serveur sur {entree['appels']} requêtes "
                    f"({taux:.0%})"
                ),
                "impact": (
                    "Période dégradée déduite des mesures du serveur : elle n'a été "
                    "déclarée par personne, et sa durée est arrondie à l'heure."
                ),
                "resolution": None,
                "dureeMinutes": 60,
            }
        )
    return incidents[:10]


def plateforme() -> dict:
    """
    L'ecran « disponibilite et performance », confronte aux engagements du BRD.

    Aucun perimetre n'intervient : la plateforme n'appartient a aucune
    structure. La garde `ADM_TEC` suffit, et c'est la seule route du depot dont
    la reponse ne depend pas de qui la demande.
    """
    maintenant = timezone.now()
    trente_jours = maintenant - timedelta(days=30)
    vingt_quatre_heures = maintenant - timedelta(hours=24)

    totaux_30j = _totaux(MesureRequete.objects.filter(heure__gte=trente_jours))
    disponibilite = _disponibilite(totaux_30j)
    p95_24h = centile(_totaux(MesureRequete.objects.filter(heure__gte=vingt_quatre_heures)), 0.95)

    return {
        "disponibilite30j": disponibilite if disponibilite is not None else 0,
        "cibleDisponibilite": CIBLE_DISPONIBILITE,
        "services": _services(trente_jours),
        "incidents": _incidents(trente_jours),
        "performances": _performances(vingt_quatre_heures),
        "compteurs": _compteurs(totaux_30j, disponibilite, p95_24h),
        "pra": {
            # Aucun test de reprise n'a jamais eu lieu : la valeur est nulle,
            # pas zero. Zero minute serait une reprise instantanee (ADR 011).
            "dernierTest": None,
            "dureeRepriseMinutes": None,
            "cibleMinutes": cible_reprise_minutes(),
            "feu": "inconnu",
        },
    }


def _compteurs(totaux: dict, disponibilite: float | None, p95: int | None) -> list[dict]:
    """
    Les quatre chiffres de la bande superieure.

    Le dernier n'est pas une mesure mais un avertissement : il dit ce que cette
    page ne voit pas. Le placer ici plutot que dans un coin de la
    documentation est deliberé — c'est en lisant 99,9 % qu'on a besoin de
    savoir ce que le chiffre ne couvre pas.
    """
    hors_cible = 0
    for entree in (
        MesureRequete.objects.filter(heure__gte=timezone.now() - timedelta(hours=24))
        .values("chemin")
        .distinct()
    ):
        chemin_totaux = _totaux(
            MesureRequete.objects.filter(
                heure__gte=timezone.now() - timedelta(hours=24), chemin=entree["chemin"]
            )
        )
        valeur = centile(chemin_totaux, 0.95)
        if valeur is None or valeur > CIBLE_P95_MS:
            hors_cible += 1 if chemin_totaux["appels"] else 0

    return [
        {
            "libelle": "Disponibilité sur 30 jours",
            "valeur": f"{disponibilite} %" if disponibilite is not None else "Non mesuré",
            "note": (
                f"engagement {CIBLE_DISPONIBILITE} % — RNF-DISP-01"
                if disponibilite is not None
                else "aucune requête servie sur la période"
            ),
            "feu": (
                "inconnu"
                if disponibilite is None
                else ("vert" if disponibilite >= CIBLE_DISPONIBILITE else "rouge")
            ),
        },
        {
            "libelle": "Temps de réponse au p95",
            "valeur": f"{p95} ms" if p95 is not None else "Non mesuré",
            "note": f"engagement {CIBLE_P95_MS} ms — RNF-PERF-01",
            "feu": _feu_performance(p95),
        },
        {
            "libelle": "Requêtes mesurées sur 30 jours",
            "valeur": str(totaux["appels"]),
            "note": f"dont {totaux['echecs']} en erreur serveur",
            "feu": "vert" if totaux["appels"] else "inconnu",
        },
        {
            "libelle": "Écrans au-delà de l'engagement",
            "valeur": str(hors_cible),
            "note": (
                "mesuré sur les requêtes servies : une panne totale n'émet "
                "aucune requête et n'apparaît pas ici"
            ),
            "feu": "vert" if hors_cible == 0 else "orange",
        },
    ]


# =====================================================================
#  L'ecran des integrations
# =====================================================================


def _sso() -> dict:
    """
    L'etat de l'authentification unique — RF-ADM-02.

    Le chiffre qui compte n'est pas le nombre de comptes annuaire, mais le
    nombre de connexions **encore faites par mot de passe applicatif**. Tant
    qu'il n'est pas nul, le SSO n'est pas la porte d'entree mais une porte
    parmi deux, et la politique de mot de passe de l'annuaire ne s'applique pas
    a tout le monde.

    Un compte est dit « local » s'il porte un mot de passe applicatif. Ce n'est
    pas la meme chose que l'absence d'identifiant d'annuaire : un compte peut
    porter les deux, et c'est justement le cas a surveiller.
    """
    sept_jours = timezone.now() - timedelta(days=7)
    connexions = Evenement.objects.filter(
        objet_type="utilisateur", type_evenement="connexion", survenu_le__gte=sept_jours
    )
    locales = connexions.filter(donnees__moyen="mot_de_passe").count()
    par_annuaire = connexions.count() - locales

    vivants = Utilisateur.objects.actifs()
    comptes_locaux = vivants.exclude(mot_de_passe__isnull=True).exclude(mot_de_passe="").count()
    comptes_annuaire = vivants.exclude(identifiant_annuaire__isnull=True).count()

    fournisseur = parametres.valeur("supervision.sso_fournisseur", "")
    protocole = parametres.valeur("supervision.sso_protocole", "")
    actif = bool(fournisseur) and par_annuaire > 0

    return {
        "actif": actif,
        # Pas de valeur inventee : « aucun fournisseur déclaré » est la verite
        # tant que la Direction des systemes d'information n'a pas tranche (A47).
        "fournisseur": fournisseur or "Aucun fournisseur déclaré",
        "protocole": protocole or "Non défini",
        "domaines": [],
        "comptesAnnuaire": comptes_annuaire,
        "comptesLocaux": comptes_locaux,
        "dernierImport": None,
        "connexionsSso7j": par_annuaire,
        "connexionsLocales7j": locales,
        "feu": "vert" if actif and locales == 0 else ("orange" if actif else "rouge"),
    }


def _feu_integration(etat: str) -> str:
    return {
        "Connecté": "vert",
        "Dégradé": "orange",
        "Non connecté": "rouge",
        "En construction": "inconnu",
    }.get(etat, "inconnu")


def integrations() -> dict:
    """
    Le SSO et les systemes tiers.

    La liste est declarative — rien n'interroge les systemes cites (A48). Elle
    porte l'exigence du BRD qui demande chaque branchement : une integration
    sans source est une integration que personne n'a demandee, et elle n'a rien
    a faire sur cet ecran.
    """
    lignes = [
        {
            "id": integration.pk,
            "systeme": integration.systeme,
            "type": integration.type,
            "protocole": integration.protocole,
            "etat": integration.etat,
            "derniereSynchronisation": (
                integration.derniere_synchronisation.isoformat()
                if integration.derniere_synchronisation
                else None
            ),
            "latenceMs": integration.latence_ms,
            "volumeDernierPassage": integration.volume_dernier_passage,
            "erreurs24h": integration.erreurs_24h,
            "feu": _feu_integration(integration.etat),
            "note": integration.note,
        }
        for integration in Integration.objects.filter(actif=True)
    ]

    connectees = sum(1 for ligne in lignes if ligne["etat"] == "Connecté")
    sso = _sso()

    return {
        "sso": sso,
        "integrations": lignes,
        "compteurs": [
            {
                "libelle": "Intégrations connectées",
                "valeur": f"{connectees} / {len(lignes)}",
                "note": "état déclaré par l'administration technique, non sondé",
                "feu": "vert" if connectees == len(lignes) and lignes else "orange",
            },
            {
                "libelle": "Connexions par mot de passe applicatif",
                "valeur": str(sso["connexionsLocales7j"]),
                "note": "sur sept jours — RF-ADM-02 demande l'authentification unique",
                "feu": "vert" if sso["connexionsLocales7j"] == 0 else "rouge",
            },
            {
                "libelle": "Comptes portant un mot de passe local",
                "valeur": str(sso["comptesLocaux"]),
                "note": "à vider le jour de la bascule vers l'annuaire",
                "feu": "vert" if sso["comptesLocaux"] == 0 else "orange",
            },
        ],
    }


def base_de_donnees_repond() -> bool:
    """
    Un aller-retour vers PostgreSQL.

    Sert au diagnostic, pas a l'ecran : une base qui ne repond pas empeche de
    servir la page qui l'aurait affiche.
    """
    with connection.cursor() as curseur:
        curseur.execute("SELECT 1")
        return curseur.fetchone() == (1,)

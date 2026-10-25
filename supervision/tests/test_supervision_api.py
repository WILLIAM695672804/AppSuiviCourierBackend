"""
La supervision technique — `/api/supervision*`.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **Un engagement contractuel se verifie, il ne s'arrondit pas en sa faveur.**
    Le p95 rendu est un majorant par tranche ; s'il devenait une moyenne, une
    plateforme hors engagement passerait pour conforme.
 2. **L'absence de mesure n'est pas la perfection.** Une plateforme sans trafic
    ne rend pas 100 % de disponibilite, et un plan de reprise jamais teste ne
    rend pas zero minute (ADR 011).
 3. **Un 404 n'est pas une panne.** Compter les 4xx comme des echecs aurait
    fait chuter la disponibilite a chaque refus legitime — et le portail en
    produit par construction.
 4. **Le chemin est normalise.** Sans cela, une table par identifiant rend la
    mesure illisible et son volume ingerable.
 5. **Le chiffre qui compte pour le SSO est le nombre de connexions encore
    faites par mot de passe applicatif**, pas le nombre de comptes annuaire.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from noyau.identite.modeles import Utilisateur
from noyau.journal.service import inscrire
from noyau.parametres.service import vider_cache
from supervision.lecture import centile
from supervision.mesure import enregistrer, normaliser, tranche
from supervision.modeles import Integration, MesureRequete

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
PLATEFORME = "/api/supervision"
INTEGRATIONS = "/api/supervision/integrations"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    vider_cache()
    yield
    vider_cache()


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


def _mesure(
    chemin: str,
    *,
    heures: int = 1,
    appels: int = 100,
    echecs: int = 0,
    tranches: dict | None = None,
) -> MesureRequete:
    """Une ligne d'agregat posee a la main, `heures` heures avant maintenant."""
    defauts = {"sous_200": appels}
    return MesureRequete.objects.create(
        methode="GET",
        chemin=chemin,
        heure=(timezone.now() - timedelta(hours=heures)).replace(minute=0, second=0, microsecond=0),
        appels=appels,
        echecs=echecs,
        duree_totale_ms=appels * 150,
        duree_max_ms=400,
        **(tranches or defauts),
    )


# =====================================================================
#  La normalisation des chemins
# =====================================================================


def test_les_identifiants_disparaissent_du_chemin():
    assert normaliser("/api/dossiers/412") == "/api/dossiers/{id}"
    assert (
        normaliser("/api/dossiers/412/complements/7/reception")
        == "/api/dossiers/{id}/complements/{id}/reception"
    )


def test_un_identifiant_negatif_est_normalise_aussi():
    """
    La file des versements designe par un identifiant negatif un dossier clos
    qui n'est pas encore verse. Sans le signe, ces appels auraient fabrique une
    ligne de mesure par dossier.
    """
    assert normaliser("/api/archivage/versements/-42") == "/api/archivage/versements/{id}"


def test_une_reference_metier_est_normalisee():
    assert normaliser("/api/dossiers/DOS-2026-0001") == "/api/dossiers/{id}"


def test_un_segment_de_route_n_est_pas_pris_pour_un_identifiant():
    assert normaliser("/api/pilotage/vue-ensemble") == "/api/pilotage/vue-ensemble"
    assert normaliser("/api/portail/demandes") == "/api/portail/demandes"


def test_les_tranches_encadrent_l_engagement_du_brd():
    """2 000 ms est une borne : une requete est d'un cote ou de l'autre."""
    assert tranche(199) == "sous_200"
    assert tranche(1999) == "sous_2000"
    assert tranche(2000) == "sous_5000"
    assert tranche(9000) == "au_dela"


# =====================================================================
#  Le calcul des centiles
# =====================================================================


def test_le_p95_est_un_majorant_de_tranche():
    """
    96 % des appels sous 500 ms : le p95 rendu est 500, pas la valeur exacte.
    L'arrondi va toujours dans le sens defavorable a l'engagement.
    """
    totaux = {
        "appels": 100,
        "sous_200": 90,
        "sous_500": 6,
        "sous_1000": 2,
        "sous_2000": 2,
        "sous_5000": 0,
        "au_dela": 0,
    }

    assert centile(totaux, 0.95) == 500
    assert centile(totaux, 0.50) == 200


def test_le_centile_est_nul_sans_aucune_mesure():
    """Zero milliseconde serait la performance parfaite (ADR 011)."""
    vide = {
        "appels": 0,
        "sous_200": 0,
        "sous_500": 0,
        "sous_1000": 0,
        "sous_2000": 0,
        "sous_5000": 0,
        "au_dela": 0,
    }

    assert centile(vide, 0.95) is None


def test_un_centile_dans_la_tranche_ouverte_ne_se_majore_pas():
    """
    10 % des appels au-dela de 5 secondes : le p95 n'a pas de borne haute. On
    rend `None` plutot que 5 000, qui aurait fait croire au respect d'un plafond.
    """
    totaux = {
        "appels": 100,
        "sous_200": 80,
        "sous_500": 5,
        "sous_1000": 5,
        "sous_2000": 0,
        "sous_5000": 0,
        "au_dela": 10,
    }

    assert centile(totaux, 0.95) is None


# =====================================================================
#  L'ecriture des mesures
# =====================================================================


def test_deux_appels_de_la_meme_heure_tiennent_sur_une_ligne(db):
    enregistrer("GET", "/api/dossiers", 120, 200)
    enregistrer("GET", "/api/dossiers", 340, 200)

    ligne = MesureRequete.objects.get(chemin="/api/dossiers")
    assert ligne.appels == 2
    assert ligne.sous_200 == 1
    assert ligne.sous_500 == 1
    assert ligne.duree_totale_ms == 460
    assert ligne.duree_max_ms == 340


def test_un_404_n_est_pas_un_echec(db):
    """
    Le portail rend 404 chaque fois qu'un usager demande la demande d'un autre.
    Les compter aurait fait chuter la disponibilite a chaque refus legitime.
    """
    enregistrer("GET", "/api/portail/demandes/{id}", 80, 404)
    enregistrer("GET", "/api/portail/demandes/{id}", 90, 409)
    enregistrer("GET", "/api/portail/demandes/{id}", 95, 500)

    ligne = MesureRequete.objects.get(chemin="/api/portail/demandes/{id}")
    assert ligne.appels == 3
    assert ligne.echecs == 1


def test_la_duree_maximale_ne_recule_pas(db):
    enregistrer("GET", "/api/dossiers", 900, 200)
    enregistrer("GET", "/api/dossiers", 100, 200)

    assert MesureRequete.objects.get(chemin="/api/dossiers").duree_max_ms == 900


def test_le_middleware_mesure_les_requetes_reelles(connecte):
    """
    Bout en bout : une requete servie laisse sa trace, sous son chemin
    normalise et avec la methode employee.
    """
    MesureRequete.objects.all().delete()
    connecte("admin.tech").get(PLATEFORME)

    ligne = MesureRequete.objects.get(chemin="/api/supervision")
    assert ligne.methode == "GET"
    assert ligne.appels == 1


# =====================================================================
#  L'ecran de la plateforme
# =====================================================================


def test_la_disponibilite_se_confronte_a_l_engagement(connecte):
    _mesure("/api/dossiers", appels=1000, echecs=2)

    corps = connecte("admin.tech").get(PLATEFORME).json()

    assert corps["cibleDisponibilite"] == 99.5
    # 998 requetes servies sur 1000 : 99,8 %, l'engagement est tenu.
    assert corps["disponibilite30j"] >= 99.5
    compteur = corps["compteurs"][0]
    assert "RNF-DISP-01" in compteur["note"]
    assert compteur["feu"] == "vert"


def test_une_disponibilite_sous_l_engagement_passe_au_rouge(connecte):
    _mesure("/api/dossiers", appels=1000, echecs=40)

    corps = connecte("admin.tech").get(PLATEFORME).json()

    assert corps["disponibilite30j"] == 96.0
    assert corps["compteurs"][0]["feu"] == "rouge"


def test_sans_trafic_la_plateforme_ne_dit_pas_cent_pour_cent(connecte):
    """
    Une plateforme que personne n'a sollicitee n'est ni disponible ni
    indisponible. Le middleware mesure la requete du test lui-meme ; on efface
    donc les mesures juste avant de lire, pour eprouver le cas vide.
    """
    client = connecte("admin.tech")
    MesureRequete.objects.all().delete()

    corps = client.get(PLATEFORME).json()

    assert corps["compteurs"][0]["valeur"] == "Non mesuré"
    assert corps["compteurs"][0]["feu"] == "inconnu"


def test_le_plan_de_reprise_avoue_n_avoir_jamais_ete_teste(connecte):
    corps = connecte("admin.tech").get(PLATEFORME).json()

    assert corps["pra"]["dernierTest"] is None
    # Zero minute serait une reprise instantanee. La cible, elle, a une source.
    assert corps["pra"]["dureeRepriseMinutes"] is None
    assert corps["pra"]["cibleMinutes"] == 240
    assert corps["pra"]["feu"] == "inconnu"


def test_un_ecran_lent_est_signale_hors_engagement(connecte):
    _mesure(
        "/api/pilotage/analyses",
        appels=100,
        tranches={"sous_2000": 50, "sous_5000": 50},
    )

    corps = connecte("admin.tech").get(PLATEFORME).json()

    ligne = next(p for p in corps["performances"] if p["ecran"] == "/api/pilotage/analyses")
    assert ligne["p95Ms"] == 5000
    assert ligne["feu"] == "rouge"


def test_les_performances_portent_le_chemin_et_non_un_nom_d_ecran(connecte):
    _mesure("/api/dossiers/{id}", appels=42)

    corps = connecte("admin.tech").get(PLATEFORME).json()

    chemins = {ligne["ecran"] for ligne in corps["performances"]}
    assert "/api/dossiers/{id}" in chemins


def test_une_heure_degradee_devient_un_incident_deduit(connecte):
    _mesure("/api/dossiers", heures=3, appels=100, echecs=30)

    corps = connecte("admin.tech").get(PLATEFORME).json()

    assert len(corps["incidents"]) == 1
    incident = corps["incidents"][0]
    assert incident["gravite"] == "Majeur"
    # L'ecran doit dire que personne ne l'a declare : un incident deduit et un
    # incident constate n'ont pas la meme valeur en reunion.
    assert "déclarée par personne" in incident["impact"]


def test_une_heure_a_peine_ecornee_n_est_pas_un_incident(connecte):
    _mesure("/api/dossiers", heures=3, appels=1000, echecs=2)

    corps = connecte("admin.tech").get(PLATEFORME).json()

    assert corps["incidents"] == []


def test_les_services_portent_les_familles_du_brd(connecte):
    corps = connecte("admin.tech").get(PLATEFORME).json()

    noms = [service["nom"] for service in corps["services"]]
    assert noms == [
        "Authentification",
        "Tableaux de bord",
        "Traitement des dossiers",
        "Portail usagers",
    ]


def test_un_service_sans_trafic_reste_inconnu_et_non_vert(connecte):
    client = connecte("admin.tech")
    MesureRequete.objects.all().delete()

    corps = client.get(PLATEFORME).json()

    portail = next(s for s in corps["services"] if s["nom"] == "Portail usagers")
    assert portail["feu"] == "inconnu"


def test_la_supervision_exige_la_permission_technique(connecte):
    """Le Directeur general voit tout du port. Pas la salle des machines."""
    assert connecte("dg").get(PLATEFORME).status_code == 401
    assert connecte("dg").get(INTEGRATIONS).status_code == 401


# =====================================================================
#  L'ecran des integrations
# =====================================================================


def test_le_sso_compte_les_connexions_par_mot_de_passe(connecte):
    """
    C'est le chiffre qui dit si la bascule est achevee. La connexion du test
    lui-meme est journalisee par la route `/api/connexion` ; ici on l'inscrit
    directement, `force_login` ne passant pas par elle.
    """
    utilisateur = Utilisateur.objects.get(identifiant_annuaire="admin.tech")
    for _ in range(3):
        inscrire(
            objet_type="utilisateur",
            objet_id=utilisateur.pk,
            type_evenement="connexion",
            libelle="Connexion",
            acteur=utilisateur,
            donnees={"moyen": "mot_de_passe"},
        )

    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    assert corps["sso"]["connexionsLocales7j"] == 3
    assert corps["sso"]["connexionsSso7j"] == 0
    assert corps["sso"]["actif"] is False
    assert corps["sso"]["feu"] == "rouge"


def test_le_sso_ne_nomme_pas_un_fournisseur_qu_il_n_a_pas(connecte):
    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    assert corps["sso"]["fournisseur"] == "Aucun fournisseur déclaré"
    assert corps["sso"]["protocole"] == "Non défini"


def test_les_comptes_locaux_sont_ceux_qui_portent_un_mot_de_passe(connecte):
    """
    Le semis donne un mot de passe a tous les comptes : ils sont donc tous
    locaux, y compris ceux qui portent un identifiant d'annuaire. C'est
    exactement le cas a surveiller — deux portes, une seule politique.
    """
    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    assert corps["sso"]["comptesLocaux"] > 0
    assert corps["sso"]["comptesAnnuaire"] >= corps["sso"]["comptesLocaux"]


def test_les_integrations_non_livrees_sont_affichees_et_non_masquees(connecte):
    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    systemes = {ligne["systeme"]: ligne for ligne in corps["integrations"]}
    assert systemes["Annuaire d'entreprise"]["etat"] == "Non connecté"
    assert systemes["Annuaire d'entreprise"]["feu"] == "rouge"
    # Le portail, lui, est livre.
    assert systemes["Portail usagers"]["etat"] == "Connecté"


def test_chaque_integration_cite_l_exigence_qui_la_demande(connecte):
    """Une integration sans source est une integration que personne n'a demandee."""
    connecte("admin.tech")

    assert not Integration.objects.filter(actif=True, exigence__isnull=True).exists()


def test_une_integration_non_sondee_ne_ment_pas_sur_sa_latence(connecte):
    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    annuaire = next(
        ligne for ligne in corps["integrations"] if ligne["systeme"] == "Annuaire d'entreprise"
    )
    # `null` et non zero : rien n'interroge ce systeme (A48).
    assert annuaire["latenceMs"] is None
    assert annuaire["derniereSynchronisation"] is None


def test_les_compteurs_disent_ce_qui_reste_a_basculer(connecte):
    corps = connecte("admin.tech").get(INTEGRATIONS).json()

    libelles = [compteur["libelle"] for compteur in corps["compteurs"]]
    assert "Connexions par mot de passe applicatif" in libelles
    assert "Comptes portant un mot de passe local" in libelles

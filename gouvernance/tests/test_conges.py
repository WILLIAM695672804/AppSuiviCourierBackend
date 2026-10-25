"""
La planification des conges — §3.3, etendue a tous les agents.

Le registre de disponibilite enregistre une absence **decidee** ; ces tables-ci
arbitrent des souhaits avant qu'ils ne le deviennent. Les deux ne se confondent
pas, et le service refuse qu'une periode souhaitee chevauche une absence deja
prononcee.

Le jeu d'essai donne la dissymetrie : `dir.dsi` porte RESP — donc DISPO depuis
la migration 0024 — en portee `sous_arbre` sur la DSI ; `agent.dsi` est dans son
sous-arbre ; `focal.daf` est a la DAF, hors de portee.
"""

from datetime import date

import pytest
from django.core.management import call_command

from gouvernance.modeles import CongeDroit, CongePeriode, Disponibilite
from noyau.identite.modeles import Utilisateur

BACKEND = "noyau.identite.authentification.BackendAnnuaire"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(compte(identifiant), backend=BACKEND)
        return client

    return _connecter


def _poster(client, chemin: str, corps: dict):
    return client.post(chemin, data=corps, content_type="application/json")


def _droit(identifiant: str, annee: int = 2026, jours: int = 30) -> CongeDroit:
    return CongeDroit.objects.create(
        utilisateur=compte(identifiant), annee=annee, droits_jours=jours
    )


# ---------------------------------------------------------------------
#  Ouverture d'un droit
# ---------------------------------------------------------------------


def test_un_directeur_ouvre_un_droit_pour_un_agent_de_son_sous_arbre(connecte):
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges",
        {"agentId": compte("agent.dsi").pk, "annee": 2026, "droitsJours": 30},
    )

    assert reponse.status_code == 200
    assert CongeDroit.objects.filter(utilisateur=compte("agent.dsi"), annee=2026).exists()


def test_un_directeur_n_ouvre_pas_de_droit_hors_de_son_perimetre(connecte):
    """404 et non 403 : hors perimetre, l'agent n'existe pas — decision D5."""
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges",
        {"agentId": compte("focal.daf").pk, "annee": 2026, "droitsJours": 30},
    )

    assert reponse.status_code == 404


def test_un_collaborateur_ne_peut_pas_ouvrir_de_droit(connecte):
    """Le profil Collaborateur ne porte pas DISPO : la garde de route refuse
    avant toute regle metier."""
    reponse = _poster(
        connecte("agent.dsi"),
        "/api/gouvernance/conges",
        {"agentId": compte("agent.dsi").pk, "annee": 2026, "droitsJours": 30},
    )

    assert reponse.status_code == 401


def test_rouvrir_un_droit_le_corrige_au_lieu_de_le_doubler(connecte):
    """Un agent n'a qu'un droit par annee ; le second appel corrige le premier."""
    client = connecte("dir.dsi")
    corps = {"agentId": compte("agent.dsi").pk, "annee": 2026, "droitsJours": 30}
    _poster(client, "/api/gouvernance/conges", corps)
    _poster(client, "/api/gouvernance/conges", {**corps, "droitsJours": 25})

    droits = CongeDroit.objects.filter(utilisateur=compte("agent.dsi"), annee=2026)
    assert droits.count() == 1
    assert droits.first().droits_jours == 25


# ---------------------------------------------------------------------
#  Planification d'une periode
# ---------------------------------------------------------------------


def test_planifier_une_periode_la_pose_en_souhaite(connecte):
    droit = _droit("agent.dsi")
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-03", "au": "2026-08-14"},
    )

    assert reponse.status_code == 200
    periode = CongePeriode.objects.get(pk=reponse.json()["id"])
    assert periode.etat == CongePeriode.SOUHAITE


def test_une_periode_ne_chevauche_pas_une_absence_decidee(connecte):
    """
    L'absence est prononcee ; le souhait qui la recouvre n'a plus de sens et
    ferait paraitre disponible un agent deja parti.
    """
    droit = _droit("agent.dsi")
    Disponibilite.objects.create(
        utilisateur=compte("agent.dsi"),
        type_absence="mission",
        du=date(2026, 8, 5),
        au=date(2026, 8, 20),
        saisi_par=compte("dir.dsi"),
    )

    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-03", "au": "2026-08-14"},
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "chevauche_une_absence"


def test_deux_souhaits_qui_se_chevauchent_sont_acceptes(connecte):
    """C'est justement le conflit que l'ecran de planning sert a montrer."""
    droit = _droit("agent.dsi")
    client = connecte("dir.dsi")
    _poster(
        client,
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-03", "au": "2026-08-14"},
    )
    reponse = _poster(
        client,
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-10", "au": "2026-08-20"},
    )

    assert reponse.status_code == 200


def test_la_date_de_fin_ne_precede_pas_la_date_de_debut(connecte):
    droit = _droit("agent.dsi")
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-14", "au": "2026-08-03"},
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "periode_invalide"


def test_planifier_hors_perimetre_est_refuse(connecte):
    droit = _droit("focal.daf")
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/conges/periodes",
        {"droitId": droit.pk, "du": "2026-08-03", "au": "2026-08-14"},
    )

    assert reponse.status_code == 404


# ---------------------------------------------------------------------
#  Arbitrage
# ---------------------------------------------------------------------


def test_valider_une_periode(connecte):
    droit = _droit("agent.dsi")
    periode = CongePeriode.objects.create(
        conge_droit=droit, du=date(2026, 8, 3), au=date(2026, 8, 14)
    )

    reponse = _poster(
        connecte("dir.dsi"),
        f"/api/gouvernance/conges/periodes/{periode.pk}/arbitrage",
        {"etat": "Validé"},
    )

    assert reponse.status_code == 200
    periode.refresh_from_db()
    assert periode.etat == CongePeriode.VALIDE
    assert periode.arbitre_par == compte("dir.dsi")
    assert periode.arbitre_le is not None


def test_un_report_sans_motif_est_refuse(connecte):
    """
    Meme regle que le renvoi d'un plan d'actions : sans motif, l'agent
    resoumettra la meme periode.
    """
    droit = _droit("agent.dsi")
    periode = CongePeriode.objects.create(
        conge_droit=droit, du=date(2026, 8, 3), au=date(2026, 8, 14)
    )

    reponse = _poster(
        connecte("dir.dsi"),
        f"/api/gouvernance/conges/periodes/{periode.pk}/arbitrage",
        {"etat": "Reporté"},
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "motif_requis"


def test_l_arbitrage_est_borne_au_perimetre(connecte):
    droit = _droit("focal.daf")
    periode = CongePeriode.objects.create(
        conge_droit=droit, du=date(2026, 8, 3), au=date(2026, 8, 14)
    )

    reponse = _poster(
        connecte("dir.dsi"),
        f"/api/gouvernance/conges/periodes/{periode.pk}/arbitrage",
        {"etat": "Validé"},
    )

    assert reponse.status_code == 404


# ---------------------------------------------------------------------
#  Conflits
# ---------------------------------------------------------------------


def test_le_conflit_se_detecte_entre_deux_sous_structures_d_une_meme_tete(connecte):
    """
    Deux agents de DSI-ET et DSI-IN absents la meme semaine privent la DSI de
    sa ligne d'encadrement. A structure strictement egale, rien ne se serait
    declenche — et c'est precisement ce que l'ecran sert a voir.
    """
    from noyau.organisation.modeles import Structure

    autre = compte("focal.dsi")
    autre.structure = Structure.objects.get(code="DSI-IN", valide_au__isnull=True)
    autre.save(update_fields=["structure"])

    for identifiant in ("agent.dsi", "focal.dsi"):
        CongePeriode.objects.create(
            conge_droit=_droit(identifiant),
            du=date(2026, 8, 3),
            au=date(2026, 8, 14),
            etat=CongePeriode.VALIDE,
        )

    reponse = connecte("dsr").get("/api/gouvernance/conges?annee=2026")

    assert reponse.status_code == 200
    conflits = reponse.json()["conflits"]
    assert len(conflits) == 1
    assert conflits[0]["structure"] == "DSI"

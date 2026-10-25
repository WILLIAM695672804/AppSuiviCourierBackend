"""
Le pilier gouvernance, par ses routes et par ses services.

Ces tests ne verifient pas d'abord que les routes repondent — ils verifient
qu'elles **refusent**, et surtout qu'elles ne montrent pas ce qu'il ne faut pas.
Une fuite de perimetre ne provoque aucune erreur : elle affiche a une direction
la decision qui en contraint une autre, et personne ne s'en apercoit.

Le jeu d'essai fournit la dissymetrie qu'on exploite : `dsr` porte DEC, INST,
DISPO et REL sur toutes les structures ; `dir.dsi` n'a aucune de ces
permissions ; `focal.dsi` et `focal.daf` sont bornes a des structures
differentes — c'est la seule facon de verifier qu'aucun ne voit chez l'autre.
"""

from datetime import date, datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from gouvernance.modeles import (
    CongeDroit,
    CongePeriode,
    Disponibilite,
    Engagement,
    EngagementJalon,
    EngagementObservation,
    EngagementStructure,
    Seance,
    SeanceDocument,
)
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.journal.modeles import Evenement
from noyau.organisation.modeles import Structure

BACKEND = "noyau.identite.authentification.BackendAnnuaire"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


def structure(code: str) -> Structure:
    return Structure.objects.get(code=code, valide_au__isnull=True)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(compte(identifiant), backend=BACKEND)
        return client

    return _connecter


def _horodatage(jour: date):
    """
    `suspendu_le` et `execute_le` sont des `TIMESTAMPTZ`.

    Y poser une date nue passe — Django l'accepte — mais avec un avertissement,
    et surtout avec un decalage de fuseau que personne ne verra jusqu'au jour ou
    une comparaison tombera du mauvais cote de minuit.
    """
    return timezone.make_aware(datetime.combine(jour, time(12, 0)))


def _poster(client, chemin: str, corps: dict):
    return client.post(chemin, data=corps, content_type="application/json")


def _engagement(chargees: list[str], **surcharges) -> Engagement:
    """
    Un engagement charge des structures citees, la premiere pilote.

    Passe par les modeles et non par le service : ces tests eprouvent aussi ce
    qui se lit d'un engagement cree autrement — reprise de donnees comprise.
    """
    dsr = compte("dsr")
    defauts = {
        "origine": Engagement.INSTANCE,
        "instance": "codir",
        "date_engagement": date(2026, 6, 12),
        "objet": "Fiabiliser le reseau du terminal",
        "prise_par": compte("dg"),
        "saisie_par": dsr,
    }
    with acteur(dsr):
        engagement = Engagement.objects.create(**{**defauts, **surcharges})
        engagement.refresh_from_db()
        for rang, code in enumerate(chargees, start=1):
            EngagementStructure.objects.create(
                engagement=engagement, structure=structure(code), rang=rang
            )
    return engagement


def _seance(code_structure: str = "DSI", **surcharges) -> Seance:
    defauts = {
        "reference": "CODIR-2026-001",
        "type_seance": Seance.CODIR,
        "intitule": "CODIR de juin",
        "date_seance": date(2026, 6, 12),
        "president": compte("dg"),
        "structure": structure(code_structure),
        "echeance_depot": date(2026, 6, 26),
    }
    with acteur(compte("dsr")):
        return Seance.objects.create(**{**defauts, **surcharges})


# =====================================================================
#  Ce que la garde refuse
# =====================================================================


def test_sans_session_tout_est_refuse(client, jeu):
    assert client.get("/api/gouvernance/decisions").status_code == 401


def test_sans_dec_le_registre_des_decisions_est_refuse(connecte):
    """Une directrice de structure ne tient pas le registre des decisions."""
    assert connecte("dir.dsi").get("/api/gouvernance/decisions").status_code == 401


def test_sans_inst_le_registre_des_seances_est_refuse(connecte):
    """`DEC` n'ouvre pas `INST` : tenir les decisions n'est pas tenir les
    reunions. Le decoupage vient du §3.3, qui en fait deux charges."""
    assert connecte("dg").get("/api/gouvernance/seances").status_code == 401


def test_avec_dec_le_registre_repond(connecte):
    reponse = connecte("dsr").get("/api/gouvernance/decisions")
    assert reponse.status_code == 200
    assert reponse.json()["total"] == 0


# =====================================================================
#  Le perimetre — le point le plus sensible
# =====================================================================


def test_un_point_focal_ne_voit_pas_la_decision_du_voisin(connecte, jeu):
    """
    **Le test qui compte.** Une decision chargeant la DAF ne doit pas paraitre
    dans le registre de la DSI, et reciproquement. L'oubli d'un `restreindre()`
    ne casse rien : il montre simplement l'autre direction.
    """
    _engagement(["DAF"], objet="Revoir la chaine de la depense")
    _engagement(["DSI"], objet="Fiabiliser le reseau")

    # Le point focal n'a pas DEC ; on eprouve donc la couche de lecture
    # elle-meme, qui est ce qui borne.
    from gouvernance.lecture import registre_decisions

    vu_dsi = registre_decisions(compte("focal.dsi"))
    vu_daf = registre_decisions(compte("focal.daf"))

    assert [ligne["objet"] for ligne in vu_dsi["decisions"]] == ["Fiabiliser le reseau"]
    assert [ligne["objet"] for ligne in vu_daf["decisions"]] == ["Revoir la chaine de la depense"]


def test_une_decision_chargeant_deux_structures_n_est_comptee_qu_une_fois(connecte, jeu):
    """
    `distinct()` n'est pas decoratif : sans lui, la jointure sur les structures
    chargees duplique la ligne, et le compteur du tableau de bord affiche deux
    decisions la ou il n'y en a qu'une.
    """
    _engagement(["DSI", "DAF"])
    reponse = connecte("dsr").get("/api/gouvernance/decisions")
    assert reponse.json()["total"] == 1


def test_la_fiche_hors_perimetre_sort_en_404_et_non_403(connecte, jeu):
    """
    Decision D5. Repondre « interdit » confirmerait l'existence de la decision,
    et c'est deja une information.
    """
    engagement = _engagement(["DAF"])
    from gouvernance.lecture import fiche_decision
    from noyau.erreurs import HorsPerimetre

    with pytest.raises(HorsPerimetre):
        fiche_decision(compte("focal.dsi"), engagement.pk)


def test_une_seance_est_bornee_par_sa_structure_organisatrice(connecte, jeu):
    _seance("DAF", reference="CA-2026-001")
    _seance("DSI", reference="CODIR-2026-001")

    from gouvernance.lecture import registre_seances

    vu = registre_seances(compte("focal.dsi"))
    assert [ligne["reference"] for ligne in vu["seances"]] == ["CODIR-2026-001"]


# =====================================================================
#  Creation d'une decision
# =====================================================================


def _saisie_decision(**surcharges) -> dict:
    defauts = {
        "instance": "CODIR",
        "seance": "",
        "objet": "Generaliser les reunions de service",
        "contexte": "Quatre directions n'en tiennent pas.",
        "dateDecision": "2026-06-12",
        "echeance": "2026-07-31",
        "structures": [structure("DSI").pk, structure("DAF").pk],
    }
    return {**defauts, **surcharges}


def test_creer_une_decision_pose_la_reference_et_le_pilote(connecte, jeu):
    """
    La reference vient d'un declencheur BEFORE INSERT, sous verrou d'avis. Et la
    **premiere structure citee est pilote** : c'est elle qui rendra compte.
    """
    reponse = _poster(connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision())
    assert reponse.status_code == 200

    engagement = Engagement.objects.get(pk=reponse.json()["id"])
    assert engagement.reference == "DEC-2026-0001"

    chargees = list(engagement.structures.order_by("rang").select_related("structure"))
    assert [c.structure.code for c in chargees] == ["DSI", "DAF"]
    assert [c.pilote for c in chargees] == [True, False]


def test_une_decision_sans_structure_est_refusee(connecte, jeu):
    """
    Un engagement que nul ne porte n'est visible de personne — la lecture passe
    par les structures chargees — et surtout personne ne repond quand l'instance
    demande ou cela en est.
    """
    reponse = _poster(
        connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision(structures=[])
    )
    assert reponse.status_code == 409
    assert "au moins une structure" in reponse.json()["message"]


def test_une_echeance_anterieure_a_la_decision_est_refusee(connecte, jeu):
    reponse = _poster(
        connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision(echeance="2026-01-01")
    )
    assert reponse.status_code == 409


def test_une_instance_inconnue_est_refusee(connecte, jeu):
    """Le referentiel est ferme par une contrainte CHECK ; sans cette garde, le
    refus sortirait en 500 avec un message que personne ne lit."""
    reponse = _poster(
        connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision(instance="Comite technique")
    )
    assert reponse.status_code == 409
    assert "inconnu" in reponse.json()["message"]


def test_creer_une_decision_inscrit_un_evenement(connecte, jeu):
    reponse = _poster(connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision())
    assert Evenement.objects.filter(
        objet_type="engagement",
        objet_id=reponse.json()["id"],
        type_evenement="engagement_consigne",
    ).exists()


def test_une_decision_issue_d_une_seance_s_y_rattache(connecte, jeu):
    """
    Le rattachement se fait sur la **reference exacte**. Une decision sans seance
    reste le cas ordinaire : le §17 traite l'instruction verbale du DG comme une
    source de plein droit, pas comme une anomalie a corriger.
    """
    seance = _seance("DSI", reference="CODIR-2026-001")
    reponse = _poster(
        connecte("dsr"), "/api/gouvernance/decisions", _saisie_decision(seance="CODIR-2026-001")
    )
    assert Engagement.objects.get(pk=reponse.json()["id"]).seance_id == seance.pk


# =====================================================================
#  Avancement
# =====================================================================


def test_l_avancement_de_la_decision_est_la_moyenne_des_structures(connecte, jeu):
    """
    Le declencheur recalcule ; le service n'ecrit **que** la ligne de la
    structure. Le recalculer en Python ferait deux verites, dont l'une serait
    fausse le lendemain.
    """
    engagement = _engagement(["DSR", "DSI"])
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/avancement",
        {"avancement": 80, "observation": "Cablage termine.", "jalonsFaits": []},
    )
    assert reponse.status_code == 200

    engagement.refresh_from_db()
    # 80 pour la structure servie, 0 pour l'autre : moyenne a parts egales (A17).
    assert float(engagement.avancement) == 40.0


def test_declarer_pour_une_structure_non_chargee_est_refuse(connecte, jeu):
    """
    **403 et non 404**, et la nuance est reelle.

    La DSR voit tout : la decision existe pour elle, et le nier serait absurde.
    Mais sa structure n'est pas chargee, et laisser une direction declarer
    l'avancement d'une autre ferait de la moyenne un chiffre sans auteur — la
    structure ainsi creditee ne le saurait jamais.

    Quand la decision est **invisible**, en revanche, c'est bien 404 qui sort :
    c'est ce que verifie `test_la_fiche_hors_perimetre_sort_en_404_et_non_403`.
    """
    engagement = _engagement(["DSI"])
    from gouvernance import services
    from noyau.erreurs import ErreurMetier

    with pytest.raises(ErreurMetier) as leve:
        services.consigner_avancement(
            compte("dsr"),
            engagement.pk,
            type("S", (), {"avancement": 50, "observation": "", "jalonsFaits": []})(),
        )
    assert leve.value.statut == 403


def test_une_direction_declare_pour_ses_divisions(connecte, jeu):
    """
    Le rattachement inclut les descendantes : une directrice repond de ses
    divisions. L'exclure obligerait chaque chef de division a se connecter pour
    un chiffre que sa direction consolide deja.
    """
    engagement = _engagement(["DSI-ET"])
    from gouvernance import services

    services.consigner_avancement(
        compte("dir.dsi"),
        engagement.pk,
        type("S", (), {"avancement": 60, "observation": "", "jalonsFaits": []})(),
    )
    engagement.refresh_from_db()
    assert float(engagement.avancement) == 60.0


def test_une_decision_suspendue_n_avance_pas(connecte, jeu):
    """§19. Consigner un avancement sur ce qu'une autorite a arrete reviendrait
    a passer outre la suspension sans jamais la lever."""
    engagement = _engagement(
        ["DSI"],
        suspendu_le=_horodatage(date(2026, 6, 20)),
        motif_suspension="Etude d'impact attendue",
    )
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/avancement",
        {"avancement": 50, "observation": "", "jalonsFaits": []},
    )
    assert reponse.status_code == 409
    assert "suspendue" in reponse.json()["message"]


def test_un_jalon_coche_porte_sa_date(connecte, jeu):
    engagement = _engagement(["DSR"])
    jalon = EngagementJalon.objects.create(
        engagement=engagement, libelle="Cartographie", echeance=date(2026, 7, 15)
    )
    _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/avancement",
        {"avancement": 30, "observation": "", "jalonsFaits": [jalon.pk]},
    )
    jalon.refresh_from_db()
    assert jalon.fait_le == date.today()


def test_un_avancement_hors_bornes_est_refuse(connecte, jeu):
    engagement = _engagement(["DSI"])
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/avancement",
        {"avancement": 140, "observation": "", "jalonsFaits": []},
    )
    assert reponse.status_code == 409


# =====================================================================
#  Relances
# =====================================================================


def test_la_relance_se_compte_et_vise_le_pilote(connecte, jeu):
    engagement = _engagement(["DSI", "DAF"])
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/relance",
        {"motif": "Deuxieme rappel.", "structureId": None},
    )
    assert reponse.status_code == 200

    from gouvernance.modeles import VueEngagementEtat

    assert VueEngagementEtat.objects.get(pk=engagement.pk).relances == 1
    evenement = Evenement.objects.get(objet_type="engagement", type_evenement="relance_emise")
    assert "DSI" in evenement.libelle


def test_la_relance_d_engagement_notifie_le_directeur_de_la_tete(connecte, jeu):
    """
    Une decision chargeant DSI-ET se relance chez la directrice de la DSI :
    c'est elle qui repond de la branche devant le CODIR. Le chef du
    departement, lui, ne debloque rien qu'il ne pouvait deja faire.
    """
    from noyau.notifications.modeles import Notification

    engagement = _engagement(["DSI-ET"])
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/relance",
        {"motif": "Le jalon de juin n'est pas tenu.", "structureId": None},
    )

    assert reponse.status_code == 200
    assert Notification.objects.filter(
        destinataire=compte("dir.dsi"),
        objet_type="engagement",
        objet_id=engagement.pk,
    ).exists()


def test_une_decision_executee_ne_se_relance_pas(connecte, jeu):
    """La relance perdrait tout sens, et le compteur ferait paraitre defaillante
    une structure qui a livre."""
    engagement = _engagement(["DSI"], execute_le=_horodatage(date(2026, 7, 1)))
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/relance",
        {"motif": "Rappel.", "structureId": None},
    )
    assert reponse.status_code == 409


def test_relancer_une_structure_non_chargee_est_refuse(connecte, jeu):
    engagement = _engagement(["DSI"])
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{engagement.pk}/relance",
        {"motif": "Rappel.", "structureId": structure("DAF").pk},
    )
    assert reponse.status_code == 409


def test_sans_rel_on_ne_relance_pas(connecte, jeu):
    """`REL` et non `DEC` : personne ne se relance soi-meme. Le DG porte DEC
    mais pas REL — c'est la DSR qui relance."""
    engagement = _engagement(["DSI"])
    reponse = _poster(
        connecte("dg"),
        f"/api/gouvernance/decisions/{engagement.pk}/relance",
        {"motif": "Rappel.", "structureId": None},
    )
    assert reponse.status_code == 401


# =====================================================================
#  Seances et depots
# =====================================================================


def test_creer_une_seance_compose_sa_reference(connecte, jeu):
    corps = {
        "type": "CODIR",
        "intitule": "CODIR de septembre",
        "date": "2026-09-10",
        "presidentId": compte("dg").pk,
        "structure": "DSI",
        "echeanceDepot": "2026-09-24",
        "ordreDuJour": [{"point": "Point d'etape", "rapporteurId": None}],
    }
    reponse = _poster(connecte("dsr"), "/api/gouvernance/seances", corps)
    assert reponse.status_code == 200

    seance = Seance.objects.get(pk=reponse.json()["id"])
    assert seance.reference == "CODIR-2026-001"
    assert seance.points.count() == 1


def test_une_echeance_de_depot_anterieure_a_la_seance_est_refusee(connecte, jeu):
    corps = {
        "type": "CODIR",
        "intitule": "CODIR",
        "date": "2026-09-10",
        "presidentId": None,
        "structure": "DSI",
        "echeanceDepot": "2026-09-01",
        "ordreDuJour": [],
    }
    assert _poster(connecte("dsr"), "/api/gouvernance/seances", corps).status_code == 409


def test_un_depot_hors_delai_reste_hors_delai(connecte, jeu):
    """
    L'etat du depot ne se stocke pas : `echeance_depot` et la date constatee
    suffisent. Et un compte rendu rendu en retard **reste** hors delai une fois
    depose — c'est la ponctualite qui se mesure, pas la presence du document.
    """
    seance = _seance("DSI", echeance_depot=date.today() - timedelta(days=10))
    reponse = _poster(
        connecte("dsr"),
        f"/api/gouvernance/seances/{seance.pk}/documents",
        {
            "nature": "Compte rendu",
            "libelle": "CR du CODIR",
            "nomFichier": "cr.pdf",
            "poids": "1.2 Mo",
        },
    )
    assert reponse.status_code == 200

    fiche = connecte("dsr").get(f"/api/gouvernance/seances/{seance.pk}").json()
    assert fiche["depot"] == "Hors délai"
    assert fiche["dateDepot"] == date.today().isoformat()


def test_un_compte_rendu_ne_se_depose_pas_deux_fois(connecte, jeu):
    """Redeposer effacerait la date qui prouve la ponctualite."""
    seance = _seance("DSI")
    corps = {
        "nature": "Compte rendu",
        "libelle": "CR",
        "nomFichier": "cr.pdf",
        "poids": "100 Ko",
    }
    assert (
        _poster(
            connecte("dsr"), f"/api/gouvernance/seances/{seance.pk}/documents", corps
        ).status_code
        == 200
    )
    reponse = _poster(connecte("dsr"), f"/api/gouvernance/seances/{seance.pk}/documents", corps)
    assert reponse.status_code == 409


def test_un_proces_verbal_vaut_compte_rendu(connecte, jeu):
    """
    Une session du CA rend un PV, pas un compte rendu. Les distinguer ici ferait
    paraitre en souffrance toutes les sessions du conseil.
    """
    seance = _seance("DSI", echeance_depot=date.today() + timedelta(days=5))
    with acteur(compte("dsr")):
        SeanceDocument.objects.create(
            seance=seance,
            nature="proces_verbal",
            libelle="PV",
            depose_le=date.today(),
            depose_par=compte("dsr"),
        )
    fiche = connecte("dsr").get(f"/api/gouvernance/seances/{seance.pk}").json()
    assert fiche["depot"] == "Déposé"


# =====================================================================
#  Disponibilite
# =====================================================================


def _absence(**surcharges) -> dict:
    defauts = {
        "responsableId": compte("dir.dsi").pk,
        "type": "Mission",
        "du": date.today().isoformat(),
        "au": (date.today() + timedelta(days=5)).isoformat(),
        "interimaireId": None,
    }
    return {**defauts, **surcharges}


def test_une_absence_sans_interimaire_est_acceptee_et_rouge(connecte, jeu):
    """
    C'est le cas que la DSR doit voir. Le refuser obligerait a inventer un
    interimaire pour pouvoir saisir, et le registre ne signalerait plus rien.
    """
    assert (
        _poster(connecte("dsr"), "/api/gouvernance/disponibilites", _absence()).status_code == 200
    )
    registre = connecte("dsr").get("/api/gouvernance/disponibilites").json()
    assert registre["sansInterim"] == 1
    assert registre["disponibilites"][0]["feu"] == "rouge"


def test_deux_absences_du_meme_agent_ne_se_chevauchent_pas(connecte, jeu):
    """
    Le moteur le refuse (exclusion GiST) et c'est lui qui fait foi ; le service
    ne fait que rendre le refus lisible avant que PostgreSQL ne le crie.
    """
    _poster(connecte("dsr"), "/api/gouvernance/disponibilites", _absence())
    reponse = _poster(
        connecte("dsr"),
        "/api/gouvernance/disponibilites",
        _absence(du=(date.today() + timedelta(days=2)).isoformat()),
    )
    assert reponse.status_code == 409
    assert "deja declare absent" in reponse.json()["message"]


def test_on_ne_se_remplace_pas_soi_meme(connecte, jeu):
    reponse = _poster(
        connecte("dsr"),
        "/api/gouvernance/disponibilites",
        _absence(interimaireId=compte("dir.dsi").pk),
    )
    assert reponse.status_code == 409


def test_le_nombre_de_jours_compte_les_bornes(connecte, jeu):
    """Du lundi au vendredi fait cinq jours, pas quatre."""
    _poster(
        connecte("dsr"),
        "/api/gouvernance/disponibilites",
        _absence(du="2026-09-07", au="2026-09-11"),
    )
    ligne = connecte("dsr").get("/api/gouvernance/disponibilites").json()["disponibilites"][0]
    assert ligne["jours"] == 5


def test_le_registre_des_absences_filtre_par_libelle_affiche(connecte, jeu):
    """
    Le front envoie ce qu'il affiche — « Mission », « Sans interim » — et non
    des codes. Un filtre qui ne reconnait pas sa valeur ne filtre rien, et
    l'ecran parait fonctionner alors qu'il montre tout : c'est le piege
    « un filtre de la demo n'est pas un filtre du backend ».
    """
    _poster(connecte("dsr"), "/api/gouvernance/disponibilites", _absence())

    def lignes(**parametres) -> list[dict]:
        reponse = connecte("dsr").get("/api/gouvernance/disponibilites", parametres)
        return reponse.json()["disponibilites"]

    assert len(lignes()) == 1
    assert len(lignes(filtre="Toutes")) == 1
    assert len(lignes(filtre="Mission")) == 1
    assert len(lignes(filtre="En cours")) == 1
    assert len(lignes(filtre="Sans intérim")) == 1
    assert lignes(filtre="Congé annuel") == []
    # Un libelle inconnu ne renvoie rien plutot que tout.
    assert lignes(filtre="en_cours") == []


def test_sans_dispo_le_registre_des_absences_est_refuse(connecte):
    """Un collaborateur ne lit pas les absences de la direction."""
    assert connecte("agent.dsi").get("/api/gouvernance/disponibilites").status_code == 401


def test_le_dg_voit_nominativement_un_agent_de_sous_structure(connecte):
    """
    Le profil DG porte `DISPO` depuis la migration 0024, et sa portee est
    `toutes` : la disponibilite du Port lui est ouverte, nominativement — et
    a l'etage de la direction, pas du service.
    """
    Disponibilite.objects.create(
        utilisateur=compte("agent.dsi"),
        type_absence="mission",
        du=date(2026, 9, 1),
        au=date(2026, 9, 10),
        saisi_par=compte("dsr"),
    )

    reponse = connecte("dg").get("/api/gouvernance/disponibilites")

    assert reponse.status_code == 200
    lignes = reponse.json()["disponibilites"]
    assert any(ligne["responsable"] == compte("agent.dsi").nom_complet for ligne in lignes)
    assert all(ligne["structure"] != "DSI-ET" for ligne in lignes)


def test_le_registre_se_filtre_par_tete(connecte):
    Disponibilite.objects.create(
        utilisateur=compte("agent.dsi"),
        type_absence="mission",
        du=date(2026, 9, 1),
        au=date(2026, 9, 10),
        saisi_par=compte("dsr"),
    )

    reponse = connecte("dg").get("/api/gouvernance/disponibilites?structure=DAF")

    assert reponse.status_code == 200
    assert reponse.json()["disponibilites"] == []


def test_un_directeur_garde_le_detail_de_ses_services_au_registre(connecte):
    """
    La contrepartie : sous la tete, le directeur voit ses services nommes.
    C'est ce que la consolidation lui laisse.
    """
    Disponibilite.objects.create(
        utilisateur=compte("agent.dsi"),
        type_absence="mission",
        du=date(2026, 9, 1),
        au=date(2026, 9, 10),
        saisi_par=compte("dsr"),
    )

    lignes = connecte("dir.dsi").get("/api/gouvernance/disponibilites").json()["disponibilites"]

    assert any(ligne["structure"] == "DSI-ET" for ligne in lignes)


def test_un_directeur_ne_declare_pas_une_absence_hors_de_son_perimetre(connecte):
    """
    La directrice de la DSI porte `DISPO` depuis la migration 0024. Son
    perimetre est `sous_arbre` sur la DSI : la DAF ne la regarde pas.

    404 et non 403 — decision D5 : un objet hors perimetre n'existe pas.
    """
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/disponibilites",
        {
            "responsableId": compte("focal.daf").pk,
            "type": "Mission",
            "du": "2026-09-01",
            "au": "2026-09-05",
            "interimaireId": None,
        },
    )
    assert reponse.status_code == 404


def test_un_directeur_declare_une_absence_dans_son_sous_arbre(connecte):
    reponse = _poster(
        connecte("dir.dsi"),
        "/api/gouvernance/disponibilites",
        {
            "responsableId": compte("agent.dsi").pk,
            "type": "Mission",
            "du": "2026-09-01",
            "au": "2026-09-05",
            "interimaireId": None,
        },
    )
    assert reponse.status_code == 200


def test_un_directeur_lit_les_absences(connecte):
    """
    `DISPO` est accordee au profil `RESP` : un chef de structure planifie les
    conges de ses agents, il lui faut donc voir leur disponibilite comme la
    voit la DSR. Migration 0024.
    """
    assert connecte("dir.dsi").get("/api/gouvernance/disponibilites").status_code == 200


# =====================================================================
#  Conges
# =====================================================================


def test_un_conflit_de_conges_se_voit_avant_l_arbitrage(connecte, jeu):
    """
    Deux responsables d'une meme structure absents en meme temps privent la
    direction de sa ligne hierarchique. Les souhaits sont inclus : c'est
    **avant** l'arbitrage que le conflit doit se voir, sinon l'ecran ne sert
    qu'a constater.
    """
    with acteur(compte("dsr")):
        for identifiant in ("dir.dsi", "focal.dsi"):
            droit = CongeDroit.objects.create(utilisateur=compte(identifiant), annee=2026)
            CongePeriode.objects.create(
                conge_droit=droit, du=date(2026, 8, 3), au=date(2026, 8, 21)
            )

    planning = connecte("dsr").get("/api/gouvernance/conges?annee=2026").json()
    assert len(planning["conflits"]) == 1
    assert planning["conflits"][0]["structure"] == "DSI"


def test_un_souhait_n_entame_pas_le_solde(connecte, jeu):
    """
    Le decompter ferait paraitre epuise un solde que rien n'a encore engage.
    Seules les periodes arbitrees ou validees comptent.
    """
    with acteur(compte("dsr")):
        droit = CongeDroit.objects.create(
            utilisateur=compte("dir.dsi"), annee=2026, droits_jours=30
        )
        CongePeriode.objects.create(
            conge_droit=droit, du=date(2026, 8, 3), au=date(2026, 8, 12), etat=CongePeriode.SOUHAITE
        )
        CongePeriode.objects.create(
            conge_droit=droit, du=date(2026, 9, 1), au=date(2026, 9, 5), etat=CongePeriode.VALIDE
        )

    ligne = connecte("dsr").get("/api/gouvernance/conges?annee=2026").json()["lignes"][0]
    assert ligne["planifies"] == 5
    assert ligne["solde"] == 25


# =====================================================================
#  Tableau de bord
# =====================================================================


def test_le_tableau_de_bord_range_les_moins_avancees_d_abord(connecte, jeu):
    """
    Une decision a 10 % relancee trois fois est le vrai signal, pas celle a
    95 %. L'ordre de cette liste est ce que la DSR lit en premier le matin.
    """
    hier = date.today() - timedelta(days=30)
    presque = _engagement(["DSI"], echeance=hier, objet="Presque finie")
    demarre = _engagement(["DAF"], echeance=hier, objet="A peine commencee")
    with acteur(compte("dsr")):
        presque.structures.update(avancement=90)
        demarre.structures.update(avancement=10)
        # `update()` ne declenche pas le recalcul : on le force en touchant la
        # ligne comme le ferait le service.
        for charge in list(presque.structures.all()) + list(demarre.structures.all()):
            charge.save()

    bord = connecte("dsr").get("/api/gouvernance/tableau-de-bord").json()
    assert [ligne["objet"] for ligne in bord["aRelancer"]] == [
        "A peine commencee",
        "Presque finie",
    ]


def test_une_decision_relancee_figure_a_relancer_sans_etre_en_retard(connecte, jeu):
    """
    La carte annonce « aucune décision en retard **ni relancée** » : une decision
    deja relancee mais encore dans les temps appelle une action. Le compteur
    « En retard », lui, ne compte que les retards — sinon il dirait faux.
    """
    dans_les_temps = _engagement(
        ["DSI"], echeance=date.today() + timedelta(days=30), objet="Relancee dans les temps"
    )
    retard = _engagement(
        ["DAF"], echeance=date.today() - timedelta(days=30), objet="Echeance depassee"
    )
    _poster(
        connecte("dsr"),
        f"/api/gouvernance/decisions/{dans_les_temps.pk}/relance",
        {"motif": "Premier rappel.", "structureId": None},
    )

    bord = connecte("dsr").get("/api/gouvernance/tableau-de-bord").json()
    # Les retards d'abord, la relancee ensuite.
    assert [ligne["objet"] for ligne in bord["aRelancer"]] == [
        "Echeance depassee",
        "Relancee dans les temps",
    ]
    assert retard.pk == bord["aRelancer"][0]["id"]
    compteur = next(c for c in bord["compteurs"] if c["libelle"] == "En retard")
    assert compteur["valeur"] == 1


def test_les_quatre_instances_sont_toujours_renvoyees(connecte, jeu):
    """
    Meme a zero. Une barre dont les segments apparaissent et disparaissent selon
    les donnees se relit mal d'un jour sur l'autre.
    """
    bord = connecte("dsr").get("/api/gouvernance/tableau-de-bord").json()
    assert [ligne["instance"] for ligne in bord["parInstance"]] == [
        "Conseil d'administration",
        "CODIR",
        "Directeur général",
        "Assemblée générale",
    ]


def test_une_decision_suspendue_sort_en_feu_inconnu(connecte, jeu):
    """
    Ni vert — cela dirait qu'elle va bien — ni rouge — cela dirait qu'on est en
    faute. Elle est a l'arret sur decision.
    """
    _engagement(
        ["DSI"], suspendu_le=_horodatage(date(2026, 6, 20)), motif_suspension="Etude attendue"
    )
    ligne = connecte("dsr").get("/api/gouvernance/decisions").json()["decisions"][0]
    assert ligne["etat"] == "Suspendue"
    assert ligne["feu"] == "inconnu"


# =====================================================================
#  Traitements automatiques
# =====================================================================


def test_la_relance_automatique_n_a_pas_d_auteur(connecte, jeu):
    """
    Personne ne l'a signee, et lui attribuer un agent serait faux. Meme regle que
    `relance.emetteur_id` nul pour les courriers.
    """
    from gouvernance.taches import relancer_les_engagements

    _engagement(["DSI"], echeance=date.today() - timedelta(days=30))
    assert relancer_les_engagements() == 1

    observation = EngagementObservation.objects.get(relance=True)
    assert observation.auteur_id is None
    assert "Relance automatique" in observation.texte


def test_la_relance_automatique_ne_part_pas_deux_fois_de_suite(connecte, jeu):
    """
    Sans intervalle, la tache relancerait chaque nuit la meme decision : la
    structure cesserait de lire, et l'escalade ne servirait plus a rien.
    """
    from gouvernance.taches import relancer_les_engagements

    _engagement(["DSI"], echeance=date.today() - timedelta(days=30))
    assert relancer_les_engagements() == 1
    assert relancer_les_engagements() == 0


def test_une_decision_suspendue_n_est_pas_relancee(connecte, jeu):
    """Relancer une structure a qui une autorite a interdit d'avancer serait
    faux — arbitrage n° 2."""
    from gouvernance.taches import relancer_les_engagements

    _engagement(
        ["DSI"],
        echeance=date.today() - timedelta(days=30),
        suspendu_le=_horodatage(date(2026, 6, 20)),
        motif_suspension="Etude attendue",
    )
    assert relancer_les_engagements() == 0


def test_les_agregats_se_rejouent_sans_doubler(connecte, jeu):
    """
    Condition pour qu'on puisse les rejouer apres un incident sans se demander
    ce qu'ils ont deja fait.
    """
    from gouvernance.modeles import AgregatGouvernanceJour
    from gouvernance.taches import recalculer_agregats

    _engagement(["DSI"])
    assert recalculer_agregats() == 1
    assert recalculer_agregats() == 1
    assert AgregatGouvernanceJour.objects.count() == 1


def test_un_depot_en_souffrance_n_est_signale_qu_une_fois(connecte, jeu):
    """
    Un evenement par seance et par jour ferait de la fiche de vie un journal de
    la tache plutot que de la seance.
    """
    from gouvernance.taches import signaler_les_depots

    _seance("DSI", echeance_depot=date.today() - timedelta(days=15))
    assert signaler_les_depots() == 1
    assert signaler_les_depots() == 0
    assert (
        Evenement.objects.filter(objet_type="seance", type_evenement="depot_en_souffrance").count()
        == 1
    )


def test_une_absence_en_cours_sans_interim_est_agregee(connecte, jeu):
    from gouvernance.modeles import AgregatGouvernanceJour
    from gouvernance.taches import recalculer_agregats

    _engagement(["DSI"])
    with acteur(compte("dsr")):
        Disponibilite.objects.create(
            utilisateur=compte("dir.dsi"),
            type_absence="mission",
            du=date.today() - timedelta(days=1),
            au=date.today() + timedelta(days=3),
            saisi_par=compte("dsr"),
        )
    recalculer_agregats()
    assert AgregatGouvernanceJour.objects.first().absences_sans_interim == 1

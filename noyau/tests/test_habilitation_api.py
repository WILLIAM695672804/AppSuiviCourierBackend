"""
Le pilier habilitation, par ses routes.

Ces tests ne verifient pas que les routes repondent — ils verifient qu'elles
**refusent**. Une couche d'habilitation qui laisse passer ne provoque aucune
erreur : elle donne des droits a quelqu'un, et personne ne le voit.

Le jeu d'essai fournit les comptes : `admin` porte ADM_HAB, `focal.dsi` ne le
porte pas, `dg` porte COT et VAL. C'est cette dissymetrie qu'on exploite.
"""

import pytest
from django.core.management import call_command

from noyau.habilitation.modeles import (
    Delegation,
    Permission,
    Profil,
    ProfilPermission,
    UtilisateurProfil,
)
from noyau.habilitation.resolution import comptes_du_portail, permissions_de
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.journal.modeles import Evenement
from noyau.organisation.modeles import Poste, Structure
from noyau.perimetre.modeles import Perimetre

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


# =====================================================================
#  Ce que la garde refuse
# =====================================================================


def test_sans_session_tout_est_refuse(client, jeu):
    assert client.get("/api/habilitations/profils").status_code == 401


def test_sans_adm_hab_le_registre_est_refuse(connecte):
    """Un point focal n'administre pas les habilitations."""
    assert connecte("focal.dsi").get("/api/habilitations/utilisateurs").status_code == 401


def test_avec_adm_hab_le_registre_repond(connecte):
    reponse = connecte("admin").get("/api/habilitations/utilisateurs")
    assert reponse.status_code == 200
    assert len(reponse.json()) == Utilisateur.objects.count()


def test_la_session_expiree_sort_en_401_et_non_403(client, jeu):
    """Le garde du front redirige sur 401. Un 403 le ferait echouer sans le dire."""
    assert client.get("/api/moi").status_code == 401


# =====================================================================
#  Profils
# =====================================================================


PROFILS = "/api/habilitations/profils"


def test_un_profil_se_cree(connecte):
    """G-02 : « d'autres profils peuvent etre crees librement » (inventaire des
    ecrans v3, zone G)."""
    reponse = connecte("admin").post(
        PROFILS,
        {"code": "coordonnateur", "libelle": "Coordonnateur de projet"},
        content_type="application/json",
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    # Le code est normalise en majuscules : c'est une clef, pas une phrase.
    assert corps["code"] == "COORDONNATEUR"
    assert corps["verrouille"] is False
    assert corps["permissions"] == []
    assert corps["nombreAgents"] == 0


def test_un_profil_derive_herite_des_permissions_de_son_modele(connecte):
    """
    C'est exactement ce que le refus de `basculer_permission` recommande depuis
    le premier jour — « creez un profil derive » — et qui n'existait pas.
    """
    modele = Profil.objects.get(code="POINT_FOCAL")
    attendues = sorted(p.code for p in modele.permissions.all())
    assert attendues, "Le profil modele doit porter des permissions."

    reponse = connecte("admin").post(
        PROFILS,
        {
            "code": "FOCAL_ETENDU",
            "libelle": "Point focal etendu",
            "depuisProfilId": modele.pk,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert reponse.json()["permissions"] == attendues


def test_le_derive_ne_suit_pas_les_evolutions_de_son_modele(connecte):
    """
    La copie est faite **une fois**. Un heritage vivant aurait fait bouger les
    droits d'un profil sans que personne ne touche a ce profil.
    """
    modele = Profil.objects.create(code="SOURCE", libelle="Source", systeme=False)
    modele.permissions.add(Permission.objects.get(code="ACT_LEC"))

    derive_id = (
        connecte("admin")
        .post(
            PROFILS,
            {"code": "DERIVE", "libelle": "Derive", "depuisProfilId": modele.pk},
            content_type="application/json",
        )
        .json()["id"]
    )

    connecte("admin").patch(
        f"{PROFILS}/{modele.pk}/permissions",
        {"permission": "STAT", "accordee": True},
        content_type="application/json",
    )

    profils = {p["id"]: p for p in connecte("admin").get(PROFILS).json()}
    assert profils[derive_id]["permissions"] == ["ACT_LEC"]
    assert "STAT" in profils[modele.pk]["permissions"]


def test_un_profil_cree_n_est_jamais_systeme(connecte):
    """
    Le drapeau n'est pas un parametre de la route, et ce n'est pas un oubli : il
    designe le referentiel livre. Un profil cree a l'ecran n'en fait pas partie,
    quoi que le corps de la requete raconte.
    """
    reponse = connecte("admin").post(
        PROFILS,
        {"code": "FAUX_SYSTEME", "libelle": "Faux systeme", "systeme": True},
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert reponse.json()["verrouille"] is False
    assert Profil.objects.get(code="FAUX_SYSTEME").systeme is False


def test_un_code_de_profil_deja_pris_est_refuse(connecte):
    reponse = connecte("admin").post(
        PROFILS,
        {"code": "POINT_FOCAL", "libelle": "Doublon"},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "code_profil_pris"


def test_le_code_d_un_profil_ne_se_modifie_pas(connecte):
    """Il est la clef par laquelle le semis, les tests et les migrations
    designent un profil."""
    profil = Profil.objects.create(code="STABLE", libelle="Stable", systeme=False)

    reponse = connecte("admin").patch(
        f"{PROFILS}/{profil.pk}",
        {"code": "AUTRE", "libelle": "Renomme"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    assert reponse.json()["libelle"] == "Renomme"
    profil.refresh_from_db()
    assert profil.code == "STABLE"


def test_un_profil_systeme_se_renomme(connecte):
    """
    Le **code** reste hors du formulaire — le semis et les migrations le citent.
    Le libelle, lui, est l'affaire de l'institution : « Point focal » se dit
    peut-etre autrement au Port. ADR 041.
    """
    profil = Profil.objects.get(code="POINT_FOCAL")
    reponse = connecte("admin").patch(
        f"{PROFILS}/{profil.pk}",
        {"libelle": "Autre chose"},
        content_type="application/json",
    )
    assert reponse.status_code == 200, reponse.content
    profil.refresh_from_db()
    assert (profil.libelle, profil.code) == ("Autre chose", "POINT_FOCAL")


def test_un_profil_systeme_ne_sort_pas_du_catalogue(connecte):
    """
    Le seul verrou qui demeure sur le referentiel livre. Modifier ses droits se
    reprend d'un clic ; le retirer casserait le semis et les migrations, qui le
    citent par son code, et rien n'echouerait avant le deploiement suivant.
    """
    profil = Profil.objects.create(code="LIVRE", libelle="Livre", systeme=True)

    reponse = connecte("admin").post(
        f"{PROFILS}/{profil.pk}/invalidation",
        {"motif": "Essai."},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "profil_systeme"


def test_un_profil_porte_ne_se_retire_pas_du_catalogue(connecte):
    """
    L'invalider oterait tous leurs droits aux porteurs d'un coup, sans qu'aucun
    ne soit prevenu : ils se connecteraient a une application vide et
    chercheraient la panne ailleurs.
    """
    profil = Profil.objects.get(code="POINT_FOCAL")
    profil.systeme = False
    profil.save(update_fields=["systeme"])

    reponse = connecte("admin").post(
        f"{PROFILS}/{profil.pk}/invalidation",
        {"motif": "Profil obsolete."},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "profil_porte"


def test_un_profil_sans_porteur_sort_du_catalogue_sans_etre_efface(connecte):
    profil = Profil.objects.create(code="ABANDONNE", libelle="Abandonne", systeme=False)

    reponse = connecte("admin").post(
        f"{PROFILS}/{profil.pk}/invalidation",
        {"motif": "Cree par erreur."},
        content_type="application/json",
    )

    assert reponse.status_code == 204
    assert profil.pk not in {p["id"] for p in connecte("admin").get(PROFILS).json()}
    # La ligne reste : sans elle, on ne pourrait plus dire quels droits un agent
    # detenait a une date passee.
    assert Profil.objects.filter(pk=profil.pk).exists()


def test_les_profils_ne_s_administrent_pas_sans_ADM_HAB(connecte):
    assert (
        connecte("agent.dsi")
        .post(PROFILS, {"code": "PIRATE", "libelle": "Pirate"}, content_type="application/json")
        .status_code
        == 401
    )


def test_un_profil_systeme_se_modifie(connecte):
    """
    Le referentiel livre decrit l'organisation telle qu'on l'a comprise ; celui
    qui administre le Port la connait mieux. Le verrou n'ajoutait que des gestes :
    l'administrateur pouvait deja deriver le profil, l'attribuer et retirer
    l'ancien. ADR 041.
    """
    profil = Profil.objects.get(code="POINT_FOCAL")
    reponse = connecte("admin").patch(
        f"/api/habilitations/profils/{profil.pk}/permissions",
        data={"permission": "ARCH", "accordee": True},
        content_type="application/json",
    )
    assert reponse.status_code == 204, reponse.content
    assert profil.permissions.filter(code="ARCH").exists()


def test_on_ne_retire_pas_la_derniere_clef_de_l_administration(connecte):
    """
    La seule serrure qui reste sur les permissions, et elle n'est pas une
    opinion : ce geste ferme l'administration a tout le monde, y compris a celui
    qui vient de le faire, et aucun ecran ne permet d'y revenir.

    L'etat de depart est pose **en base** et non par l'API : retirer le droit aux
    autres profils un a un aurait pu commencer par celui de l'appelant, qui
    aurait alors perdu la route avant d'arriver au dernier.
    """
    dernier = Profil.objects.filter(
        utilisateurprofil__utilisateur__identifiant_annuaire="admin",
        permissions__code="ADM_HAB",
        invalide_le__isnull=True,
    ).first()
    assert dernier is not None, "Le compte d'administration doit porter le droit."

    ProfilPermission.objects.filter(permission__code="ADM_HAB").exclude(profil=dernier).delete()

    reponse = connecte("admin").patch(
        f"/api/habilitations/profils/{dernier.pk}/permissions",
        data={"permission": "ADM_HAB", "accordee": False},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "derniere_clef_administration"
    assert dernier.permissions.filter(code="ADM_HAB").exists()


def test_accorder_une_permission_inscrit_un_evenement(connecte):
    profil = Profil.objects.create(code="ESSAI", libelle="Profil d'essai", systeme=False)
    reponse = connecte("admin").patch(
        f"/api/habilitations/profils/{profil.pk}/permissions",
        data={"permission": "ACT_SAI", "accordee": True},
        content_type="application/json",
    )
    assert reponse.status_code == 204
    assert profil.permissions.filter(code="ACT_SAI").exists()
    assert Evenement.objects.filter(objet_type="profil", objet_id=profil.pk).exists()


def test_une_permission_inconnue_est_refusee(connecte):
    profil = Profil.objects.create(code="ESSAI2", libelle="Autre essai", systeme=False)
    reponse = connecte("admin").patch(
        f"/api/habilitations/profils/{profil.pk}/permissions",
        data={"permission": "N_IMPORTE_QUOI", "accordee": True},
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  Delegations
# =====================================================================


def test_on_ne_delegue_que_ce_que_l_on_possede(connecte):
    """
    La regle qui empeche la delegation de devenir une escalade de privileges.
    Un point focal ne porte ni COT ni VAL : il ne peut pas deleguer « Signature ».
    """
    reponse = connecte("focal.dsi").post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": compte("agent.dsi").pk,
            "etendue": "Signature",
            "debut": "2026-09-01",
            "fin": "2026-09-15",
            "motif": "Conge",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert "on ne delegue que ce que l'on possede" in reponse.json()["message"]
    assert not Delegation.objects.exists()


def test_les_etendues_proposees_sont_celles_que_l_on_detient(connecte):
    """Le serveur seul enumere : proposer une etendue qu'il refusera ensuite
    ne ferait que deplacer le refus apres la saisie."""
    etendues = connecte("dg").get("/api/habilitations/delegations/possible").json()["etendues"]
    assert "Signature" in etendues  # le DG porte VAL
    assert "Cloture du courrier" not in etendues  # il ne porte pas CLO : c'est le SCC qui cloture
    assert "Instruction des dossiers" not in etendues  # il ne porte pas DOS_INS

    etendues_focal = (
        connecte("focal.dsi").get("/api/habilitations/delegations/possible").json()["etendues"]
    )
    # Trois depuis la migration 0018, et dans l'ordre de `ETENDUES` : le point
    # focal porte `AFF` et `BO_STR` en plus de `ACT_SAI`.
    assert etendues_focal == [
        "Affectation",
        "Bureau d'ordre de la structure",
        "Suivi des activites",
    ]


def test_on_ne_se_delegue_pas_a_soi_meme(connecte):
    reponse = connecte("dg").post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": compte("dg").pk,
            "etendue": "Signature",
            "debut": "2026-09-01",
            "fin": "2026-09-15",
            "motif": "Essai",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_une_delegation_accorde_les_permissions_au_beneficiaire(connecte):
    """Le coeur du mecanisme : les droits du beneficiaire changent pendant la
    periode, et reviennent a l'identique ensuite."""
    from noyau.habilitation.resolution import permissions_de

    beneficiaire = compte("agent.dsi")
    assert "VAL" not in permissions_de(beneficiaire)

    reponse = connecte("dg").post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": beneficiaire.pk,
            "etendue": "Signature",
            "debut": "2020-01-01",
            "fin": "2090-01-01",
            "motif": "Absence prolongee",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 200
    assert reponse.json()["etat"] == "active"
    assert reponse.json()["etendue"] == "Signature"
    assert "VAL" in permissions_de(beneficiaire)


def test_interrompre_retire_les_droits_sans_effacer_la_trace(connecte):
    """Une absence ecourtee laisserait sinon un agent signer au nom d'un autre
    revenu a son poste. Mais la delegation reste au registre."""
    from noyau.habilitation.resolution import permissions_de

    beneficiaire = compte("agent.dsi")
    client = connecte("dg")
    identifiant = client.post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": beneficiaire.pk,
            "etendue": "Signature",
            "debut": "2020-01-01",
            "fin": "2090-01-01",
            "motif": "Absence",
        },
        content_type="application/json",
    ).json()["id"]

    assert client.delete(f"/api/habilitations/delegations/{identifiant}").status_code == 204
    assert "VAL" not in permissions_de(beneficiaire)
    assert Delegation.objects.filter(pk=identifiant).exists()  # close, pas effacee


def test_un_tiers_ne_peut_pas_interrompre_la_delegation_d_un_autre(connecte):
    """404 et non 403 : « interdit » confirmerait que la delegation existe."""
    identifiant = (
        connecte("dg")
        .post(
            "/api/habilitations/delegations",
            data={
                "delegataireId": compte("agent.dsi").pk,
                "etendue": "Signature",
                "debut": "2020-01-01",
                "fin": "2090-01-01",
                "motif": "Absence",
            },
            content_type="application/json",
        )
        .json()["id"]
    )

    reponse = connecte("focal.dsi").delete(f"/api/habilitations/delegations/{identifiant}")
    assert reponse.status_code == 404
    assert Delegation.objects.get(pk=identifiant).invalide_le is None


def test_un_responsable_ne_voit_que_ses_propres_delegations(connecte):
    connecte("dg").post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": compte("agent.dsi").pk,
            "etendue": "Signature",
            "debut": "2020-01-01",
            "fin": "2090-01-01",
            "motif": "Absence",
        },
        content_type="application/json",
    )
    assert connecte("focal.dsi").get("/api/habilitations/delegations/miennes").json() == []
    assert len(connecte("dg").get("/api/habilitations/delegations/miennes").json()) == 1


def test_le_registre_complet_reste_reserve_a_l_administrateur(connecte):
    assert connecte("dg").get("/api/habilitations/delegations").status_code == 401
    assert connecte("admin").get("/api/habilitations/delegations").status_code == 200


# =====================================================================
#  Perimetres et sessions
# =====================================================================


def test_le_catalogue_de_perimetres_est_le_referentiel_des_quatre_portees(connecte):
    """
    Le catalogue n'est pas une table : ce sont les quatre portees, toujours les
    quatre, meme celles que personne ne porte. Une portee qui disparaitrait de
    l'ecran faute de titulaire ne serait plus attribuable.
    """
    lignes = connecte("admin").get("/api/habilitations/perimetres").json()
    assert [ligne["libelle"] for ligne in lignes] == [
        "Institution",
        "Structure et descendantes",
        "Structure seule",
        "Poste",
    ]
    # Les comptes du portail ne sont comptes nulle part : ils n'ont aucune
    # portee, et c'est ce qui les protege (ADR 013). Le catalogue denombre les
    # agents de l'institution, pas les titulaires de comptes.
    usagers = comptes_du_portail().count()
    assert sum(ligne["nombreAgents"] for ligne in lignes) == Utilisateur.objects.count() - usagers


def test_les_sessions_listent_leurs_agents(connecte):
    sessions = connecte("admin").get("/api/habilitations/sessions").json()
    arrivee = next(s for s in sessions if s["libelle"] == "Courrier Arrive")
    assert [a["nomComplet"] for a in arrivee["agents"]] == ["Marthe Fouda"]
    assert arrivee["courriersEnCours"] == 0


# =====================================================================
#  Administration des profils d'un agent
# =====================================================================


def test_attribuer_un_profil_exige_adm_hab(connecte):
    """Sans cette garde, n'importe qui se donnerait n'importe quel droit."""
    profil = Profil.objects.get(code="ADMIN")
    reponse = connecte("focal.dsi").post(
        f"/api/habilitations/utilisateurs/{compte('focal.dsi').pk}/profils",
        data={"profilId": profil.pk},
        content_type="application/json",
    )
    assert reponse.status_code == 401
    assert "ADM_HAB" not in permissions_de(compte("focal.dsi"))


def test_attribuer_un_profil_change_les_droits_et_laisse_une_trace(connecte):
    agent = compte("agent.dsi")
    profil = Profil.objects.get(code="ADMIN")
    assert "ADM_HAB" not in permissions_de(agent)

    reponse = connecte("admin").post(
        f"/api/habilitations/utilisateurs/{agent.pk}/profils",
        data={"profilId": profil.pk},
        content_type="application/json",
    )
    assert reponse.status_code == 204
    assert "ADM_HAB" in permissions_de(agent)
    assert Evenement.objects.filter(
        objet_type="utilisateur", objet_id=agent.pk, type_evenement="profil_attribue"
    ).exists()


def test_reattribuer_le_meme_profil_ne_cree_ni_doublon_ni_evenement(connecte):
    agent = compte("agent.dsi")
    profil = Profil.objects.get(code="ADMIN")
    client = connecte("admin")
    corps = {"profilId": profil.pk}
    client.post(
        f"/api/habilitations/utilisateurs/{agent.pk}/profils",
        data=corps,
        content_type="application/json",
    )
    client.post(
        f"/api/habilitations/utilisateurs/{agent.pk}/profils",
        data=corps,
        content_type="application/json",
    )
    assert (
        UtilisateurProfil.objects.filter(
            utilisateur=agent, profil=profil, retire_le__isnull=True
        ).count()
        == 1
    )
    assert (
        Evenement.objects.filter(objet_id=agent.pk, type_evenement="profil_attribue").count() == 1
    )


def test_retirer_un_profil_le_date_au_lieu_de_l_effacer(connecte):
    """RNF-TRACE-01 : savoir qu'un droit a ete retire, et quand."""
    agent = compte("agent.dsi")
    attribution = UtilisateurProfil.objects.get(utilisateur=agent, retire_le__isnull=True)
    reponse = connecte("admin").delete(
        f"/api/habilitations/utilisateurs/{agent.pk}/profils/{attribution.profil_id}"
    )
    assert reponse.status_code == 204
    attribution.refresh_from_db()
    assert attribution.retire_le is not None
    assert Evenement.objects.filter(objet_id=agent.pk, type_evenement="profil_retire").exists()


def test_un_agent_inconnu_sort_en_404(connecte):
    """404 et non 403 — decision D5."""
    reponse = connecte("admin").post(
        "/api/habilitations/utilisateurs/999999/profils",
        data={"profilId": 1},
        content_type="application/json",
    )
    assert reponse.status_code == 404


def test_on_ne_se_retire_pas_sa_derniere_administration(connecte):
    """Garde-fou technique : qui s'exclut de l'administration des habilitations
    ne peut plus s'y readmettre, et personne d'autre ne le peut si c'etait le
    dernier administrateur."""
    administrateur = compte("admin")
    attribution = UtilisateurProfil.objects.get(
        utilisateur=administrateur, profil__permissions__code="ADM_HAB", retire_le__isnull=True
    )
    reponse = connecte("admin").delete(
        f"/api/habilitations/utilisateurs/{administrateur.pk}/profils/{attribution.profil_id}"
    )
    assert reponse.status_code == 409
    assert "ADM_HAB" in permissions_de(administrateur)


# =====================================================================
#  Administration du perimetre d'un agent
# =====================================================================


def test_changer_la_portee_clot_l_ancien_perimetre_sans_l_effacer(connecte):
    """Le geste le plus lourd du pilier : il ne change pas ce qu'un agent peut
    faire, mais l'etendue de ce sur quoi il le fait. Il doit rester relisible."""
    agent = compte("agent.dsi")
    ancien = Perimetre.objects.get(utilisateur=agent, valide_au__isnull=True)

    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{agent.pk}/perimetre",
        data={"portee": "toutes"},
        content_type="application/json",
    )
    assert reponse.status_code == 204

    ancien.refresh_from_db()
    assert ancien.valide_au is not None
    courant = Perimetre.objects.get(utilisateur=agent, valide_au__isnull=True)
    assert courant.portee == "toutes" and courant.structure_id is None
    assert Evenement.objects.filter(objet_id=agent.pk, type_evenement="perimetre_defini").exists()


def test_une_portee_bornee_sans_structure_est_refusee(connecte):
    """« Sa structure » sans dire laquelle ne veut rien dire."""
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{compte('agent.dsi').pk}/perimetre",
        data={"portee": "structure"},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_la_portee_institution_ne_prend_pas_de_structure(connecte):
    """Accepter la structure et l'ignorer laisserait croire qu'elle borne."""
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{compte('agent.dsi').pk}/perimetre",
        data={"portee": "toutes", "structureId": 1},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_une_portee_inconnue_est_refusee(connecte):
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{compte('agent.dsi').pk}/perimetre",
        data={"portee": "institution"},  # le libelle du front, pas le code de base
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  Rattachement aux sessions courrier
# =====================================================================


def test_un_agent_ne_tient_qu_une_session_a_la_fois(connecte):
    """La contrainte est au moteur (EXCLUDE USING gist). Le service la devance
    seulement pour que le refus soit lisible."""
    marthe = compte("agent.scc")
    autre = SessionCourrier.objects.exclude(
        utilisateursession__utilisateur=marthe, utilisateursession__retire_le__isnull=True
    ).first()
    reponse = connecte("admin").post(
        f"/api/habilitations/sessions/{autre.pk}/agents",
        data={"utilisateurId": marthe.pk},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_rattacher_puis_detacher_laisse_deux_traces(connecte):
    agent = compte("agent.dsi")
    session = SessionCourrier.objects.filter(invalide_le__isnull=True, actif=True).first()
    client = connecte("admin")

    assert (
        client.post(
            f"/api/habilitations/sessions/{session.pk}/agents",
            data={"utilisateurId": agent.pk},
            content_type="application/json",
        ).status_code
        == 204
    )
    assert (
        client.delete(f"/api/habilitations/sessions/{session.pk}/agents/{agent.pk}").status_code
        == 204
    )

    rattachement = UtilisateurSession.objects.get(utilisateur=agent, session=session)
    assert rattachement.retire_le is not None
    assert (
        Evenement.objects.filter(
            objet_id=agent.pk, type_evenement__in=("session_rattachee", "session_detachee")
        ).count()
        == 2
    )


def test_detacher_un_rattachement_inexistant_sort_en_404(connecte):
    session = SessionCourrier.objects.filter(invalide_le__isnull=True).first()
    reponse = connecte("admin").delete(
        f"/api/habilitations/sessions/{session.pk}/agents/{compte('dg').pk}"
    )
    assert reponse.status_code == 404


# =====================================================================
#  Creation et cycle de vie des comptes
# =====================================================================


def structure(code: str) -> Structure:
    return Structure.objects.get(code=code, valide_au__isnull=True)


def un_poste_de(code_structure: str) -> Poste:
    poste = Poste.objects.filter(
        structure=structure(code_structure), valide_au__isnull=True
    ).first()
    assert poste is not None, f"Le jeu d'essai ne pose aucun poste a {code_structure}."
    return poste


def _saisie_compte(**ecarts) -> dict:
    """Un compte valide a la DSI. Chaque test n'ecarte que ce qu'il eprouve."""
    base = {
        "identifiant": "n.essai",
        "prenom": "Nina",
        "nom": "Essai",
        "structureId": structure("DSI").pk,
        "posteId": un_poste_de("DSI").pk,
        "profilId": Profil.objects.get(code="COLLAB").pk,
        "portee": "structure",
    }
    base.update(ecarts)
    return base


def _creer(client, **ecarts):
    return client.post(
        "/api/habilitations/utilisateurs",
        data=_saisie_compte(**ecarts),
        content_type="application/json",
    )


def test_creer_un_compte_exige_adm_hab(connecte):
    """401 et non 403 : `ExigePermission` refuse en rendant `None`, comme partout
    ailleurs sur ce routeur."""
    assert _creer(connecte("focal.dsi")).status_code == 401
    assert not Utilisateur.objects.filter(identifiant_annuaire="n.essai").exists()


def test_un_compte_naissant_porte_deja_un_profil_et_un_perimetre(connecte):
    """
    Le coeur de la route. Un compte cree sans l'un des deux se connecte et
    n'obtient que des listes vides — panne qu'on cherche partout ailleurs.
    """
    reponse = _creer(connecte("admin"))
    assert reponse.status_code == 201

    agent = Utilisateur.objects.get(identifiant_annuaire="n.essai")
    assert UtilisateurProfil.objects.filter(utilisateur=agent, retire_le__isnull=True).exists()

    perimetre = Perimetre.objects.get(utilisateur=agent, valide_au__isnull=True)
    assert perimetre.portee == "structure"
    assert perimetre.structure.code == "DSI"
    assert reponse.json()["profil"] != "(aucun)"


def test_la_creation_inscrit_les_quatre_evenements(connecte):
    """
    Le compte, son profil, son perimetre — et depuis F-04 son affectation.

    Le quatrieme n'est pas decoratif : sans lui, l'histoire des occupations
    commencerait a la premiere mutation, et ferait croire que personne n'a
    jamais tenu ce poste auparavant (ADR 015).
    """
    _creer(connecte("admin"))
    agent = Utilisateur.objects.get(identifiant_annuaire="n.essai")
    types = set(
        Evenement.objects.filter(objet_type="utilisateur", objet_id=agent.pk).values_list(
            "type_evenement", flat=True
        )
    )
    assert types == {"compte_cree", "profil_attribue", "perimetre_defini", "agent_affecte"}


def test_un_identifiant_deja_pris_est_refuse_sans_500(connecte):
    """La colonne est UNIQUE : sans controle, le doublon sortirait en 500 et une
    saisie ordinaire passerait pour une panne du serveur."""
    reponse = _creer(connecte("admin"), identifiant="dg")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "doublon"


def test_un_poste_d_une_autre_structure_est_refuse(connecte):
    """Aucune contrainte de base ne l'interdit, et le perimetre `structure` en
    serait fausse en silence."""
    reponse = _creer(connecte("admin"), posteId=un_poste_de("DAF").pk)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "poste_hors_structure"


def test_la_portee_institution_ne_prend_pas_la_structure_de_l_agent(connecte):
    """Le defaut « structure de l'agent » ne doit pas s'appliquer a `toutes`,
    que le service refuse de borner."""
    assert _creer(connecte("admin"), portee="toutes").status_code == 201
    agent = Utilisateur.objects.get(identifiant_annuaire="n.essai")
    assert Perimetre.objects.get(utilisateur=agent, valide_au__isnull=True).structure_id is None


def test_un_compte_cree_sans_mot_de_passe_ne_se_connecte_pas(connecte, client):
    """RF-ADM-02 : l'authentification revient a l'annuaire. Sans mot de passe
    local, le compte existe et attend le SSO."""
    _creer(connecte("admin"))
    client.logout()
    reponse = client.post(
        "/api/connexion",
        data={"identifiant": "n.essai", "motDePasse": "demonstration"},
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_un_compte_cree_avec_mot_de_passe_se_connecte(connecte, client):
    _creer(connecte("admin"), motDePasse="essai-un-deux")
    client.logout()
    reponse = client.post(
        "/api/connexion",
        data={"identifiant": "n.essai", "motDePasse": "essai-un-deux"},
        content_type="application/json",
    )
    assert reponse.status_code == 200


def test_un_compte_suspendu_perd_sa_session_des_la_requete_suivante(connecte, client):
    """`SessionAuth` relit `is_active` a chaque appel : rien a purger."""
    _creer(connecte("admin"), motDePasse="essai-un-deux")
    agent = Utilisateur.objects.get(identifiant_annuaire="n.essai")

    connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{agent.pk}/etat",
        data={"actif": False},
        content_type="application/json",
    )

    client.logout()
    client.force_login(agent, backend=BACKEND)
    assert client.get("/api/moi").status_code == 401


def test_on_ne_suspend_pas_son_propre_compte(connecte):
    """Fermer la porte de l'exterieur en laissant la clef dedans."""
    admin = compte("admin")
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{admin.pk}/etat",
        data={"actif": False},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "suspension_de_soi"


def test_suspendre_puis_retablir_ne_touche_ni_profil_ni_perimetre(connecte):
    agent = compte("agent.dsi")
    client = connecte("admin")
    for actif in (False, True):
        assert (
            client.patch(
                f"/api/habilitations/utilisateurs/{agent.pk}/etat",
                data={"actif": actif},
                content_type="application/json",
            ).status_code
            == 200
        )

    agent.refresh_from_db()
    assert agent.actif is True
    assert UtilisateurProfil.objects.filter(utilisateur=agent, retire_le__isnull=True).exists()
    assert Perimetre.objects.filter(utilisateur=agent, valide_au__isnull=True).exists()


def test_muter_un_agent_sans_redefinir_son_perimetre_est_refuse(connecte):
    """
    Garde-fou : l'agent verrait son ancien service et pas le nouveau, sans que
    rien ne le signale.
    """
    agent = compte("focal.dsi")
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{agent.pk}",
        data={"structureId": structure("DAF").pk, "posteId": un_poste_de("DAF").pk},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "perimetre_a_redefinir"


def test_la_mutation_passe_une_fois_le_perimetre_redefini(connecte):
    agent = compte("focal.dsi")
    client = connecte("admin")

    assert (
        client.patch(
            f"/api/habilitations/utilisateurs/{agent.pk}/perimetre",
            data={"portee": "structure", "structureId": structure("DAF").pk},
            content_type="application/json",
        ).status_code
        == 204
    )
    reponse = client.patch(
        f"/api/habilitations/utilisateurs/{agent.pk}",
        data={"structureId": structure("DAF").pk, "posteId": un_poste_de("DAF").pk},
        content_type="application/json",
    )
    assert reponse.status_code == 200
    assert reponse.json()["structure"].startswith("DAF — ")


def test_une_modification_sans_changement_n_inscrit_rien(connecte):
    """Un journal qui enregistre des non-evenements cesse d'etre lu."""
    agent = compte("agent.dsi")
    reponse = connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{agent.pk}",
        data={"prenom": agent.prenom},
        content_type="application/json",
    )
    assert reponse.status_code == 200
    assert not Evenement.objects.filter(objet_id=agent.pk, type_evenement="compte_modifie").exists()


# =====================================================================
#  La fiche d'un agent — ce qui compose ses droits
# =====================================================================


def test_la_fiche_exige_adm_hab(connecte):
    agent = compte("agent.dsi")
    assert (
        connecte("focal.dsi").get(f"/api/habilitations/utilisateurs/{agent.pk}").status_code == 401
    )


def test_la_fiche_donne_les_identifiants_de_profils_que_le_registre_joint(connecte):
    """Le registre affiche « Point focal · Administrateur » ; on ne retire pas un
    profil dont on n'a que le libelle."""
    agent = compte("focal.dsi")
    fiche = connecte("admin").get(f"/api/habilitations/utilisateurs/{agent.pk}").json()

    assert [p["libelle"] for p in fiche["profils"]] == ["Point focal de structure"]
    assert all(isinstance(p["id"], int) for p in fiche["profils"])
    assert fiche["perimetre"]["portee"] == "structure"
    assert fiche["perimetre"]["structure"].startswith("DSI — ")


def test_la_fiche_dit_si_le_compte_peut_ouvrir_une_session(connecte):
    """Un compte sans mot de passe local existe et attend l'annuaire (A20). Rien
    d'autre a l'ecran ne permettrait de le savoir."""
    client = connecte("admin")
    dsi = structure("DSI")
    creation = client.post(
        "/api/habilitations/utilisateurs",
        data=_saisie_compte(),
        content_type="application/json",
    )
    sans_acces = creation.json()["id"]
    assert client.get(f"/api/habilitations/utilisateurs/{sans_acces}").json()["accesLocal"] is False
    assert dsi  # le jeu d'essai est bien en place

    avec_acces = compte("agent.dsi")
    assert (
        client.get(f"/api/habilitations/utilisateurs/{avec_acces.pk}").json()["accesLocal"] is True
    )


def test_la_fiche_d_un_agent_inconnu_sort_en_404(connecte):
    assert connecte("admin").get("/api/habilitations/utilisateurs/999999").status_code == 404


def test_la_fiche_nomme_la_session_courrier_du_titulaire(connecte):
    fiche = (
        connecte("admin").get(f"/api/habilitations/utilisateurs/{compte('agent.scc').pk}").json()
    )
    assert fiche["sessionCourrier"] == "Courrier Arrive"
    autre = connecte("admin").get(f"/api/habilitations/utilisateurs/{compte('dg').pk}").json()
    assert autre["sessionCourrier"] is None

"""
L'ouverture de session, **par HTTP**.

Ces tests existent a cause d'un defaut precis, et il faut le raconter pour
qu'il ne revienne pas. Le backend d'authentification lisait
`utilisateur.password` — attribut qui n'existe pas, `Utilisateur` n'heritant
pas d'`AbstractBaseUser` et portant `mot_de_passe`. **Toute connexion levait
une AttributeError.**

Rien ne l'avait signale. Les tests du pilier habilitation ouvraient la session
par `force_login()`, qui pose le cookie sans jamais appeler `authenticate()` :
ils traversaient les routes, jamais la porte d'entree. Trente-neuf tests au
vert, et personne ne pouvait se connecter.

Regle qui en decoule : **la connexion se teste en postant des identifiants**,
jamais autrement. `force_login` reste legitime pour les tests qui portent sur
autre chose, mais il ne prouve rien sur l'authentification elle-meme.
"""

import pytest
from django.core.management import call_command
from django.test import Client


@pytest.fixture
def jeu(db):
    call_command("semer", force=True, verbosity=0)


def _connexion(client: Client, identifiant: str, mot_de_passe: str = "demonstration"):
    return client.post(
        "/api/connexion",
        data={"identifiant": identifiant, "motDePasse": mot_de_passe},
        content_type="application/json",
    )


# =====================================================================
#  Le cycle complet
# =====================================================================


def test_un_agent_ouvre_sa_session_et_recoit_ses_droits(client, jeu):
    reponse = _connexion(client, "focal.dsi")
    assert reponse.status_code == 200

    corps = reponse.json()
    assert corps["nomComplet"] == "Yves Manga"
    assert corps["initiales"] == "YM"
    # Les permissions sont resolues cote serveur et arrivent a plat : le front
    # ne recalcule rien.
    # `BO_STR` et `AFF` s'ajoutent depuis la migration 0018 : le point focal
    # tient le bureau d'ordre de sa structure et affecte a ses collaborateurs.
    assert set(corps["permissions"]) == {
        "LEC",
        "ACT_LEC",
        "ACT_SAI",
        "DISPO",
        "BO_STR",
        "AFF",
    }
    assert corps["perimetre"]["portee"] == "structure"
    assert corps["delegationDe"] is None


def test_la_session_survit_a_la_requete_suivante(client, jeu):
    _connexion(client, "focal.dsi")
    assert client.get("/api/moi").status_code == 200


def test_la_deconnexion_ferme_reellement_la_session(client, jeu):
    _connexion(client, "focal.dsi")
    assert client.post("/api/deconnexion").status_code == 204
    assert client.get("/api/moi").status_code == 401


def test_le_cookie_de_session_est_pose(client, jeu):
    """Aucun jeton n'est renvoye dans le corps : c'est le cookie qui porte la
    session, et il est HttpOnly. Voir ADR 004."""
    reponse = _connexion(client, "dg")
    assert "suivi_session" in reponse.cookies
    assert "token" not in reponse.json()


# =====================================================================
#  Ce qui doit echouer
# =====================================================================


def test_un_mauvais_mot_de_passe_est_refuse(client, jeu):
    reponse = _connexion(client, "focal.dsi", "pas-le-bon")
    assert reponse.status_code == 401
    assert not client.cookies.get("suivi_session", "")


def test_un_compte_inconnu_donne_le_meme_message_qu_un_mauvais_mot_de_passe(client, jeu):
    """
    Differencier les deux permettrait d'enumerer les comptes : on saurait
    lesquels existent avant d'essayer un mot de passe.
    """
    inconnu = _connexion(client, "personne", "peu-importe")
    faux = _connexion(client, "focal.dsi", "pas-le-bon")
    assert inconnu.status_code == faux.status_code == 401
    assert inconnu.json()["message"] == faux.json()["message"]


def test_un_compte_desactive_ne_se_connecte_pas(client, jeu):
    from noyau.identite.modeles import Utilisateur

    Utilisateur.objects.filter(identifiant_annuaire="focal.dsi").update(actif=False)
    assert _connexion(client, "focal.dsi").status_code == 401


def test_un_compte_sans_mot_de_passe_local_ne_se_connecte_pas(client, jeu):
    """
    Le cas SSO : le compte existe, il est actif, mais son authentification
    releve de l'annuaire. Il ne doit pas s'ouvrir avec une chaine vide.
    """
    from noyau.identite.modeles import Utilisateur

    Utilisateur.objects.filter(identifiant_annuaire="focal.dsi").update(mot_de_passe=None)
    assert _connexion(client, "focal.dsi").status_code == 401


def test_une_session_absente_sort_en_401_et_non_403(client, jeu):
    """Le garde du front redirige vers la connexion sur 401. Un 403 le ferait
    echouer sans rien dire a l'agent."""
    assert client.get("/api/moi").status_code == 401


# =====================================================================
#  CSRF
# =====================================================================


def test_la_connexion_pose_le_cookie_csrf(jeu):
    """
    Sans ce cookie, le front ne peut poster aucune ecriture. Il est pose a
    l'ouverture de session, parce que Django fait tourner le jeton a ce
    moment-la.
    """
    client = Client(enforce_csrf_checks=True)
    reponse = _connexion(client, "dg")
    assert reponse.status_code == 200
    assert "suivi_csrf" in reponse.cookies


def test_une_ecriture_sans_jeton_csrf_est_refusee(jeu):
    """
    La protection CSRF est portee par `SessionAuth` depuis ninja 1.0. Elle
    n'est pas un reglage de l'API : c'est la classe d'authentification qui
    l'active, et c'est pour cela qu'aucun `csrf=True` ne figure dans
    `config/api.py`.
    """
    client = Client(enforce_csrf_checks=True)
    _connexion(client, "dg")

    reponse = client.post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": 1,
            "etendue": "Signature",
            "debut": "2026-09-01",
            "fin": "2026-09-10",
            "motif": "Essai",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 403


def test_une_ecriture_avec_jeton_csrf_passe(jeu):
    from noyau.identite.modeles import Utilisateur

    client = Client(enforce_csrf_checks=True)
    _connexion(client, "dg")
    jeton = client.cookies["suivi_csrf"].value

    reponse = client.post(
        "/api/habilitations/delegations",
        data={
            "delegataireId": Utilisateur.objects.get(identifiant_annuaire="agent.dsi").pk,
            "etendue": "Signature",
            "debut": "2026-09-01",
            "fin": "2026-09-10",
            "motif": "Absence",
        },
        content_type="application/json",
        headers={"x-csrftoken": jeton},
    )
    assert reponse.status_code == 200


# =====================================================================
#  Delegation vue depuis la session
# =====================================================================


def test_une_delegation_en_cours_apparait_dans_la_session_du_beneficiaire(client, jeu):
    """
    Le front affiche « agit au nom de » : un agent qui agit pour un autre doit
    le voir a l'ecran. Et les permissions deleguees arrivent dans la meme liste
    plate que les siennes.
    """
    from datetime import date

    from noyau.habilitation.services import declarer_delegation
    from noyau.identite.modeles import Utilisateur

    titulaire = Utilisateur.objects.get(identifiant_annuaire="dg")
    beneficiaire = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    declarer_delegation(
        titulaire,
        delegataire_id=beneficiaire.pk,
        etendue="Signature",
        debut=date(2020, 1, 1),
        fin=date(2090, 1, 1),
        motif="Absence prolongee",
    )

    corps = _connexion(client, "agent.dsi").json()
    assert "VAL" in corps["permissions"]
    assert corps["delegationDe"]["nomComplet"] == "Emmanuel Kingue"

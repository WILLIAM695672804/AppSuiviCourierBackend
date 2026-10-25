"""
Le carnet d'adresses en ecriture — `POST /api/referentiels/correspondants`.

Ce que ces tests protegent :

 1. **Le referentiel reste ferme aux doublons.** C'est sa seule raison d'etre :
    deux entrees pour un meme ministere donnent deux histoires, chacune portant
    la moitie de ses courriers, et le compte « 14 courriers recus » que l'agent
    lit dans le selecteur devient faux.
 2. **Un agent de session peut creer.** L'inverse arreterait le registre : le
    courrier est dans sa main, l'expediteur n'est pas au carnet, et attendre
    l'administrateur fonctionnel n'est pas une reponse.
 3. **La creation laisse une trace.** C'est la contrepartie du point 2
    (RNF-TRACE-01) : ce n'est pas la permission qui tient le carnet propre,
    c'est le journal.
"""

import pytest
from django.core.management import call_command
from django.db import connection

from noyau.identite.modeles import Utilisateur
from noyau.parametrage.modeles import Correspondant

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
CHEMIN = "/api/referentiels/correspondants"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


@pytest.fixture
def carnet(jeu):
    """
    Le referentiel garni, sans lequel la recherche n'a rien a trouver.

    `semer` ne pose aucun correspondant — c'est un organigramme d'essai, pas un
    carnet d'adresses. Le jeu de demonstration, lui, en tient vingt-six, et son
    module ne cree que des correspondants : il ne demande pas l'organigramme
    reel. Les recopier ici les aurait fait diverger au premier ajout.
    """
    from noyau.demonstration import correspondants as carnet_de_demonstration

    return carnet_de_demonstration.semer(lambda _: None)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


def creer(client, **champs):
    corps = {"type": "administration", "raisonSociale": "Ministère des Transports"} | champs
    return client.post(CHEMIN, corps, content_type="application/json")


def evenements(objet_id: int) -> list[str]:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT type_evenement FROM evenement WHERE objet_type = 'correspondant' "
            "AND objet_id = %s",
            [objet_id],
        )
        return [ligne[0] for ligne in curseur.fetchall()]


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_la_creation_est_refusee(client, jeu):
    assert creer(client).status_code == 401


def test_un_agent_de_session_peut_creer(connecte):
    """
    `agent.scc` tient le service central du courrier : c'est lui qui a
    l'enveloppe en main. Lui refuser la creation reviendrait a arreter le
    registre chaque fois qu'un expediteur manque au carnet.
    """
    reponse = creer(connecte("agent.scc"))
    assert reponse.status_code == 201, reponse.content


def test_un_agent_sans_ENR_ne_cree_pas(connecte):
    """
    `agent.dsi` lit les referentiels pour choisir, il n'ecrit pas dedans.

    **401 et non 403.** `exige()` rend `None` quand la permission manque, ce que
    django-ninja traduit en « non authentifie » : la garde du front redirige
    alors vers la connexion plutot que d'afficher un ecran mort. Voir
    `noyau/habilitation/dependances.py`.
    """
    assert creer(connecte("agent.dsi")).status_code == 401


# =====================================================================
#  Ce que la route rend, et ce qu'elle refuse
# =====================================================================


def test_la_reponse_a_la_forme_du_selecteur(connecte):
    """
    Meme forme que la recherche : le selecteur affiche l'entree creee sans
    second aller-retour. Les compteurs sont a zero, et c'est la verite — un
    correspondant tout juste inscrit n'a envoye aucun courrier.
    """
    fiche = creer(connecte("agent.scc")).json()

    assert set(fiche) == {
        "id",
        "libelle",
        "sigle",
        "categorie",
        "initiales",
        "nombreCourriers",
        "dernierCourrier",
    }
    assert fiche["libelle"] == "Ministère des Transports"
    assert fiche["initiales"] == "MT"
    assert fiche["nombreCourriers"] == 0
    assert fiche["dernierCourrier"] is None


def test_un_sigle_deja_pris_est_refuse(connecte):
    """Deux « MINFI » sont un seul ministere, quel que soit le nom qui suit."""
    client = connecte("agent.scc")
    creer(client, raisonSociale="Ministère des Finances du Cameroun", sigle="MINFI")

    reponse = creer(client, raisonSociale="Minfi", sigle="min fi")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "doublon_correspondant"


def test_la_saisie_est_normalisee(connecte):
    """
    Espaces doubles, apostrophe courbe, courriel en capitales : ce qui est ecrit
    une fois est lu mille fois, et deux entrees qui ne different que par une
    espace sont le meme correspondant.
    """
    fiche = creer(
        connecte("agent.scc"),
        raisonSociale="  Agence   des  Douanes ",
        sigle="agc dou",
    ).json()

    assert fiche["libelle"] == "Agence des Douanes"
    assert fiche["sigle"] == "AGCDOU"


def test_une_designation_deja_prise_est_refusee(connecte):
    """La casse, les accents et les espaces de bord ne font pas deux
    correspondants — c'est `texte_recherche()` qui compare, la meme fonction
    que la recherche. Refuser un doublon que la recherche ne trouverait pas
    serait le pire des deux mondes."""
    client = connecte("agent.scc")
    assert creer(client).status_code == 201

    reponse = creer(client, raisonSociale="  ministère des transports  ")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "doublon_correspondant"
    assert Correspondant.objects.filter(raison_sociale__icontains="Transports").count() == 1


def test_une_personne_physique_se_designe_par_son_nom(connecte):
    """
    `raison_sociale` **ou** `nom` : la contrainte `correspondant_identite` du
    socle exige l'un des deux, jamais les deux.
    """
    fiche = creer(
        connecte("agent.scc"),
        type="usager",
        raisonSociale="",
        nom="Bamba",
        prenom="Sekou",
    ).json()

    assert fiche["libelle"] == "Bamba Sekou"


def test_une_entree_sans_identite_est_refusee(connecte):
    """Sans ce controle, la contrainte du socle repondrait par une 500."""
    reponse = creer(connecte("agent.scc"), raisonSociale="", nom="")

    assert reponse.status_code == 422
    assert reponse.json()["code"] == "identite_manquante"


def test_un_type_hors_socle_est_refuse(connecte):
    reponse = creer(connecte("agent.scc"), type="fournisseur")

    assert reponse.status_code == 422
    assert reponse.json()["code"] == "type_inconnu"


# =====================================================================
#  La trace
# =====================================================================


def test_la_creation_est_inscrite_au_journal(connecte):
    """
    RNF-TRACE-01. Sous `correspondant` et non sous `courrier` : le carnet
    n'appartient a aucun courrier, meme lorsque c'est en enregistrant l'un
    d'eux que l'entree a ete creee.
    """
    fiche = creer(connecte("agent.scc")).json()

    assert evenements(fiche["id"]) == ["correspondant_cree"]


# =====================================================================
#  La recherche — `GET /api/referentiels/correspondants`
# =====================================================================


def chercher(client, terme: str) -> list[str]:
    reponse = client.get(f"{CHEMIN}?q={terme}")
    assert reponse.status_code == 200, reponse.content
    return [ligne["libelle"] for ligne in reponse.json()]


def test_une_faute_de_frappe_trouve_quand_meme(connecte, carnet):
    """
    Le filet trigramme, par mot (`<%`) et non par ligne (`%`) : « minstere »
    compare a « ministere des transports » donne une ressemblance faible si l'on
    compare la ligne entiere — la cible est longue, et la faute se noie sous les
    mots qui ne la concernent pas.
    """
    trouves = chercher(connecte("agent.scc"), "minstere")

    assert any("Ministère" in libelle for libelle in trouves)


def test_l_apostrophe_ne_coupe_plus_le_mot(connecte, carnet):
    """
    Le plein texte indexe « N'Djamena » sous « djamen » : « ndjamena » ne le
    trouvait pas. `texte_recherche()` retire l'apostrophe au lieu de la
    remplacer par une espace, ce qui aurait garde le mot coupe en deux.
    """
    assert any("Djamena" in libelle for libelle in chercher(connecte("agent.scc"), "ndjamena"))


def test_la_ville_ne_brouille_pas_les_trigrammes(connecte, carnet):
    """
    « douanes » ressemble a « Douala » a 0,71. Tant que la ville etait dans la
    cible des trigrammes, la Direction Generale des Douanes passait derriere
    quatre entreprises doualaises. La ville reste cherchable en plein texte —
    c'est la ressemblance approximative qui ne doit pas porter sur elle.
    """
    assert chercher(connecte("agent.scc"), "douanes")[0] == "Direction Générale des Douanes"


def test_le_sigle_trouve_l_entree(connecte, carnet):
    """« MINFI » est ce que l'agent tape en premier : c'est ce qui est imprime
    sur l'en-tete de la lettre qu'il tient."""
    client = connecte("agent.scc")
    creer(client, raisonSociale="Ministère de la Santé Publique", sigle="MINSANTE")

    assert chercher(client, "minsante") == ["Ministère de la Santé Publique"]


def test_une_frappe_partielle_trouve_le_correspondant(connecte, carnet):
    """
    La recherche est par prefixe. Avec `websearch`, « minis » ne trouvait rien :
    l'agent en concluait que l'entree manquait, et la creait en double — soit
    exactement ce que ce referentiel existe pour empecher.
    """
    trouves = chercher(connecte("agent.scc"), "minis")

    assert any("Ministère" in libelle for libelle in trouves)


def test_les_mots_se_cumulent(connecte, carnet):
    """Deux mots restreignent, ils n'elargissent pas : `mot:* & mot:*`."""
    client = connecte("agent.scc")

    assert len(chercher(client, "minis trans")) < len(chercher(client, "minis"))


def test_les_accents_ne_comptent_pas(connecte, carnet):
    """Configuration `fr_unaccent` : « Impots » doit trouver « Impôts »."""
    client = connecte("agent.scc")

    assert chercher(client, "ministere") == chercher(client, "ministère")


def test_une_frappe_de_ponctuation_ne_fait_pas_tomber_la_route(connecte, carnet):
    """
    Le terme part en `tsquery` : un `&`, un `|` ou une parenthese y seraient des
    operateurs, et une parenthese non fermee ferait repondre 500 a une
    recherche. Seules les suites de lettres et de chiffres sont retenues.
    """
    assert chercher(connecte("agent.scc"), "((|&") == []


def test_un_correspondant_cree_est_trouvable_aussitot(connecte, carnet):
    """
    Le vecteur est pose par le declencheur `correspondant_recherche_maj`, jamais
    par l'application. Ce test le verifie de bout en bout : sans lui, la creation
    inscrirait une entree que la recherche ne rendrait jamais.
    """
    client = connecte("agent.scc")
    creer(client, raisonSociale="Chambre de Commerce du Littoral")

    assert "Chambre de Commerce du Littoral" in chercher(client, "chambre")

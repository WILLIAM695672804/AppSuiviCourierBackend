"""
Le tableau de relance — `GET /api/suivi/relance`.

Premiere partie du pilier suivi, dont les huit routes repondaient 404 jusqu'au
28 aout 2026.

Ce que ces tests protegent, dans l'ordre :

 1. **La visibilite.** Comme partout dans le pilier, l'echec ne provoque aucun
    plantage : il montre a un agent un dossier qu'il n'a pas a lire. Les
    indicateurs sont eprouves autant que les lignes — un compteur calcule hors
    perimetre est une fuite discrete, le nombre dit quelque chose meme quand la
    liste est fermee.
 2. **Les cinq onglets sont des filtres, pas des etapes.** Un dossier hors delai
    peut aussi etre sans accuse, et une vue inconnue ne vide pas l'ecran.
 3. **Les indicateurs ne suivent pas l'onglet.** Ils repondent a « ou en est le
    Port », pas a « que montre cette liste » : les changer avec le filtre aurait
    donne quatre cartes qui repetent le tableau.
 4. **Les trois hypotheses sont lues en base** (A76, A77, A78) et non ecrites en
    dur : corriger un seuil ne doit pas demander un redeploiement.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from courrier.modeles import STATUT_CLOTURE, Courrier, Relance
from noyau.habilitation.modeles import Profil, UtilisateurProfil
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, Nature
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
RELANCE = "/api/suivi/relance"
COURRIERS = "/api/courriers"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    vider_cache()
    yield
    vider_cache()


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(compte(identifiant), backend=BACKEND)
        return client

    return _connecter


@pytest.fixture
def expediteur(jeu) -> Correspondant:
    return Correspondant.objects.create(type="externe", raison_sociale="Sotrapal", ville="Douala")


def _enregistrer_et_coter(session, expediteur: Correspondant, code_structure: str) -> int:
    """Un courrier arrive, cote a une structure, sans affectation ni decharge."""
    identifiant = session.post(
        COURRIERS,
        {
            "typeSession": "ARRIVE",
            "natureId": Nature.objects.get(code="DEMANDE").pk,
            "correspondantId": expediteur.pk,
            "objet": "Demande de raccordement electrique du quai 12",
            "nombrePages": 3,
            "delaiJours": 5,
        },
        content_type="application/json",
    ).json()["id"]

    session.post(
        f"{COURRIERS}/{identifiant}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code=code_structure).pk],
        },
        content_type="application/json",
    )
    return identifiant


@pytest.fixture
def cote(connecte, expediteur) -> int:
    """
    Un courrier enregistre puis cote au Service des etudes, sans affectation.

    C'est l'etat le plus courant du tableau : le dossier est arrive quelque part
    et personne ne l'a encore pris. Il a un responsable de structure — c'est lui
    qui recoit la relance a defaut de detenteur.
    """
    return _enregistrer_et_coter(connecte("agent.scc"), expediteur, "DSI-ET")


@pytest.fixture
def cote_sans_responsable(connecte, expediteur) -> int:
    """
    Le meme, cote a une structure dont **aucun poste n'est pourvu**.

    `DSI-IN` n'a pas de compte dans le semis, donc pas de poste : ni detenteur,
    ni responsable a qui remonter. C'est le seul montage qui produise l'ecart
    « affectez-le d'abord » — une structure pourvue rend toujours un
    destinataire.
    """
    return _enregistrer_et_coter(connecte("agent.scc"), expediteur, "DSI-IN")


def _numeros(reponse) -> list[str]:
    return [ligne["numero"] for ligne in reponse.json()["lignes"]]


def _clore(identifiant: int) -> None:
    """
    Clot un courrier sans passer par la route.

    **`cloture_le` avec le statut, jamais l'un sans l'autre** : le CHECK
    `courrier_cloture_coherente` du socle impose l'equivalence, et un
    `update(statut_courrier=...)` seul echoue en `IntegrityError`.
    """
    Courrier.objects.filter(pk=identifiant).update(
        statut_courrier=STATUT_CLOTURE, cloture_le=timezone.now()
    )


def _en_retard(identifiant: int, jours: int = 10) -> None:
    """Fait echoir le courrier dans le passe, sans passer par une route."""
    Courrier.objects.filter(pk=identifiant).update(date_limite=date.today() - timedelta(days=jours))


# =====================================================================
#  Ce que l'ecran montre
# =====================================================================


def test_le_tableau_classe_le_plus_en_retard_en_tete(connecte, cote):
    """
    L'ecran se lit du haut : ce qui deborde le plus decide de la relance du
    lundi matin, et la deux-centieme ligne n'a jamais decide de rien.
    """
    _en_retard(cote, jours=30)

    lignes = connecte("dir.dsi").get(f"{RELANCE}?vue=horsDelai").json()["lignes"]

    assert lignes, "Le courrier echu doit figurer au tableau."
    depassements = [ligne["delai"]["joursDepassement"] for ligne in lignes if ligne["delai"]]
    assert depassements == sorted(depassements, reverse=True)


def test_un_dossier_sans_agent_le_dit(connecte, cote):
    """
    `agent` a `null` n'est pas un trou dans la donnee : c'est le motif de relance
    le plus frequent — le courrier est arrive quelque part et n'a ete confie a
    personne. L'ecran ecrit alors « Non affecté ».
    """
    _en_retard(cote)

    ligne = next(
        ligne
        for ligne in connecte("dir.dsi").get(f"{RELANCE}?vue=horsDelai").json()["lignes"]
        if ligne["id"] == cote
    )

    assert ligne["agent"] is None
    assert ligne["structure"] == "DSI-ET"
    assert ligne["derniereRelance"] is None
    assert ligne["niveauEscalade"] == 0


def test_l_agent_affecte_apparait(connecte, cote):
    directrice = connecte("dir.dsi")
    directrice.post(
        f"{COURRIERS}/{cote}/affectations",
        {"utilisateurId": compte("agent.dsi").pk, "consigne": "Etude technique"},
        content_type="application/json",
    )
    _en_retard(cote)

    ligne = next(
        ligne
        for ligne in directrice.get(f"{RELANCE}?vue=horsDelai").json()["lignes"]
        if ligne["id"] == cote
    )
    assert ligne["agent"] == f"{compte('agent.dsi').prenom} {compte('agent.dsi').nom}"


# =====================================================================
#  Les cinq onglets
# =====================================================================


def test_un_dossier_clos_ne_se_relance_pas(connecte, cote):
    """
    Quel qu'ait ete son retard. Il compte en revanche dans le taux de respect,
    qui est la seule mesure du module a regarder des dossiers fermes.
    """
    _en_retard(cote)
    _clore(cote)

    numero = Courrier.objects.get(pk=cote).numero
    client = connecte("dir.dsi")
    assert numero not in _numeros(client.get(f"{RELANCE}?vue=tous"))
    assert numero not in _numeros(client.get(f"{RELANCE}?vue=horsDelai"))


def test_sous_48h_ecarte_ce_qui_est_deja_echu(connecte, cote):
    """
    Les deux onglets ne doivent pas compter le meme dossier : « sous 48 h » sert
    a prevenir, « hors delai » a relancer. Un dossier deja echu releve du second,
    et l'afficher dans les deux ferait relancer deux fois.
    """
    _en_retard(cote, jours=3)
    client = connecte("dir.dsi")
    numero = Courrier.objects.get(pk=cote).numero

    assert numero in _numeros(client.get(f"{RELANCE}?vue=horsDelai"))
    assert numero not in _numeros(client.get(f"{RELANCE}?vue=sous48h"))

    Courrier.objects.filter(pk=cote).update(date_limite=date.today() + timedelta(days=1))
    assert numero in _numeros(client.get(f"{RELANCE}?vue=sous48h"))


def test_sans_accuse_ne_retient_que_ce_qui_est_affecte(connecte, cote):
    """
    Un courrier que personne ne detient n'est pas « sans accuse » : il est sans
    destinataire, ce qui est un autre defaut et se lit dans la colonne « Agent ».
    """
    directrice = connecte("dir.dsi")
    numero = Courrier.objects.get(pk=cote).numero

    assert numero not in _numeros(directrice.get(f"{RELANCE}?vue=sansAccuse"))

    directrice.post(
        f"{COURRIERS}/{cote}/affectations",
        {"utilisateurId": compte("agent.dsi").pk, "consigne": "Etude technique"},
        content_type="application/json",
    )
    assert numero in _numeros(directrice.get(f"{RELANCE}?vue=sansAccuse"))


def test_une_vue_inconnue_ne_vide_pas_l_ecran(connecte, cote):
    """
    Convention du registre : un filtre mal orthographie qui vide l'ecran se lit
    comme une panne.
    """
    tous = connecte("dir.dsi").get(f"{RELANCE}?vue=tous").json()["lignes"]
    inconnue = connecte("dir.dsi").get(f"{RELANCE}?vue=nawak").json()["lignes"]
    assert len(inconnue) == len(tous)


# =====================================================================
#  La visibilite
# =====================================================================


def test_le_tableau_ne_montre_pas_le_dossier_d_une_autre_structure(connecte, cote):
    """
    La regle de visibilite s'applique ici comme partout : `visibles()`, jamais un
    filtre recopie a la main.
    """
    _en_retard(cote)
    numero = Courrier.objects.get(pk=cote).numero
    assert numero not in _numeros(connecte("dir.daf").get(f"{RELANCE}?vue=tous"))


def test_les_indicateurs_sont_bornes_au_perimetre(connecte, cote):
    """
    Un compteur calcule hors perimetre est une fuite discrete : le nombre dit
    quelque chose meme quand la liste est fermee.
    """
    _en_retard(cote)
    dsi = connecte("dir.dsi").get(f"{RELANCE}?vue=tous").json()
    daf = connecte("dir.daf").get(f"{RELANCE}?vue=tous").json()

    assert dsi["indicateurs"]["horsDelai"] >= 1
    assert len(dsi["lignes"]) != len(daf["lignes"]) or dsi["lignes"] != daf["lignes"]


def test_les_indicateurs_ne_suivent_pas_l_onglet(connecte, cote):
    """
    Ils repondent a « ou en est le Port », pas a « que montre cette liste ». Les
    faire suivre le filtre aurait donne quatre cartes qui repetent le tableau
    juste en dessous.
    """
    _en_retard(cote)
    client = connecte("dir.dsi")
    hors_delai = client.get(f"{RELANCE}?vue=horsDelai").json()["indicateurs"]
    clotures = client.get(f"{RELANCE}?vue=dejaRelances").json()["indicateurs"]
    assert hors_delai == clotures


# =====================================================================
#  Les trois hypotheses, lues en base
# =====================================================================


def test_le_seuil_du_retard_grave_se_lit_en_base(connecte, cote):
    """
    A76. La valeur etait en dur dans le composant React — « au-dela de 5 jours ».
    La deplacer en base ne la rend pas vraie : elle la rend corrigible.
    """
    _en_retard(cote, jours=4)
    client = connecte("dir.dsi")

    Parametre.objects.filter(cle="suivi.retard_grave_jours").update(valeur="10")
    vider_cache()
    haut = client.get(f"{RELANCE}?vue=horsDelai").json()["indicateurs"]["horsDelaiGrave"]

    Parametre.objects.filter(cle="suivi.retard_grave_jours").update(valeur="1")
    vider_cache()
    bas = client.get(f"{RELANCE}?vue=horsDelai").json()["indicateurs"]["horsDelaiGrave"]

    assert bas > haut


def test_le_niveau_d_escalade_suit_les_relances_emises(connecte, cote):
    """
    A77. Une relance vaut un niveau, plafonne a trois — le sommet de la
    hierarchie du Port. La table `relance` du socle porte les deux piliers ;
    seule la cible change.
    """
    _en_retard(cote)
    with connection.cursor() as curseur:
        for _ in range(2):
            curseur.execute(
                """
                INSERT INTO relance (courrier_id, nature, emetteur_id, destinataire_id, emise_le)
                VALUES (%s, 'manuelle', %s, %s, now())
                """,
                [cote, compte("dir.dsi").pk, compte("agent.dsi").pk],
            )

    ligne = next(
        ligne
        for ligne in connecte("dir.dsi").get(f"{RELANCE}?vue=horsDelai").json()["lignes"]
        if ligne["id"] == cote
    )
    assert ligne["niveauEscalade"] == 2
    assert ligne["derniereRelance"] is not None


def test_les_relances_d_activite_ne_comptent_pas_dans_le_mois(connecte, cote):
    """
    La table est partagee avec le pilier activite. L'ecran est celui du courrier :
    compter les relances d'activite ferait un chiffre que rien sur l'ecran
    n'explique.
    """
    avant = connecte("dir.dsi").get(f"{RELANCE}?vue=tous").json()["indicateurs"]["relancesMois"]

    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO relance (courrier_id, nature, emetteur_id, destinataire_id, emise_le)
            VALUES (%s, 'manuelle', %s, %s, now())
            """,
            [cote, compte("dir.dsi").pk, compte("agent.dsi").pk],
        )

    apres = connecte("dir.dsi").get(f"{RELANCE}?vue=tous").json()["indicateurs"]["relancesMois"]
    assert apres == avant + 1


def test_le_taux_de_respect_compte_les_dossiers_clos_dans_leur_delai(connecte, cote):
    """
    A78. La seule mesure du module qui regarde le passe : un taux de respect se
    constate a la cloture, jamais en cours de route. Le jour de l'echeance compte
    comme tenu — un courrier clos le jour de sa date limite n'est pas en retard.
    """
    Courrier.objects.filter(pk=cote).update(
        statut_courrier=STATUT_CLOTURE,
        date_limite=date.today(),
        cloture_le=timezone.now(),
    )

    taux = connecte("dir.dsi").get(f"{RELANCE}?vue=tous").json()["indicateurs"]["tauxRespect"]
    assert taux == 100


def test_le_tableau_exige_la_lecture_du_registre(connecte, cote):
    """
    Sous `LEC` et non sous `REL` : le tableau est borne par `visibles()` et ne
    dit rien qu'on ne lise deja au registre. Le geste de relancer, lui, reste
    sous `REL`.
    """
    sans_lecture = Utilisateur.objects.filter(actif=True).exclude(
        profils__profil__permissions__code="LEC",
        profils__retire_le__isnull=True,
    )
    agent = sans_lecture.first()
    if agent is None:
        pytest.skip("Tous les comptes du semis portent LEC.")

    assert connecte(agent.identifiant_annuaire).get(RELANCE).status_code == 401


# =====================================================================
#  Le geste — `POST /api/suivi/relances`
# =====================================================================

RELANCES = "/api/suivi/relances"


def test_relancer_ecrit_a_l_agent_affecte(connecte, cote):
    """
    **On ne relance pas un courrier, on relance quelqu'un.** La colonne
    `destinataire_id` est `NOT NULL` au socle depuis `0001`, et c'est cette
    contrainte qui structure tout le geste.
    """
    _en_retard(cote)
    agent = Utilisateur.objects.filter(
        poste__structure=Structure.objects.get(code="DSI-ET"), actif=True
    ).first()
    connecte("dir.dsi").post(
        f"{COURRIERS}/{cote}/affectations",
        {
            "structureId": Structure.objects.get(code="DSI-ET").pk,
            "utilisateurId": agent.pk,
            "consigne": "",
        },
        content_type="application/json",
    )

    bilan = (
        connecte("dsr")
        .post(
            RELANCES,
            {"identifiants": [cote], "motif": "Échéance dépassée."},
            content_type="application/json",
        )
        .json()
    )

    assert bilan["emises"] == 1
    assert bilan["destinataires"] == [agent.nom_complet]
    assert Relance.objects.get(courrier_id=cote).destinataire_id == agent.pk


def test_un_dossier_sans_detenteur_est_ecarte_avec_sa_raison(connecte, cote_sans_responsable):
    """
    Le cas ou l'ecran doit dire autre chose que « échec » : un courrier que
    personne n'a pris, dans une structure sans poste pourvu, demande une
    **affectation** et pas une relance. Le message le dit.

    Sans detenteur mais avec un responsable, la relance part au responsable :
    c'est `test_a_defaut_d_affectation_le_responsable_est_relance`.
    """
    cote = cote_sans_responsable
    _en_retard(cote)

    reponse = connecte("dsr").post(
        RELANCES, {"identifiants": [cote]}, content_type="application/json"
    )

    # Tout le lot est ecarte : le serveur refuse plutot que d'annoncer un succes
    # sur zero relance.
    assert reponse.status_code == 409
    assert "affectez-le d'abord" in reponse.json()["message"]
    assert not Relance.objects.filter(courrier_id=cote).exists()


def test_a_defaut_d_affectation_le_responsable_est_relance(connecte, cote):
    """
    Un dossier que personne n'a pris se relance chez le responsable de la
    structure cotee. C'est le pendant du test precedent : l'ecart « affectez-le
    d'abord » ne survient que la ou aucun poste n'est pourvu.
    """
    _en_retard(cote)

    reponse = connecte("dsr").post(
        RELANCES, {"identifiants": [cote]}, content_type="application/json"
    )

    assert reponse.status_code == 200, reponse.content
    assert reponse.json()["emises"] == 1
    assert Relance.objects.filter(courrier_id=cote).exists()


def test_un_lot_partiel_part_quand_meme(connecte, cote, expediteur):
    """
    **Un lot est partiel par nature.** Sur quatorze retards du lundi matin, deux
    seront sans detenteur. Refuser les quatorze pour deux lignes obligerait
    l'agent a deviner lesquelles.
    """
    _en_retard(cote)
    agent = Utilisateur.objects.filter(
        poste__structure=Structure.objects.get(code="DSI-ET"), actif=True
    ).first()
    connecte("dir.dsi").post(
        f"{COURRIERS}/{cote}/affectations",
        {
            "structureId": Structure.objects.get(code="DSI-ET").pk,
            "utilisateurId": agent.pk,
            "consigne": "",
        },
        content_type="application/json",
    )
    orphelin = (
        connecte("agent.scc")
        .post(
            COURRIERS,
            {
                "typeSession": "ARRIVE",
                "natureId": Nature.objects.get(code="DEMANDE").pk,
                "correspondantId": expediteur.pk,
                "objet": "Dossier que personne n'a pris",
                "nombrePages": 1,
                "delaiJours": 5,
            },
            content_type="application/json",
        )
        .json()["id"]
    )

    bilan = (
        connecte("dsr")
        .post(
            RELANCES,
            {"identifiants": [cote, orphelin]},
            content_type="application/json",
        )
        .json()
    )

    assert bilan["emises"] == 1
    assert len(bilan["ecartes"]) == 1


def test_la_relance_fait_avancer_le_tableau(connecte, cote):
    """
    Le tableau prepare le geste et le geste nourrit le tableau : « Dernière
    relance », le niveau d'escalade et l'onglet « Déjà relancés » bougent
    ensemble. Un ecran qui ne montre pas l'effet de son propre bouton fait
    recliquer.
    """
    _en_retard(cote)
    agent = Utilisateur.objects.filter(
        poste__structure=Structure.objects.get(code="DSI-ET"), actif=True
    ).first()
    connecte("dir.dsi").post(
        f"{COURRIERS}/{cote}/affectations",
        {
            "structureId": Structure.objects.get(code="DSI-ET").pk,
            "utilisateurId": agent.pk,
            "consigne": "",
        },
        content_type="application/json",
    )
    session = connecte("dsr")
    session.post(RELANCES, {"identifiants": [cote]}, content_type="application/json")

    ligne = next(
        ligne
        for ligne in session.get(f"{RELANCE}?vue=dejaRelances").json()["lignes"]
        if ligne["id"] == cote
    )

    assert ligne["derniereRelance"] is not None
    assert ligne["niveauEscalade"] == 1
    assert session.get(f"{RELANCE}?vue=horsDelai").json()["indicateurs"]["relancesMois"] >= 1


def test_relancer_demande_la_permission_de_relancer(connecte, cote):
    """
    **Sous `REL` et non sous `LEC`**, contrairement au tableau qui la prepare.
    Lire « qu'est-ce qui ne se fait pas chez moi » est une question de
    responsable ; ecrire a quatorze agents est un acte de la Division du suivi.
    """
    _en_retard(cote)

    reponse = connecte("agent.scc").post(
        RELANCES, {"identifiants": [cote]}, content_type="application/json"
    )

    assert reponse.status_code == 401


def test_on_ne_relance_pas_hors_de_son_perimetre(connecte, cote):
    """
    **Le test qui compte.** L'echec ne provoquerait aucune erreur visible : juste
    une notification adressee a l'agent d'une direction dont on n'a pas a
    connaitre les dossiers. Le lot est borne par `visibles()`, comme toute
    lecture.

    Le montage est necessaire : dans le jeu livre, `REL` n'est porte que par
    `DSR` et `ATT_DSR`, tous deux de portee `toutes`. Personne n'y detient donc a
    la fois le droit de relancer et un perimetre restreint — c'est-a-dire
    exactement la situation que ce test doit couvrir. On attribue le profil a un
    directeur, qui garde le sien : un responsable a qui l'on confie la relance de
    sa direction, ce que le Port fera le jour ou la DSR deleguera.
    """
    _en_retard(cote)
    directeur = compte("dir.daf")
    UtilisateurProfil.objects.create(
        utilisateur=directeur,
        profil=Profil.objects.get(code="DSR"),
        attribue_par=compte("dg").pk,
    )

    reponse = connecte("dir.daf").post(
        RELANCES, {"identifiants": [cote]}, content_type="application/json"
    )

    assert reponse.status_code == 409
    assert "introuvable" in reponse.json()["message"].lower()
    assert not Relance.objects.filter(courrier_id=cote).exists()


def test_le_geste_refuse_un_dossier_clos(connecte, cote):
    """
    Le tableau l'ecarte deja de ses lignes ; le service le refuse aussi. Une
    garde de lecture n'est pas une garde d'ecriture — un identifiant se poste a
    la main.
    """
    _clore(cote)

    reponse = connecte("dsr").post(
        RELANCES, {"identifiants": [cote]}, content_type="application/json"
    )

    assert reponse.status_code == 409
    assert "clos" in reponse.json()["message"]


def test_un_lot_vide_est_refuse(connecte, jeu):
    reponse = connecte("dsr").post(RELANCES, {"identifiants": []}, content_type="application/json")

    assert reponse.status_code == 409

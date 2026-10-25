"""
Le dossier de traitement et la recherche avancee — `/api/suivi`.

Deuxieme et troisieme parties du pilier suivi. Les routes servies ici
repondaient 404 jusqu'au 28 aout 2026 : le front les appelait toutes, et l'ecran
de portefeuille affichait « les délais sont tenus » sur l'erreur — ADR 011, le
pilotage nomme ce qu'il ne mesure pas.

Ce que ces tests protegent, dans l'ordre :

 1. **Le portefeuille est une corbeille, pas un registre.** Il montre ce qui est
    *affecte* a l'agent, pas ce qu'il *voit*. La difference se compte en deux
    ordres de grandeur pour un directeur, et la confondre reduirait l'ecran a un
    doublon du registre.
 2. **La note privee ne sort pas de la hierarchie.** C'est la seule regle de
    confidentialite propre au pilier, et son echec ne provoque aucune erreur :
    juste un texte lu par qui ne devait pas.
 3. **`actionsPossibles` vient du serveur.** Un bouton propose puis refuse a
    l'envoi est la panne la plus commune de cet ecran.
 4. **Demander n'est pas accorder.** Une demande de report ne deplace aucune
    echeance ; seule la decision du responsable appelle `prolonger()`.
 5. **Les criteres de recherche se cumulent**, sauf les cases d'une meme famille
    qui s'additionnent — c'est ce qu'un formulaire a dix champs laisse attendre.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from courrier.modeles import (
    DEMANDE_ACCORDEE,
    DEMANDE_EN_ATTENTE,
    STATUT_CLOTURE,
    Courrier,
    DemandeDelai,
    NoteTraitement,
)
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, Nature

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
SUIVI = "/api/suivi"
COURRIERS = "/api/courriers"


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


@pytest.fixture
def expediteur(jeu) -> Correspondant:
    return Correspondant.objects.create(type="externe", raison_sociale="Sotrapal", ville="Douala")


@pytest.fixture
def affecte(connecte, expediteur) -> tuple[int, Utilisateur]:
    """
    Un courrier enregistre, cote a la DSI, puis affecte a un agent de la DSI.

    C'est l'etat normal d'un dossier de travail : quelqu'un l'a sur les bras, et
    c'est ce que le pilier suivi decrit. Rend l'identifiant du courrier et le
    compte de l'agent affecte.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        COURRIERS,
        {
            "typeSession": "ARRIVE",
            "natureId": Nature.objects.get(code="DEMANDE").pk,
            "correspondantId": expediteur.pk,
            "objet": "Raccordement électrique du quai 12",
            "nombrePages": 3,
            "delaiJours": 5,
        },
        content_type="application/json",
    ).json()["id"]

    structure = Structure.objects.get(code="DSI-ET")
    session.post(
        f"{COURRIERS}/{identifiant}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [structure.pk],
        },
        content_type="application/json",
    )

    agent = Utilisateur.objects.filter(
        poste__structure=structure, actif=True, identifiant_annuaire__startswith="agent"
    ).first() or compte("dir.dsi")

    connecte("dir.dsi").post(
        f"{COURRIERS}/{identifiant}/affectations",
        {
            "structureId": structure.pk,
            "utilisateurId": agent.pk,
            "consigne": "Rapprocher du bon de commande, puis rédiger le projet de réponse.",
        },
        content_type="application/json",
    )
    return identifiant, agent


def _clore(identifiant: int) -> None:
    """
    Clot un courrier sans passer par la route.

    **`cloture_le` avec le statut, jamais l'un sans l'autre** : le CHECK
    `courrier_cloture_coherente` du socle impose l'equivalence, et un
    `update(statut_courrier=...)` seul echoue en `IntegrityError`. C'est le
    moteur qui tient la regle, et il a raison — un courrier clos sans date de
    cloture ne se date pas dans la fiche de vie.
    """
    Courrier.objects.filter(pk=identifiant).update(
        statut_courrier=STATUT_CLOTURE, cloture_le=timezone.now()
    )


# =====================================================================
#  Le portefeuille — la corbeille et non le registre
# =====================================================================


def test_le_portefeuille_ne_montre_que_ce_qui_est_affecte(connecte, affecte):
    """
    **La distinction qui fait tout l'ecran.** Un directeur lit des dizaines de
    courriers et en a une poignee sur les bras ; melanger les deux aurait fait de
    C-01 un registre de plus, et l'agent aurait cherche ses dossiers dedans.
    """
    identifiant, agent = affecte

    session = connecte(agent.identifiant_annuaire)
    portefeuille = session.get(f"{SUIVI}/portefeuille").json()
    numeros = [dossier["numero"] for dossier in portefeuille["dossiers"]]

    assert Courrier.objects.get(pk=identifiant).numero in numeros
    # Le meme agent voit bien plus de courriers qu'il n'en detient.
    visibles = session.get(f"{COURRIERS}?vue=tous").json()["total"]
    assert len(portefeuille["dossiers"]) <= visibles


def test_le_portefeuille_d_un_agent_non_affecte_est_vide(connecte, affecte):
    """
    Un agent qui n'a rien recu voit une corbeille vide — et non le registre de sa
    structure. L'ecran ecrit alors « aucun dossier », ce qui est un fait.
    """
    connecte("agent.scc")
    portefeuille = connecte("agent.scc").get(f"{SUIVI}/portefeuille").json()

    assert portefeuille["dossiers"] == []
    assert portefeuille["aRendre"] == 0


def test_un_dossier_clos_sort_du_portefeuille(connecte, affecte):
    """
    La corbeille dit ce qu'il reste a faire. Un dossier clos qui y resterait
    ferait grossir le compte « à rendre » sans que rien ne soit a rendre.
    """
    identifiant, agent = affecte
    _clore(identifiant)

    portefeuille = connecte(agent.identifiant_annuaire).get(f"{SUIVI}/portefeuille").json()

    assert all(dossier["id"] != identifiant for dossier in portefeuille["dossiers"])


# =====================================================================
#  Le dossier
# =====================================================================


def test_le_dossier_porte_l_instruction_et_son_auteur(connecte, affecte):
    """
    « Traiter en urgence » n'a pas le meme poids selon qu'il vient du chef de
    service ou du Directeur general : l'auteur est porte avec le texte, et
    l'ecran le met en tete.
    """
    identifiant, agent = affecte

    dossier = connecte(agent.identifiant_annuaire).get(f"{SUIVI}/dossiers/{identifiant}").json()

    assert dossier["instruction"] is not None
    assert "bon de commande" in dossier["instruction"]["texte"]
    assert dossier["instruction"]["auteur"] == compte("dir.dsi").nom_complet
    assert dossier["instruction"]["initiales"]


def test_un_dossier_hors_perimetre_repond_404(connecte, affecte):
    """
    404 et jamais 403 : repondre « interdit » confirmerait l'existence du
    courrier a qui n'a pas a la connaitre. Decision D5, comme la fiche.
    """
    identifiant, _ = affecte

    reponse = connecte("dir.daf").get(f"{SUIVI}/dossiers/{identifiant}")

    assert reponse.status_code == 404


def test_le_responsable_lit_le_dossier_sans_pouvoir_agir(connecte, affecte):
    """
    Un responsable ouvre le dossier de son agent — c'est ainsi qu'il sait ou en
    est le travail avant de relancer. Mais il n'y agit pas a sa place :
    `actionsPossibles` est vide, et l'ecran n'affiche donc aucun bouton.
    """
    identifiant, agent = affecte
    if agent.identifiant_annuaire == "dir.dsi":
        pytest.skip("La DSI n'a qu'un compte : l'agent et le responsable se confondent.")

    dossier = connecte("dir.dsi").get(f"{SUIVI}/dossiers/{identifiant}").json()

    assert dossier["actionsPossibles"] == []


def test_les_actions_viennent_du_serveur(connecte, affecte):
    """
    Un bouton propose puis refuse a l'envoi est la panne la plus commune de cet
    ecran. Le serveur dit ce qu'il accepte, le front ne le devine pas.
    """
    identifiant, agent = affecte

    dossier = connecte(agent.identifiant_annuaire).get(f"{SUIVI}/dossiers/{identifiant}").json()

    assert "traiter" in dossier["actionsPossibles"]
    assert "demanderDelai" in dossier["actionsPossibles"]


def test_un_dossier_clos_n_offre_plus_d_action(connecte, affecte):
    identifiant, agent = affecte
    _clore(identifiant)

    dossier = connecte(agent.identifiant_annuaire).get(f"{SUIVI}/dossiers/{identifiant}").json()

    assert dossier["actionsPossibles"] == []


# =====================================================================
#  Les etapes — une liste de courses, pas un circuit
# =====================================================================


def test_l_etape_ajoutee_revient_dans_le_dossier(connecte, affecte):
    identifiant, agent = affecte
    session = connecte(agent.identifiant_annuaire)

    session.post(
        f"{SUIVI}/dossiers/{identifiant}/taches",
        {"libelle": "Rapprocher du bon de commande"},
        content_type="application/json",
    )

    taches = session.get(f"{SUIVI}/dossiers/{identifiant}").json()["taches"]
    assert [tache["libelle"] for tache in taches] == ["Rapprocher du bon de commande"]
    assert taches[0]["faite"] is False


def test_une_etape_se_decoche(connecte, affecte):
    """
    Decocher est permis : une case cochee par erreur se corrige. Ce n'est pas une
    trace opposable, c'est un pense-bete — et un pense-bete qu'on ne peut pas
    corriger cesse d'etre tenu.
    """
    identifiant, agent = affecte
    session = connecte(agent.identifiant_annuaire)
    tache = session.post(
        f"{SUIVI}/dossiers/{identifiant}/taches",
        {"libelle": "Accuser réception"},
        content_type="application/json",
    ).json()

    session.patch(
        f"{SUIVI}/dossiers/{identifiant}/taches/{tache['id']}",
        {"faite": True},
        content_type="application/json",
    )
    session.patch(
        f"{SUIVI}/dossiers/{identifiant}/taches/{tache['id']}",
        {"faite": False},
        content_type="application/json",
    )

    lue = session.get(f"{SUIVI}/dossiers/{identifiant}").json()["taches"][0]
    assert lue["faite"] is False
    assert lue["faiteLe"] is None


def test_la_liste_d_etapes_appartient_a_son_auteur(connecte, affecte):
    """
    Deux agents affectes au meme dossier tiennent **deux** listes. Une liste
    partagee serait un circuit qui ne dit pas son nom — et le circuit du courrier
    ne se decide pas dans une case a cocher.
    """
    identifiant, agent = affecte
    connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/taches",
        {"libelle": "Ma propre étape"},
        content_type="application/json",
    )

    autre = connecte("dg").get(f"{SUIVI}/dossiers/{identifiant}").json()

    assert autre["taches"] == []


def test_on_ne_coche_pas_l_etape_d_un_autre(connecte, affecte):
    identifiant, agent = affecte
    tache = (
        connecte(agent.identifiant_annuaire)
        .post(
            f"{SUIVI}/dossiers/{identifiant}/taches",
            {"libelle": "Ma propre étape"},
            content_type="application/json",
        )
        .json()
    )

    reponse = connecte("dg").patch(
        f"{SUIVI}/dossiers/{identifiant}/taches/{tache['id']}",
        {"faite": True},
        content_type="application/json",
    )

    assert reponse.status_code == 404


# =====================================================================
#  Les notes — la seule confidentialite propre au pilier
# =====================================================================


def test_une_note_privee_ne_sort_pas_de_la_hierarchie(connecte, affecte):
    """
    **L'echec ici ne provoque aucune erreur** : juste un texte de travail lu par
    qui ne devait pas. C'est ce que l'ecran promet en toutes lettres — « Note
    privée · visible par ma hiérarchie ».
    """
    identifiant, agent = affecte
    connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/notes",
        {"texte": "L'expéditeur a téléphoné : le dossier est monté au cabinet.", "privee": True},
        content_type="application/json",
    )

    # `agent.scc` voit le courrier par sa session de bureau d'ordre, mais ne
    # couvre pas la structure de l'auteur.
    lues = connecte("agent.scc").get(f"{SUIVI}/dossiers/{identifiant}").json()["notes"]

    assert lues == []


def test_une_note_ouverte_se_lit_par_tout_lecteur(connecte, affecte):
    identifiant, agent = affecte
    connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/notes",
        {"texte": "Pièces complémentaires demandées à la DAMP.", "privee": False},
        content_type="application/json",
    )

    lues = connecte("agent.scc").get(f"{SUIVI}/dossiers/{identifiant}").json()["notes"]

    assert [note["texte"] for note in lues] == ["Pièces complémentaires demandées à la DAMP."]


def test_une_note_est_privee_par_defaut(connecte, affecte):
    """Le doute profite a la discretion : l'agent qui veut ecrire a tous decoche,
    et il le fait sciemment."""
    identifiant, agent = affecte
    connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/notes",
        {"texte": "À vérifier avec la DAJ."},
        content_type="application/json",
    )

    assert NoteTraitement.objects.get(courrier_id=identifiant).privee is True


def test_une_note_vide_est_refusee(connecte, affecte):
    identifiant, agent = affecte

    reponse = connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/notes",
        {"texte": "   "},
        content_type="application/json",
    )

    assert reponse.status_code == 409


# =====================================================================
#  La demande de delai — demander n'est pas accorder
# =====================================================================


def test_une_demande_de_delai_ne_deplace_pas_l_echeance(connecte, affecte):
    """
    **Le point de tout le geste.** La demande trace et previent ; l'echeance ne
    bouge qu'a la decision. L'inverse ferait du report un droit que l'on
    s'accorde, et le delai cesserait de vouloir dire quelque chose.
    """
    identifiant, agent = affecte
    avant = Courrier.objects.get(pk=identifiant).date_limite

    connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/demandes-delai",
        {"joursDemandes": 5, "motif": "Pièces techniques non parvenues de la DAMP."},
        content_type="application/json",
    )

    assert Courrier.objects.get(pk=identifiant).date_limite == avant
    assert DemandeDelai.objects.get(courrier_id=identifiant).etat == DEMANDE_EN_ATTENTE


def test_une_seule_demande_en_attente_a_la_fois(connecte, affecte):
    """Redemander n'est pas relancer : la seconde demande est refusee tant que la
    premiere n'est pas tranchee."""
    identifiant, agent = affecte
    session = connecte(agent.identifiant_annuaire)
    corps = {"joursDemandes": 5, "motif": "Pièces techniques non parvenues."}

    session.post(
        f"{SUIVI}/dossiers/{identifiant}/demandes-delai", corps, content_type="application/json"
    )
    seconde = session.post(
        f"{SUIVI}/dossiers/{identifiant}/demandes-delai", corps, content_type="application/json"
    )

    assert seconde.status_code == 409
    assert DemandeDelai.objects.filter(courrier_id=identifiant).count() == 1


def test_une_demande_sans_motif_est_refusee(connecte, affecte):
    identifiant, agent = affecte

    reponse = connecte(agent.identifiant_annuaire).post(
        f"{SUIVI}/dossiers/{identifiant}/demandes-delai",
        {"joursDemandes": 5, "motif": ""},
        content_type="application/json",
    )

    assert reponse.status_code == 409


def test_accorder_prolonge_reellement_le_courrier(connecte, affecte):
    """
    Accorder appelle `prolonger()` et non une ecriture directe : deux chemins
    vers `date_limite` auraient fini par diverger, et l'un d'eux aurait oublie
    `delai_reglementaire_jours` — la jauge de la fiche aurait alors menti.
    """
    identifiant, agent = affecte
    if agent.identifiant_annuaire == "dir.dsi":
        pytest.skip("La DSI n'a qu'un compte : on ne s'accorde pas son propre report.")

    avant = Courrier.objects.get(pk=identifiant)
    demande = (
        connecte(agent.identifiant_annuaire)
        .post(
            f"{SUIVI}/dossiers/{identifiant}/demandes-delai",
            {"joursDemandes": 5, "motif": "Pièces techniques non parvenues."},
            content_type="application/json",
        )
        .json()
    )

    connecte("dir.dsi").post(
        f"{SUIVI}/demandes-delai/{demande['id']}",
        {"accordee": True, "reponse": "Accordé, sans nouveau report."},
        content_type="application/json",
    )

    apres = Courrier.objects.get(pk=identifiant)
    assert apres.date_limite > avant.date_limite
    assert apres.delai_reglementaire_jours > avant.delai_reglementaire_jours
    assert DemandeDelai.objects.get(pk=demande["id"]).etat == DEMANDE_ACCORDEE


def test_on_ne_s_accorde_pas_son_propre_report(connecte, affecte):
    """
    Un directeur cote, s'affecte et demande : sans cette garde, il signerait sa
    propre prolongation, et le report ne serait plus une decision.
    """
    identifiant, _ = affecte
    session = connecte("dir.dsi")
    session.post(
        f"{COURRIERS}/{identifiant}/affectations",
        {
            "structureId": Structure.objects.get(code="DSI-ET").pk,
            "utilisateurId": compte("dir.dsi").pk,
            "consigne": "Je traite moi-même.",
        },
        content_type="application/json",
    )
    demande = session.post(
        f"{SUIVI}/dossiers/{identifiant}/demandes-delai",
        {"joursDemandes": 5, "motif": "Dossier technique lourd."},
        content_type="application/json",
    ).json()

    reponse = session.post(
        f"{SUIVI}/demandes-delai/{demande['id']}",
        {"accordee": True, "reponse": ""},
        content_type="application/json",
    )

    assert reponse.status_code == 409


def test_un_refus_se_motive(connecte, affecte):
    identifiant, agent = affecte
    if agent.identifiant_annuaire == "dir.dsi":
        pytest.skip("La DSI n'a qu'un compte.")

    demande = (
        connecte(agent.identifiant_annuaire)
        .post(
            f"{SUIVI}/dossiers/{identifiant}/demandes-delai",
            {"joursDemandes": 5, "motif": "Pièces non parvenues."},
            content_type="application/json",
        )
        .json()
    )

    reponse = connecte("dir.dsi").post(
        f"{SUIVI}/demandes-delai/{demande['id']}",
        {"accordee": False, "reponse": ""},
        content_type="application/json",
    )

    assert reponse.status_code == 409


# =====================================================================
#  La recherche avancee
# =====================================================================


def test_la_recherche_ne_sort_pas_du_perimetre(connecte, affecte):
    """
    **Le test qui compte.** Une recherche est une porte derobee sur le registre :
    l'agent y ecrit ce qu'il veut, et rien dans le formulaire ne rappelle le
    cloisonnement. La borne est posee par `visibles()`, en amont de tout filtre.
    """
    identifiant, _ = affecte

    trouves = (
        connecte("dir.daf")
        .post(
            f"{SUIVI}/recherche",
            {"motsCles": "quai"},
            content_type="application/json",
        )
        .json()
    )

    assert all(ligne["id"] != identifiant for ligne in trouves["lignes"])


def test_les_criteres_se_cumulent(connecte, affecte):
    """
    Mots-cles **et** periode **et** nature : c'est ce qu'un formulaire a dix
    champs laisse attendre. Une periode qui ne recouvre pas la reception vide
    donc le resultat, meme si les mots-cles correspondent.
    """
    identifiant, agent = affecte
    session = connecte(agent.identifiant_annuaire)

    hier = (date.today() - timedelta(days=1)).isoformat()
    trouves = session.post(
        f"{SUIVI}/recherche",
        {"motsCles": "quai", "du": "2019-01-01", "au": hier},
        content_type="application/json",
    ).json()

    assert all(ligne["id"] != identifiant for ligne in trouves["lignes"])


def test_un_formulaire_vide_rend_le_registre(connecte, affecte):
    """« Cherche tout » est une question legitime, et la reponse est le registre
    visible — plafonne, jamais vide."""
    _, agent = affecte

    trouves = (
        connecte(agent.identifiant_annuaire)
        .post(f"{SUIVI}/recherche", {}, content_type="application/json")
        .json()
    )

    assert trouves["total"] > 0


def test_le_total_precede_le_plafond(connecte, affecte):
    """L'agent doit savoir que sa recherche rend plus que ce qu'il lit : le total
    est compte avant le plafonnement de la liste."""
    _, agent = affecte

    trouves = (
        connecte(agent.identifiant_annuaire)
        .post(f"{SUIVI}/recherche", {}, content_type="application/json")
        .json()
    )

    assert trouves["total"] >= len(trouves["lignes"])


def test_une_recherche_enregistree_recompte_a_chaque_lecture(connecte, affecte):
    """
    Le nombre n'est pas stocke : une recherche enregistree est une **question**,
    pas une reponse. « Les courriers hors délai de la DAF » n'a pas le meme
    compte lundi et vendredi, et c'est ce que l'agent revient voir.
    """
    _, agent = affecte
    session = connecte(agent.identifiant_annuaire)

    session.post(
        f"{SUIVI}/recherches",
        {"libelle": "Tout mon registre", "criteres": {}},
        content_type="application/json",
    )
    avant = session.get(f"{SUIVI}/recherches").json()[0]["nombre"]

    # Un courrier retire du registre, choisi parmi ceux que la recherche rend :
    # invalider un courrier invisible n'aurait rien prouve.
    tout = session.post(f"{SUIVI}/recherche", {}, content_type="application/json").json()
    lignes = tout["lignes"]
    Courrier.objects.filter(pk=lignes[0]["id"]).update(invalide_le=timezone.now())

    apres = session.get(f"{SUIVI}/recherches").json()[0]["nombre"]

    assert apres == avant - 1


def test_le_meme_nom_ecrase_les_criteres(connecte, affecte):
    """L'agent qui affine sa recherche et la resauvegarde du meme nom veut la
    remplacer, pas lire un message d'erreur."""
    _, agent = affecte
    session = connecte(agent.identifiant_annuaire)

    session.post(
        f"{SUIVI}/recherches",
        {"libelle": "Mes urgences", "criteres": {"motsCles": "quai"}},
        content_type="application/json",
    )
    session.post(
        f"{SUIVI}/recherches",
        {"libelle": "Mes urgences", "criteres": {"motsCles": "facture"}},
        content_type="application/json",
    )

    conservees = session.get(f"{SUIVI}/recherches").json()
    assert len(conservees) == 1
    assert conservees[0]["criteres"]["motsCles"] == "facture"


def test_on_n_oublie_pas_la_recherche_d_un_autre(connecte, affecte):
    _, agent = affecte
    conservee = (
        connecte(agent.identifiant_annuaire)
        .post(
            f"{SUIVI}/recherches",
            {"libelle": "Mes urgences", "criteres": {}},
            content_type="application/json",
        )
        .json()
    )

    reponse = connecte("dg").delete(f"{SUIVI}/recherches/{conservee['id']}")

    assert reponse.status_code == 404

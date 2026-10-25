"""
Le pilier activites, par ses routes.

Comme pour l'habilitation, ces tests verifient d'abord ce que les routes
**refusent** : une lecture qui laisse passer ne provoque aucune erreur, elle
montre a un agent le plan du voisin.

Le jeu d'essai fournit la dissymetrie necessaire. `focal.dsi` et `focal.daf`
portent le meme profil et la meme portee sur deux structures differentes : c'est
la seule facon de verifier le cloisonnement. `dsr` n'est bornee par rien.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from activite.modeles import Activite, AxeStrategique, Exercice, PlanActions, Tache
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.journal.modeles import Evenement
from noyau.organisation.modeles import Structure
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
AXE = "Port attractif et performant"


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


def _plan(sigle: str) -> PlanActions:
    structure = Structure.objects.get(code=sigle)
    exercice = Exercice.objects.get(ouvert=True)
    plan, _ = PlanActions.objects.get_or_create(structure=structure, exercice=exercice)
    return plan


def _activite(sigle: str, intitule: str, responsable: str = "agent.dsi", **surcharges) -> Activite:
    activite = Activite.objects.create(
        plan=_plan(sigle),
        axe_strategique=AxeStrategique.objects.get(code="A1"),
        intitule=intitule,
        responsable=compte(responsable),
        date_debut=surcharges.pop("date_debut", date(2026, 1, 1)),
        date_fin=surcharges.pop("date_fin", date(2026, 12, 31)),
        **surcharges,
    )
    activite.refresh_from_db()
    return activite


def _tache_unique(debut: str, fin: str) -> list[dict]:
    """RG-1 et RG-3 : la plus petite liste valide, une tache a 100 points."""
    return [{"libelle": "Execution", "valeurPrevue": 100, "moisDebut": debut, "moisFin": fin}]


def _tache(activite: Activite, intitule: str = "Execution", prevue=100, **surcharges) -> Tache:
    """
    Une tache posee par l'ORM, sur l'annee 2026 par defaut.

    Sous acteur : une valeur obtenue non nulle fait recalculer l'activite, et
    le declencheur d'historisation refuserait par ricochet.
    """
    with acteur(compte("focal.dsi")):
        return Tache.objects.create(
            activite=activite,
            intitule=intitule,
            valeur_prevue=prevue,
            date_debut=surcharges.pop("date_debut", date(2026, 1, 1)),
            date_fin=surcharges.pop("date_fin", date(2026, 12, 31)),
            **surcharges,
        )


def _declarer(client, activite: Activite, tache: Tache, valeur, observation="Travaux engages."):
    return client.post(
        f"/api/activites/{activite.pk}/avancement",
        data={"tacheId": tache.pk, "valeurObtenue": valeur, "observation": observation},
        content_type="application/json",
    )


def _recalibrer(client, activite: Activite, tache: Tache, valeur, motif="Aucune piece a l'appui."):
    return client.post(
        f"/api/activites/{activite.pk}/recalibrage",
        data={"tacheId": tache.pk, "valeur": valeur, "motif": motif},
        content_type="application/json",
    )


# =====================================================================
#  Ce que la garde refuse
# =====================================================================


def test_sans_session_le_registre_est_refuse(client, jeu):
    assert client.get("/api/activites").status_code == 401


def test_sans_act_lec_le_registre_est_refuse(connecte):
    """`agent.dsi` porte le profil Collaborateur, sans permission d'activite."""
    assert connecte("agent.dsi").get("/api/activites").status_code == 401


def test_la_corbeille_des_plans_exige_act_val(connecte):
    """Un point focal soumet son plan ; il ne valide pas ceux des autres."""
    assert connecte("focal.dsi").get("/api/activites/plans?annee=2026").status_code == 401
    assert connecte("dcg").get("/api/activites/plans?annee=2026").status_code == 200


# =====================================================================
#  Le cloisonnement
# =====================================================================


def test_un_point_focal_ne_voit_pas_le_plan_du_voisin(connecte):
    """
    Le test le plus important du pilier. Deux points focaux, meme profil, meme
    portee, deux structures : chacun ne voit que la sienne.
    """
    _activite("DSI", "Refonte du reseau")
    _activite("DAF", "Cloture comptable", responsable="focal.daf")

    vues_dsi = connecte("focal.dsi").get("/api/activites").json()
    assert [a["intitule"] for a in vues_dsi["activites"]] == ["Refonte du reseau"]

    vues_daf = connecte("focal.daf").get("/api/activites").json()
    assert [a["intitule"] for a in vues_daf["activites"]] == ["Cloture comptable"]


def test_la_dsr_voit_les_deux(connecte):
    """Portee `toutes` : la consolidation du §3.3 n'aurait pas de sens sinon."""
    _activite("DSI", "Refonte du reseau")
    _activite("DAF", "Cloture comptable", responsable="focal.daf")

    registre = connecte("dsr").get("/api/activites").json()
    assert registre["total"] == 2
    assert set(registre["structures"]) == {"DSI", "DAF"}


def test_une_activite_hors_perimetre_sort_en_404_et_non_403(connecte):
    """403 confirmerait l'existence de l'activite — decision D5."""
    autre = _activite("DAF", "Cloture comptable", responsable="focal.daf")
    assert connecte("focal.dsi").get(f"/api/activites/{autre.pk}").status_code == 404


def test_on_ne_modifie_pas_ce_que_l_on_ne_peut_pas_lire(connecte):
    """
    Le perimetre borne l'ecriture comme la lecture. Une route d'ecriture qui
    chargerait l'objet sans passer par le perimetre ouvrirait une faille
    complete et silencieuse.
    """
    autre = _activite("DAF", "Cloture comptable", responsable="focal.daf")
    tache = _tache(autre)
    reponse = _declarer(connecte("focal.dsi"), autre, tache, 90)
    assert reponse.status_code == 404
    autre.refresh_from_db()
    assert autre.avancement_calcule == 0


def test_le_selecteur_de_structures_ne_revele_pas_l_organigramme(connecte):
    """`structures` peuple un filtre : il ne doit montrer que le perimetre."""
    _activite("DSI", "Refonte du reseau")
    _activite("DAF", "Cloture comptable", responsable="focal.daf")
    assert connecte("focal.dsi").get("/api/activites").json()["structures"] == ["DSI"]


# =====================================================================
#  L'etat affiche
# =====================================================================


def test_le_registre_applique_l_arbitrage_n_2(connecte):
    """
    A2. Une activite peu avancee mais dont l'echeance n'est pas passee est « En
    cours », pas « En retard » — quelle que soit sa distance a l'attendu.
    """
    hier = date.today() - timedelta(days=1)
    _activite("DSI", "Echue", date_debut=date(2026, 1, 1), date_fin=hier)
    _activite("DSI", "A temps", date_debut=date(2026, 1, 1), date_fin=date(2030, 1, 1))

    etats = {
        a["intitule"]: a["etat"]
        for a in connecte("focal.dsi").get("/api/activites").json()["activites"]
    }
    assert etats == {"Echue": "En retard", "A temps": "En cours"}


def test_la_criticite_demande_une_contrainte_echue(connecte):
    """§20. Le retard seul ne suffit pas."""
    hier = date.today() - timedelta(days=1)
    activite = _activite("DSI", "Echue", date_debut=date(2026, 1, 1), date_fin=hier)

    lignes = connecte("focal.dsi").get("/api/activites").json()["activites"]
    assert lignes[0]["etat"] == "En retard" and lignes[0]["critique"] is False

    # Une tache dont le dernier mois est clos sans qu'elle ait obtenu sa part :
    # la fin de sa periode tient lieu d'echeance (ADR 049).
    fin_du_mois_dernier = date.today().replace(day=1) - timedelta(days=1)
    _tache(
        activite,
        "Recette",
        date_debut=fin_du_mois_dernier.replace(day=1),
        date_fin=fin_du_mois_dernier,
    )

    lignes = connecte("focal.dsi").get("/api/activites").json()["activites"]
    assert lignes[0]["critique"] is True


# =====================================================================
#  Ecritures de la structure
# =====================================================================


def test_creer_une_activite_lui_donne_sa_reference_et_sa_trace(connecte):
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "objectif": "Fiabiliser",
            "etatReferenceGeneral": "",
            "resultatsAttendus": "",
            "debut": "2026-01-01",
            "fin": "2026-12-31",
            "budgetValide": None,
            "responsableId": compte("agent.dsi").pk,
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 200
    activite = Activite.objects.get(pk=reponse.json()["id"])
    assert activite.code == "PAA-DSI-01"
    assert activite.plan.structure.code == "DSI"
    assert Evenement.objects.filter(
        objet_type="activite", objet_id=activite.pk, type_evenement="activite_creee"
    ).exists()


# =====================================================================
#  Les taches saisies a la creation — ADR 049, RG-1 a RG-3, RG-8, RG-9
# =====================================================================


def _creation(client, taches, debut="2026-03", fin="2026-11"):
    return client.post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": debut,
            "fin": fin,
            "responsableId": None,
            "taches": taches,
        },
        content_type="application/json",
    )


def test_les_taches_se_creent_avec_l_activite(connecte):
    """RG-1. Les taches sont saisies avec l'activite, dans l'ordre soumis."""
    reponse = _creation(
        connecte("focal.dsi"),
        [
            {"libelle": "Etude", "valeurPrevue": 30, "moisDebut": "2026-03", "moisFin": "2026-04"},
            {
                "libelle": "Deploiement",
                "valeurPrevue": 70,
                "moisDebut": "2026-05",
                "moisFin": "2026-11",
            },
        ],
    )
    assert reponse.status_code == 200

    taches = list(Tache.objects.filter(activite_id=reponse.json()["id"]).order_by("ordre"))
    assert [(t.intitule, t.valeur_prevue) for t in taches] == [("Etude", 30), ("Deploiement", 70)]
    # RG-8 : des mois entiers.
    assert (taches[0].date_debut, taches[0].date_fin) == (date(2026, 3, 1), date(2026, 4, 30))
    assert taches[0].responsable_id is None  # ADR 048


def test_une_activite_sans_tache_est_refusee(connecte):
    """RG-1. Et rien n'est cree : le controle precede la premiere ecriture."""
    reponse = _creation(connecte("focal.dsi"), [])
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "taches_absentes"
    assert not Activite.objects.exists()


@pytest.mark.parametrize("parts", [[30, 60], [50, 50.01], [100, 0.5]])
def test_la_somme_des_valeurs_prevues_doit_faire_exactement_100(connecte, parts):
    """RG-3, au centieme pres, ni plus ni moins."""
    taches = [
        {"libelle": f"T{i}", "valeurPrevue": v, "moisDebut": "2026-03", "moisFin": "2026-11"}
        for i, v in enumerate(parts)
    ]
    reponse = _creation(connecte("focal.dsi"), taches)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "somme_taches"
    assert not Activite.objects.exists()


def test_trois_tiers_au_centieme_font_100(connecte):
    """`Decimal(str(...))` : la somme de 33,33 + 33,33 + 33,34 tombe juste."""
    taches = [
        {"libelle": f"T{i}", "valeurPrevue": v, "moisDebut": "2026-03", "moisFin": "2026-11"}
        for i, v in enumerate([33.33, 33.33, 33.34])
    ]
    assert _creation(connecte("focal.dsi"), taches).status_code == 200


def test_une_valeur_prevue_nulle_est_refusee(connecte):
    """RG-2, au-dela de la lettre : une tache de valeur nulle ne se realise jamais."""
    taches = [
        {"libelle": "Vide", "valeurPrevue": 0, "moisDebut": "2026-03", "moisFin": "2026-11"},
        {"libelle": "Tout", "valeurPrevue": 100, "moisDebut": "2026-03", "moisFin": "2026-11"},
    ]
    reponse = _creation(connecte("focal.dsi"), taches)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "valeur_prevue_hors_borne"


def test_une_tache_hors_de_la_periode_de_l_activite_est_refusee(connecte):
    """RG-9. L'activite court de mars a novembre ; une tache de decembre en sort."""
    taches = [
        {"libelle": "Bilan", "valeurPrevue": 100, "moisDebut": "2026-10", "moisFin": "2026-12"}
    ]
    reponse = _creation(connecte("focal.dsi"), taches)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "tache_hors_periode"


def test_une_tache_se_saisit_au_mois_sans_quantieme(connecte):
    """RG-8. `2026-03-15` n'est pas un mois."""
    taches = [
        {"libelle": "Etude", "valeurPrevue": 100, "moisDebut": "2026-03-15", "moisFin": "2026-11"}
    ]
    reponse = _creation(connecte("focal.dsi"), taches)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "mois_invalide"


def test_un_axe_inconnu_est_refuse(connecte):
    """Referentiel ferme : trois axes, jamais de saisie libre."""
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Essai",
            "axe": "Digitalisation",
            "debut": "2026-01-01",
            "fin": "2026-12-31",
            "responsableId": compte("agent.dsi").pk,
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert "inconnu" in reponse.json()["message"]


def test_l_avancement_se_declare_sur_une_tache_et_se_somme(connecte):
    """
    RG-4, RG-5, RG-7. Une tache prevue a 30 et declaree a 15 apporte 15 points
    a l'activite, sans conversion ; l'activite est la somme brute.
    """
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 30)
    deploiement = _tache(activite, "Deploiement", 70)
    client = connecte("focal.dsi")

    assert _declarer(client, activite, etude, 15).status_code == 200
    assert _declarer(client, activite, deploiement, 35).status_code == 200

    activite.refresh_from_db()
    assert activite.avancement_calcule == 50
    evenement = Evenement.objects.filter(
        objet_id=activite.pk, type_evenement="avancement_declare"
    ).latest("pk")  # `survenu_le` est l'horodatage de la transaction : identique
    assert evenement.donnees["tache"] == deploiement.pk
    assert evenement.donnees["avancement"] == 50

    fiche = client.get(f"/api/activites/{activite.pk}").json()
    assert fiche["avancement"] == 50
    etude_lue = next(t for t in fiche["taches"] if t["id"] == etude.pk)
    assert (etude_lue["valeurPrevue"], etude_lue["valeurObtenue"]) == (30, 15)
    assert etude_lue["avancementPropre"] == 50  # point 2 : obtenue / prevue
    assert etude_lue["fait"] is False


def test_la_declaration_est_cumulative(connecte):
    """
    Point 1 : la valeur declaree **remplace** la precedente, comme le faisait
    l'avancement de l'activite. Deux declarations a 20 font 20, pas 40.
    """
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite, "Etude", 60)
    client = connecte("focal.dsi")

    _declarer(client, activite, tache, 20)
    _declarer(client, activite, tache, 20)
    tache.refresh_from_db()
    assert tache.valeur_obtenue == 20

    # Et elle peut redescendre : une declaration trop optimiste se corrige.
    _declarer(client, activite, tache, 10, observation="Lot 2 refuse a la recette.")
    activite.refresh_from_db()
    assert activite.avancement_calcule == 10


def test_la_valeur_obtenue_est_plafonnee_par_la_valeur_prevue(connecte):
    """RG-6. Le refus nomme la tache et sa part."""
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite, "Etude", 30)
    reponse = _declarer(connecte("focal.dsi"), activite, tache, 31)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "valeur_obtenue_hors_borne"
    assert "Etude" in reponse.json()["message"]


def test_une_tache_realisee_porte_sa_date(connecte):
    """Atteindre sa part rend la tache faite, et la date se pose d'elle-meme."""
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite, "Etude", 30)
    _declarer(connecte("focal.dsi"), activite, tache, 30)

    fiche = connecte("focal.dsi").get(f"/api/activites/{activite.pk}").json()
    assert fiche["taches"][0]["fait"] is True
    assert fiche["taches"][0]["dateRealisation"] == date.today().isoformat()
    assert fiche["tachesFaites"] == 1


def test_on_ne_declare_pas_sur_la_tache_d_une_autre_activite(connecte):
    """La tache doit appartenir a l'activite de l'URL : sinon 404, comme D5."""
    activite = _activite("DSI", "Refonte du reseau")
    autre = _activite("DSI", "Migration des postes")
    tache = _tache(autre, "Etude", 100)
    assert _declarer(connecte("focal.dsi"), activite, tache, 10).status_code == 404


def test_l_ancien_contrat_de_declaration_est_refuse(connecte):
    """
    Point 4 : plus de saisie directe sur l'activite. Un front reste en arriere
    qui enverrait `avancement` est refuse par le schema, pas ignore — ignorer
    laisserait croire a l'agent que sa declaration est passee.
    """
    activite = _activite("DSI", "Refonte du reseau")
    _tache(activite)
    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}/avancement",
        data={"avancement": 40, "observation": "Deux lots.", "tachesFaites": []},
        content_type="application/json",
    )
    assert reponse.status_code == 422


def test_declarer_un_avancement_ne_cree_aucune_piece_jointe(connecte):
    """
    La déclaration portait un champ `pieces: [{nom, poids}]`, et le service en
    faisait des lignes de `piece_jointe` **sans binaire** — empreinte et chemin
    de stockage vides. L'onglet des pièces les listait comme les autres, et le
    clic tombait sur « le fichier est enregistré mais introuvable sur le volume »,
    qui accusait l'exploitation d'une perte n'ayant pas eu lieu.

    Le champ a disparu ; ce test empêche qu'il revienne. Les justificatifs
    passent par `POST /api/pieces`, qui lit le fichier et calcule son empreinte.
    """
    from noyau.pieces.modeles import PieceJointe

    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)

    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}/avancement",
        # Envoyé quand même : un client resté sur l'ancien contrat ne doit pas
        # pouvoir faire réapparaître ces lignes par la bande.
        data={
            "tacheId": tache.pk,
            "valeurObtenue": 40,
            "observation": "Rapport d'etape joint.",
            "pieces": [{"nom": "rapport.pdf", "poids": "1,2 Mo"}],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 200
    assert not PieceJointe.objects.filter(objet_type="activite", objet_id=activite.pk).exists()


def test_declarer_un_avancement_sur_une_activite_suspendue_sort_en_409(connecte):
    """
    §19, et la traduction du refus du moteur : laissee telle quelle, l'erreur
    PostgreSQL sortirait en 500 et n'apprendrait rien a l'agent.
    """
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)
    connecte("dg").post(
        f"/api/activites/{activite.pk}/suspension",
        data={"action": "suspendre", "motif": "Budget gele", "reference": None},
        content_type="application/json",
    )

    reponse = _declarer(connecte("focal.dsi"), activite, tache, 50, "Reprise partielle.")
    assert reponse.status_code == 409
    assert "suspendue" in reponse.json()["message"]


def test_un_indicateur_non_chiffrable_est_refuse(connecte):
    """Sans cible numerique, aucun taux d'atteinte n'est calculable — §16."""
    activite = _activite("DSI", "Refonte du reseau")
    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}/indicateurs",
        data={"libelle": "Satisfaction", "unite": "", "etatReference": "", "cible": "elevee"},
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  Gestes d'autorite
# =====================================================================


def test_une_structure_ne_se_suspend_pas_elle_meme(connecte):
    """§19 : la suspension releve de `DEC`, pas de `ACT_SAI`."""
    activite = _activite("DSI", "Refonte du reseau")
    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}/suspension",
        data={"action": "suspendre", "motif": "Essai", "reference": None},
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_une_structure_ne_rattache_pas_l_instruction_qui_la_contraint(connecte):
    """§17 : laisser la structure l'inscrire aurait vide l'article de son objet."""
    activite = _activite("DSI", "Refonte du reseau")
    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}/instructions",
        data={
            "origine": "Instruction verbale",
            "reference": None,
            "texte": "Accelerer",
            "responsableId": compte("agent.dsi").pk,
            "echeance": "2026-12-01",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_la_suspension_passe_par_la_table_et_jamais_par_l_etat(connecte):
    """
    Le code applicatif n'ecrit pas `etat = 'suspendue'` : il inscrit la
    suspension, et l'etat suit par declencheur.
    """
    activite = _activite("DSI", "Refonte du reseau")
    reponse = connecte("dg").post(
        f"/api/activites/{activite.pk}/suspension",
        data={"action": "suspendre", "motif": "Budget gele", "reference": None},
        content_type="application/json",
    )
    assert reponse.status_code == 200
    activite.refresh_from_db()
    assert activite.etat == Activite.SUSPENDUE
    assert activite.suspensions.filter(repris_le__isnull=True).exists()


def test_on_ne_suspend_pas_deux_fois(connecte):
    activite = _activite("DSI", "Refonte du reseau")
    corps = {"action": "suspendre", "motif": "Budget gele", "reference": None}
    client = connecte("dg")
    client.post(
        f"/api/activites/{activite.pk}/suspension", data=corps, content_type="application/json"
    )
    reponse = client.post(
        f"/api/activites/{activite.pk}/suspension", data=corps, content_type="application/json"
    )
    assert reponse.status_code == 409


def test_un_directeur_ne_relance_pas_sa_propre_structure(connecte):
    """
    La relance est une escalade — descriptif §1.1.

    La garde ne porte plus sur le responsable nomme mais sur le **destinataire
    calcule** : la directrice de la DSI ne peut pas emettre la relance qui lui
    reviendrait. Le profil `RESP` ne porte pas `REL` — il ne l'obtient ici que
    pour eprouver la garde, et non dans la migration.
    """
    from noyau.habilitation.modeles import Permission, Profil, ProfilPermission

    ProfilPermission.objects.get_or_create(
        profil=Profil.objects.get(code="RESP"),
        permission=Permission.objects.get(code="REL"),
    )
    activite = _activite("DSI-ET", "Suivi", responsable="agent.dsi")
    reponse = connecte("dir.dsi").post(
        f"/api/activites/{activite.pk}/relance",
        data={"texte": "Merci d'avancer"},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "auto_relance"


def test_la_relance_manuelle_va_au_directeur_de_la_tete(connecte):
    """
    Une activite portee par DSI-ET et confiee a un agent se relance chez la
    directrice de la DSI, pas chez l'agent.
    """
    from django.db import connection

    activite = _activite("DSI-ET", "Suivi", responsable="agent.dsi")
    reponse = connecte("dsr").post(
        f"/api/activites/{activite.pk}/relance",
        data={"texte": "Merci d'avancer"},
        content_type="application/json",
    )
    assert reponse.status_code == 200

    with connection.cursor() as curseur:
        curseur.execute("SELECT destinataire_id FROM relance WHERE activite_id = %s", [activite.pk])
        assert [ligne[0] for ligne in curseur.fetchall()] == [compte("dir.dsi").pk]


def test_la_relance_automatique_va_au_directeur_de_la_tete(jeu):
    """
    L'escalade du §16 remonte a qui peut arbitrer : le directeur redescend en
    interne.
    """
    from django.db import connection

    from activite.taches import relancer_les_retards

    activite = _activite("DSI-ET", "Suivi", responsable="agent.dsi", date_fin=date(2026, 1, 10))

    relancer_les_retards(aujourd_hui="2026-03-01")

    with connection.cursor() as curseur:
        curseur.execute("SELECT destinataire_id FROM relance WHERE activite_id = %s", [activite.pk])
        assert [ligne[0] for ligne in curseur.fetchall()] == [compte("dir.dsi").pk]


def test_la_relance_n_est_pas_emise_sans_destinataire(jeu):
    """
    Aucun poste de tete pourvu jusqu'a la Direction generale : la relance ne
    part pas, et le journal dit pourquoi (A81).
    """
    from django.db import connection

    from activite.taches import relancer_les_retards

    for identifiant in ("dir.dsi", "dg"):
        agent = compte(identifiant)
        agent.poste = None
        agent.save(update_fields=["poste"])

    activite = _activite("DSI-ET", "Suivi", responsable="agent.dsi", date_fin=date(2026, 1, 10))

    relancer_les_retards(aujourd_hui="2026-03-01")

    with connection.cursor() as curseur:
        curseur.execute("SELECT count(*) FROM relance WHERE activite_id = %s", [activite.pk])
        assert curseur.fetchone()[0] == 0

    assert Evenement.objects.filter(
        objet_type="activite",
        objet_id=activite.pk,
        type_evenement="relance_sans_destinataire",
    ).exists()


def test_une_relance_laisse_sa_date_et_sa_trace(connecte):
    activite = _activite("DSI", "Refonte du reseau")
    reponse = connecte("dsr").post(
        f"/api/activites/{activite.pk}/relance",
        data={"texte": "Le plan attend votre declaration"},
        content_type="application/json",
    )
    assert reponse.status_code == 200
    activite.refresh_from_db()
    assert activite.derniere_relance_le is not None
    assert Evenement.objects.filter(objet_id=activite.pk, type_evenement="relance_emise").exists()


# =====================================================================
#  Le plan d'actions
# =====================================================================


def test_un_plan_vide_ne_se_soumet_pas(connecte):
    _plan("DSI")
    reponse = connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "soumettre", "motif": None},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_qui_soumet_ne_valide_pas(connecte):
    """§15 : la validation releve du controle de gestion, jamais du soumettant."""
    _activite("DSI", "Refonte du reseau")
    connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "soumettre", "motif": None},
        content_type="application/json",
    )
    reponse = connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "valider", "motif": None},
        content_type="application/json",
    )
    assert reponse.status_code == 403
    assert _plan("DSI").statut == PlanActions.SOUMIS


def test_le_controle_de_gestion_valide(connecte):
    _activite("DSI", "Refonte du reseau")
    connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "soumettre", "motif": None},
        content_type="application/json",
    )
    reponse = connecte("dcg").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "valider", "motif": None},
        content_type="application/json",
    )
    assert reponse.status_code == 200
    assert _plan("DSI").statut == PlanActions.VALIDE


def test_un_plan_retourne_sans_motif_est_refuse(connecte):
    """Un plan renvoye sans motif est resoumis a l'identique."""
    _activite("DSI", "Refonte du reseau")
    connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "soumettre", "motif": None},
        content_type="application/json",
    )
    reponse = connecte("dcg").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "retourner", "motif": None},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_un_plan_valide_n_accepte_plus_d_activite(connecte):
    """
    A5 : faute de mecanisme d'avenant, ajouter une activite a un plan valide
    reviendrait a modifier apres coup ce que la DCG a approuve.
    """
    _activite("DSI", "Refonte du reseau")
    connecte("focal.dsi").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "soumettre", "motif": None},
        content_type="application/json",
    )
    connecte("dcg").post(
        "/api/activites/plan/etat",
        data={"annee": 2026, "structureSigle": "DSI", "action": "valider", "motif": None},
        content_type="application/json",
    )
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Ajout tardif",
            "axe": AXE,
            "debut": "2026-01-01",
            "fin": "2026-12-31",
            "responsableId": compte("agent.dsi").pk,
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  La fiche
# =====================================================================


def test_la_fiche_porte_la_fiche_de_vie(connecte):
    """§18. Ce n'est pas une table : ce sont les evenements de l'objet."""
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-01-01",
            "fin": "2026-12-31",
            "responsableId": compte("agent.dsi").pk,
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    fiche = connecte("focal.dsi").get(f"/api/activites/{reponse.json()['id']}").json()
    assert [e["type"] for e in fiche["vie"]] == ["Création"]
    assert fiche["vie"][0]["auteur"] == compte("focal.dsi").nom_complet


def test_le_chemin_plan_n_est_pas_pris_pour_un_identifiant(connecte):
    """Une route variable declaree trop tot capturerait « plan »."""
    assert connecte("focal.dsi").get("/api/activites/plan?annee=2026").status_code == 200


# =====================================================================
#  Le redecoupage d'une activite — ADR 049
#
#  La liste soumise fait foi. RG-3 ne se controle que sur la liste
#  entiere : passer de 50/50 a 30/70 transite par une somme fausse.
# =====================================================================


def _redecouper(client, activite: Activite, taches: list[dict], motif="Nouveau decoupage."):
    return client.post(
        f"/api/activites/{activite.pk}/taches",
        data={"taches": taches, "motif": motif},
        content_type="application/json",
    )


def _ligne(tache: Tache | None, libelle: str, prevue, debut="2026-01", fin="2026-12") -> dict:
    ligne = {"libelle": libelle, "valeurPrevue": prevue, "moisDebut": debut, "moisFin": fin}
    if tache is not None:
        ligne["id"] = tache.pk
    return ligne


def test_redecouper_met_a_jour_cree_et_retire(connecte):
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 50)
    abandon = _tache(activite, "Abandonnee", 50)

    reponse = _redecouper(
        connecte("focal.dsi"),
        activite,
        [_ligne(etude, "Etude detaillee", 30), _ligne(None, "Deploiement", 70, "2026-06")],
    )
    assert reponse.status_code == 200

    en_vigueur = list(activite.taches.filter(invalide_le__isnull=True).order_by("ordre"))
    assert [(t.intitule, t.valeur_prevue) for t in en_vigueur] == [
        ("Etude detaillee", 30),
        ("Deploiement", 70),
    ]
    assert en_vigueur[0].pk == etude.pk
    abandon.refresh_from_db()
    assert abandon.invalide_le is not None  # invalidee, jamais supprimee
    assert Evenement.objects.filter(
        objet_id=activite.pk, type_evenement="activite_taches_modifiees"
    ).exists()


def test_redecouper_controle_la_somme(connecte):
    """RG-3, a toute modification ulterieure de la liste."""
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 100)
    reponse = _redecouper(
        connecte("focal.dsi"),
        activite,
        [_ligne(etude, "Etude", 60), _ligne(None, "Recette", 30)],
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "somme_taches"
    assert activite.taches.filter(invalide_le__isnull=True).count() == 1


def test_une_tache_avancee_ne_se_retire_pas(connecte):
    """Ses points disparaitraient de l'activite sans declaration ni justification."""
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 50, valeur_obtenue=20)
    recette = _tache(activite, "Recette", 50)

    reponse = _redecouper(connecte("focal.dsi"), activite, [_ligne(recette, "Recette", 100)])
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "tache_avancee_retiree"
    etude.refresh_from_db()
    assert etude.invalide_le is None


def test_la_valeur_prevue_ne_descend_pas_sous_l_obtenue(connecte):
    """RG-6 vaut aussi quand c'est la part qui bouge."""
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 50, valeur_obtenue=40)
    recette = _tache(activite, "Recette", 50)

    reponse = _redecouper(
        connecte("focal.dsi"),
        activite,
        [_ligne(etude, "Etude", 30), _ligne(recette, "Recette", 70)],
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "valeur_prevue_sous_obtenue"


def test_redecouper_exige_un_motif(connecte):
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 100)
    reponse = _redecouper(
        connecte("focal.dsi"), activite, [_ligne(etude, "Etude", 100)], motif="  "
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "motif_exige"


def test_on_ne_resserre_pas_l_activite_sur_ses_taches(connecte):
    """RG-9 dans l'autre sens : la periode de l'activite ne peut exclure une tache."""
    activite = _activite("DSI", "Refonte du reseau")
    _tache(activite, "Bilan", 100, date_debut=date(2026, 12, 1))
    reponse = connecte("focal.dsi").post(
        f"/api/activites/{activite.pk}",
        data={
            "intitule": activite.intitule,
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-11",
            "responsableId": None,
            "motif": "Calendrier resserre.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "tache_hors_periode"


# =====================================================================
#  La tache n'a pas d'attributaire — ADR 048
# =====================================================================


def test_une_tache_creee_ne_porte_aucun_agent(connecte):
    """
    Le formulaire ne demande plus « a quel agent ». Une tache se rattache a son
    activite, et qui en repond se lit sur l'activite (ADR 047). Un
    `responsableId` encore envoye par un front reste en arriere est ignore.
    """
    activite = _activite("DSI", "Refonte du reseau")
    ligne = _ligne(None, "Recetter le socle", 100) | {"responsableId": compte("agent.dsi").pk}
    assert _redecouper(connecte("focal.dsi"), activite, [ligne]).status_code == 200

    tache = activite.taches.get(invalide_le__isnull=True)
    assert tache.responsable_id is None


def test_le_responsable_des_taches_anciennes_reste_lisible(connecte):
    """
    La colonne n'est pas supprimee : les taches d'avant gardent leur agent, et
    la sortie continue de le porter. Le retrait vaut pour la saisie et pour
    l'ecran, pas pour la memoire.
    """
    activite = _activite("DSI", "Refonte du reseau")
    _tache(activite, "Cabler le batiment", responsable=compte("agent.dsi"))

    fiche = connecte("focal.dsi").get(f"/api/activites/{activite.pk}").json()
    assert fiche["taches"][0]["responsable"] == compte("agent.dsi").nom_complet


# =====================================================================
#  La justification et le recalibrage — ADR 030
# =====================================================================


def test_une_declaration_sans_justification_est_refusee(connecte):
    """
    §15 : « pourcentage + observation ». C'est cette observation qui alimente
    la fiche de vie et sur laquelle la DSR s'appuie pour recalibrer ; un taux
    sans elle ne se conteste pas, il se subit.
    """
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)
    reponse = _declarer(connecte("focal.dsi"), activite, tache, 90, observation="   ")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "observation_exigee"


def test_seule_la_dsr_recalibre(connecte):
    """
    Ni la structure qui declare, ni le controle de gestion — qui porte pourtant
    `ACT_VAL`. L'exigence dit « seule la DSR », et c'est `ACT_REC` qui la tient.
    """
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)

    for identifiant in ("focal.dsi", "dcg"):
        assert _recalibrer(connecte(identifiant), activite, tache, 50).status_code == 401

    assert _recalibrer(connecte("dsr"), activite, tache, 50).status_code == 200


def test_le_recalibrage_porte_sur_la_tache_et_n_efface_pas_la_declaration(connecte):
    """
    ADR 049 : la DSR recalibre une tache, et le taux retenu de l'activite reste
    la somme des valeurs retenues. La declaration de la structure demeure
    lisible a cote.
    """
    activite = _activite("DSI", "Refonte du reseau")
    etude = _tache(activite, "Etude", 40)
    deploiement = _tache(activite, "Deploiement", 60)
    _declarer(connecte("focal.dsi"), activite, etude, 40, "Etude remise.")
    _declarer(connecte("focal.dsi"), activite, deploiement, 40, "Chantier bien engage.")

    _recalibrer(connecte("dsr"), activite, deploiement, 10)

    activite.refresh_from_db()
    assert activite.avancement_calcule == 80
    assert activite.avancement_recalibre == 50
    assert activite.avancement_retenu == 50

    fiche = connecte("dsr").get(f"/api/activites/{activite.pk}").json()
    assert fiche["avancement"] == 50
    assert fiche["recalibrage"]["avancementDeclare"] == 80
    assert fiche["recalibrage"]["motif"] == "Aucune piece a l'appui."
    deploiement_lu = next(t for t in fiche["taches"] if t["id"] == deploiement.pk)
    assert deploiement_lu["recalibrage"]["valeurDeclaree"] == 40
    assert deploiement_lu["valeurRetenue"] == 10
    assert "Recalibrage" in [e["type"] for e in fiche["vie"]]


def test_le_recalibrage_tient_malgre_une_nouvelle_declaration(connecte):
    """
    Sinon l'exigence serait sans effet : il suffirait a la structure de
    redeclarer pour se donner raison. La levee appartient a la DSR.
    """
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)
    _recalibrer(connecte("dsr"), activite, tache, 20, "Realisations non justifiees.")
    _declarer(connecte("focal.dsi"), activite, tache, 95, "Presque fini.")

    activite.refresh_from_db()
    assert activite.avancement_calcule == 95
    assert activite.avancement_retenu == 20


def test_lever_le_recalibrage_rend_la_main_a_la_structure(connecte):
    """`valeur` a `null` leve le desaccord. Le motif reste exige."""
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)
    _declarer(connecte("focal.dsi"), activite, tache, 60, "Trois lots livres.")
    _recalibrer(connecte("dsr"), activite, tache, 30, "Justificatifs attendus.")
    _recalibrer(connecte("dsr"), activite, tache, None, "Justificatifs recus.")

    activite.refresh_from_db()
    assert activite.avancement_recalibre is None
    assert activite.avancement_retenu == 60
    fiche = connecte("dsr").get(f"/api/activites/{activite.pk}").json()
    assert fiche["recalibrage"] is None
    assert fiche["taches"][0]["recalibrage"] is None


def test_un_recalibrage_sans_motif_est_refuse(connecte):
    """Contredire une structure sans ecrire pourquoi ne se conteste pas."""
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite)
    reponse = _recalibrer(connecte("dsr"), activite, tache, 10, motif="")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "motif_exige"


def test_un_recalibrage_ne_depasse_pas_la_part_de_la_tache(connecte):
    activite = _activite("DSI", "Refonte du reseau")
    tache = _tache(activite, "Etude", 100)
    autre = _redecouper(
        connecte("focal.dsi"),
        activite,
        [_ligne(tache, "Etude", 30), _ligne(None, "Recette", 70)],
    )
    assert autre.status_code == 200
    reponse = _recalibrer(connecte("dsr"), activite, tache, 31)
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "avancement_hors_borne"


# =====================================================================
#  Les structures responsables — ADR 047
# =====================================================================


def test_une_activite_se_cree_sans_point_focal(connecte):
    """La responsabilite est institutionnelle : l'agent nomme est facultatif."""
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 200
    activite = Activite.objects.get(pk=reponse.json()["id"])
    assert activite.responsable_id is None
    assert activite.plan.structure.code == "DSI"


def test_la_periode_se_saisit_au_mois_et_borne_le_mois(connecte):
    """`2026-03` commence le 1er, `2026-11` finit le 30. Sinon novembre serait
    en retard des le 2."""
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-03",
            "fin": "2026-11",
            "responsableId": None,
            "taches": _tache_unique("2026-03", "2026-11"),
        },
        content_type="application/json",
    )
    activite = Activite.objects.get(pk=reponse.json()["id"])
    assert activite.date_debut == date(2026, 3, 1)
    assert activite.date_fin == date(2026, 11, 30)


def test_un_mois_de_fin_anterieur_est_refuse(connecte):
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-11",
            "fin": "2026-03",
            "responsableId": None,
            "taches": _tache_unique("2026-11", "2026-03"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "periode_invalide"


def test_une_structure_associee_voit_l_activite_du_voisin(connecte):
    """
    Le coeur de l'ADR 047 : associer une structure lui **ouvre** l'activite.

    `focal.daf` ne voit rien de la DSI — c'est ce que verifie
    `test_un_point_focal_ne_voit_pas_le_plan_du_voisin`. L'association renverse
    exactement cela, et rien d'autre : l'activite reste au plan de la DSI.
    """
    creation = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Dematerialisation",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": ["DAF"],
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert creation.status_code == 200
    identifiant = creation.json()["id"]

    fiche = connecte("focal.daf").get(f"/api/activites/{identifiant}")
    assert fiche.status_code == 200
    assert fiche.json()["structureSigle"] == "DSI"
    assert [s["sigle"] for s in fiche.json()["structuresAssociees"]] == ["DAF"]

    registre = connecte("focal.daf").get("/api/activites").json()
    assert identifiant in [ligne["id"] for ligne in registre["activites"]]


def test_une_structure_associee_declare_l_avancement(connecte):
    """Voir et declarer vont ensemble : l'ecriture passe par le meme filtre."""
    identifiant = (
        connecte("focal.dsi")
        .post(
            "/api/activites",
            data={
                "intitule": "Dematerialisation",
                "axe": AXE,
                "debut": "2026-01",
                "fin": "2026-12",
                "responsableId": None,
                "structuresAssociees": ["DAF"],
                "taches": _tache_unique("2026-01", "2026-12"),
            },
            content_type="application/json",
        )
        .json()["id"]
    )
    activite = Activite.objects.get(pk=identifiant)
    tache = activite.taches.get()

    reponse = _declarer(connecte("focal.daf"), activite, tache, 40, "Deux lots livres.")
    assert reponse.status_code == 200
    assert Activite.objects.get(pk=identifiant).avancement_retenu == 40


def test_la_structure_porteuse_ne_s_associe_pas_a_elle_meme(connecte):
    """Elle repond deja de l'activite par son plan : deux verites en feraient
    une fausse."""
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": ["DSI"],
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "structure_porteuse_associee"


def test_une_structure_inconnue_est_refusee(connecte):
    reponse = connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Refonte du reseau",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": ["XYZ"],
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "structure_inconnue"


def test_retirer_une_structure_lui_ferme_l_activite_et_laisse_sa_trace(connecte):
    """
    Le retrait est logique : la ligne reste, l'acces cesse.

    Un rattachement retire qui continuerait d'ouvrir l'activite ne serait pas un
    retrait ; une ligne supprimee effacerait qui en repondait au trimestre
    precedent.
    """
    identifiant = (
        connecte("focal.dsi")
        .post(
            "/api/activites",
            data={
                "intitule": "Dematerialisation",
                "axe": AXE,
                "debut": "2026-01",
                "fin": "2026-12",
                "responsableId": None,
                "structuresAssociees": ["DAF"],
                "taches": _tache_unique("2026-01", "2026-12"),
            },
            content_type="application/json",
        )
        .json()["id"]
    )
    assert connecte("focal.daf").get(f"/api/activites/{identifiant}").status_code == 200

    modification = connecte("focal.dsi").post(
        f"/api/activites/{identifiant}",
        data={
            "intitule": "Dematerialisation",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": [],
            "motif": "La DAF s'est retiree du projet.",
        },
        content_type="application/json",
    )
    assert modification.status_code == 200

    # 404 et non 403 : repondre « interdit » confirmerait l'existence — D5.
    assert connecte("focal.daf").get(f"/api/activites/{identifiant}").status_code == 404

    activite = Activite.objects.get(pk=identifiant)
    assert activite.structures_associees.count() == 1
    assert activite.structures_associees.filter(invalide_le__isnull=True).count() == 0
    assert Evenement.objects.filter(
        objet_type="activite",
        objet_id=identifiant,
        type_evenement="activite_structures_modifiees",
    ).exists()


def test_un_rattachement_retire_ne_masque_pas_l_activite_a_sa_porteuse(connecte):
    """
    Le piege du filtre de visibilite, tenu par un test.

    La premiere version posait la condition « non retire » dans un `filter()`
    separe : la jointure supplementaire faisait disparaitre du registre de la
    **porteuse** toute activite portant un rattachement retire.
    """
    identifiant = (
        connecte("focal.dsi")
        .post(
            "/api/activites",
            data={
                "intitule": "Dematerialisation",
                "axe": AXE,
                "debut": "2026-01",
                "fin": "2026-12",
                "responsableId": None,
                "structuresAssociees": ["DAF"],
                "taches": _tache_unique("2026-01", "2026-12"),
            },
            content_type="application/json",
        )
        .json()["id"]
    )
    connecte("focal.dsi").post(
        f"/api/activites/{identifiant}",
        data={
            "intitule": "Dematerialisation",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": [],
            "motif": "La DAF s'est retiree du projet.",
        },
        content_type="application/json",
    )

    registre = connecte("focal.dsi").get("/api/activites").json()
    lignes = [ligne["id"] for ligne in registre["activites"]]
    assert lignes.count(identifiant) == 1


def test_l_activite_associee_ne_compte_pas_deux_fois(connecte):
    """
    Une activite reste inscrite au **seul** plan de sa porteuse.

    Sans quoi une action transverse gonflerait deux directions a la fois, et
    aucun taux de plan ne voudrait plus rien dire.
    """
    connecte("focal.dsi").post(
        "/api/activites",
        data={
            "intitule": "Dematerialisation",
            "axe": AXE,
            "debut": "2026-01",
            "fin": "2026-12",
            "responsableId": None,
            "structuresAssociees": ["DAF"],
            "taches": _tache_unique("2026-01", "2026-12"),
        },
        content_type="application/json",
    )

    annee = Exercice.objects.get(ouvert=True).annee
    plan_daf = connecte("focal.daf").get(f"/api/activites/plan?annee={annee}&structure=DAF").json()
    assert "Dematerialisation" not in [a["intitule"] for a in plan_daf["activites"]]

    plan_dsi = connecte("focal.dsi").get(f"/api/activites/plan?annee={annee}&structure=DSI").json()
    assert "Dematerialisation" in [a["intitule"] for a in plan_dsi["activites"]]

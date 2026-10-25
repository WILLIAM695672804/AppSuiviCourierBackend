"""
Les traitements nocturnes.

Ce qu'ils doivent prouver n'est pas qu'ils calculent — c'est qu'ils **calculent
sans acteur**. Le declencheur d'historisation refuse toute ecriture qui n'en
declare pas un, et une tache planifiee n'en a pas. Une tache qui echouerait la
nuit ne reveillerait personne : le tableau de bord serait simplement faux au
matin.

Second point : elles sont **idempotentes**. Relancees deux fois, elles ne
doublent rien. C'est la condition pour pouvoir les rejouer apres un incident
sans se demander ce qu'elles ont deja fait.
"""

from datetime import date, timedelta

import pytest
from django.db import connection

from activite import taches
from activite.modeles import (
    Activite,
    ActiviteSuspension,
    AgregatActiviteJour,
    AxeStrategique,
    CalendrierProduction,
    Exercice,
    Obligation,
)
from activite.tests.test_schema import socle  # noqa: F401
from noyau.journal.contexte import acteur
from noyau.journal.modeles import Evenement
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache


@pytest.fixture(autouse=True)
def cache_propre():
    vider_cache()
    yield
    vider_cache()


def _activite(socle, **surcharges) -> Activite:  # noqa: F811
    defauts = {
        "plan": socle["plan"],
        "axe_strategique": AxeStrategique.objects.get(code="A1"),
        "intitule": "Refonte du reseau",
        "responsable": socle["agent"],
        "date_debut": date(2026, 1, 1),
        "date_fin": date(2026, 12, 31),
    }
    activite = Activite.objects.create(**{**defauts, **surcharges})
    activite.refresh_from_db()
    return activite


# =====================================================================
#  Agregats
# =====================================================================


def test_les_agregats_se_calculent_sans_acteur(socle):  # noqa: F811
    """
    Le point qui fait tout le module. Sans `traitement_automatique`, le
    declencheur d'historisation refuserait, et la tache echouerait la nuit sans
    reveiller personne.
    """
    hier = date.today() - timedelta(days=1)
    _activite(socle, intitule="Echue", date_fin=hier)
    _activite(socle, intitule="A temps", date_fin=date(2030, 1, 1))

    assert taches.recalculer_agregats() == 1

    agregat = AgregatActiviteJour.objects.get(
        structure=socle["structure"], exercice=socle["plan"].exercice, jour=date.today()
    )
    assert agregat.nb_total == 2
    assert agregat.nb_en_retard == 1
    assert agregat.nb_en_cours == 1


def test_l_agregat_lit_l_etat_dans_la_vue_et_non_ailleurs(socle):  # noqa: F811
    """
    Deux calculs d'une meme regle divergent toujours un jour. La vue fait foi
    cote SQL ; la tache la lit plutot que de recalculer le retard.
    """
    hier = date.today() - timedelta(days=1)
    activite = _activite(socle, date_fin=hier)
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )

    taches.recalculer_agregats()
    agregat = AgregatActiviteJour.objects.get(jour=date.today())
    # Echeance passee, mais suspendue : la vue dit « suspendue », pas « en retard ».
    assert (agregat.nb_suspendues, agregat.nb_en_retard) == (1, 0)


def test_relancer_le_recalcul_ne_double_rien(socle):  # noqa: F811
    _activite(socle)
    taches.recalculer_agregats()
    taches.recalculer_agregats()
    assert AgregatActiviteJour.objects.filter(jour=date.today()).count() == 1


def test_un_plan_vide_n_a_pas_un_taux_de_zero(socle):  # noqa: F811
    """Zero se lirait comme une contre-performance ; il n'y a rien a executer."""
    taches.recalculer_agregats()
    agregat = AgregatActiviteJour.objects.get(jour=date.today())
    assert agregat.nb_total == 0
    assert agregat.taux_execution is None


def test_le_recalcul_laisse_sa_trace(socle):  # noqa: F811
    taches.recalculer_agregats()
    assert Evenement.objects.filter(type_evenement="agregats_recalcules").exists()


# =====================================================================
#  Obligations
# =====================================================================


@pytest.fixture
def calendrier(socle):  # noqa: F811
    return CalendrierProduction.objects.create(
        structure=socle["structure"],
        nature="rapport_mensuel",
        intitule="Rapport mensuel d'activite",
        periodicite="mensuelle",
        jour_echeance=5,
        valide_du=date(2026, 1, 1),
    )


def test_les_obligations_sont_engendrees_pour_les_periodes_closes(calendrier):
    """
    Une periode n'est due qu'une fois close : le rapport de juillet ne s'attend
    pas le 15 juillet.
    """
    taches.engendrer_obligations("2026-08-15")

    periodes = set(Obligation.objects.values_list("periode_libelle", flat=True))
    assert "Juillet 2026" in periodes
    assert "Août 2026" not in periodes  # en cours, pas encore due


def test_l_echeance_tombe_sur_la_periode_suivante(calendrier):
    """Le rapport de juillet est du le 5 aout."""
    taches.engendrer_obligations("2026-08-15")
    juillet = Obligation.objects.get(periode_libelle="Juillet 2026")
    assert juillet.echeance == date(2026, 8, 5)
    assert juillet.periode_debut == date(2026, 7, 1)
    assert juillet.periode_fin == date(2026, 7, 31)


def test_l_engendrement_rattrape_les_periodes_manquees(calendrier):
    """
    On regarde en arriere plutot que d'engendrer « la periode suivante » : une
    tache qui n'a pas tourne pendant trois jours doit rattraper, pas laisser un
    trou que personne ne verra.
    """
    taches.engendrer_obligations("2026-08-15")
    assert Obligation.objects.count() >= 7  # janvier a juillet


def test_l_engendrement_ne_double_pas(calendrier):
    """Garanti par `obligation_unique_par_periode`, verifie ici."""
    premier = taches.engendrer_obligations("2026-08-15")
    second = taches.engendrer_obligations("2026-08-15")
    assert premier > 0 and second == 0


def test_rien_avant_l_entree_en_vigueur_du_calendrier(socle):  # noqa: F811
    """Une ligne de calendrier ouverte en juin n'engendre pas le rapport de
    janvier : la structure n'y etait tenue par rien."""
    CalendrierProduction.objects.create(
        structure=socle["structure"],
        nature="rapport_mensuel",
        intitule="Rapport mensuel",
        periodicite="mensuelle",
        valide_du=date(2026, 6, 1),
    )
    taches.engendrer_obligations("2026-08-15")
    debuts = set(Obligation.objects.values_list("periode_debut", flat=True))
    assert min(debuts) == date(2026, 6, 1)


def test_un_calendrier_trimestriel_engendre_des_trimestres(socle):  # noqa: F811
    CalendrierProduction.objects.create(
        structure=socle["structure"],
        nature="rapport_sectoriel",
        intitule="Rapport sectoriel",
        periodicite="trimestrielle",
        valide_du=date(2026, 1, 1),
    )
    taches.engendrer_obligations("2026-08-15")
    periodes = set(Obligation.objects.values_list("periode_libelle", flat=True))
    assert {"T1 2026", "T2 2026"} <= periodes
    assert "T3 2026" not in periodes  # en cours


# =====================================================================
#  Relances automatiques
# =====================================================================


def test_le_seuil_de_relance_est_une_hypothese(db):
    """
    Aucun texte ne dit au bout de combien de jours relancer. Le coder en dur
    aurait fait passer une invention pour une decision — A16.
    """
    for cle in (
        "activite.relance_auto_apres_jours",
        "activite.relance_auto_intervalle_jours",
    ):
        parametre = Parametre.objects.get(cle=cle)
        assert parametre.statut == "hypothese"
        assert parametre.a_trancher_par == "DSR"


def test_une_activite_en_retard_est_relancee(socle):  # noqa: F811
    aujourd_hui = date.today()
    activite = _activite(socle, date_fin=aujourd_hui - timedelta(days=10))

    assert taches.relancer_les_retards() == 1

    activite.refresh_from_db()
    assert activite.derniere_relance_le is not None
    assert Evenement.objects.filter(objet_id=activite.pk, type_evenement="relance_emise").exists()


def test_un_retard_plus_court_que_le_seuil_ne_declenche_rien(socle):  # noqa: F811
    """Relancer des le premier jour ferait du signal un bruit."""
    _activite(socle, date_fin=date.today() - timedelta(days=2))
    assert taches.relancer_les_retards() == 0


def test_sans_poste_de_tete_pourvu_la_relance_n_est_pas_emise(socle):  # noqa: F811
    """
    Une relance envoyee dans le vide fait croire que l'escalade a eu lieu : on
    ne l'emet pas, et le journal dit pourquoi (A81).
    """
    socle["directeur"].poste = None
    socle["directeur"].save(update_fields=["poste"])
    activite = _activite(socle, date_fin=date.today() - timedelta(days=10))

    assert taches.relancer_les_retards() == 0

    with connection.cursor() as curseur:
        curseur.execute("SELECT count(*) FROM relance")
        assert curseur.fetchone()[0] == 0
    assert Evenement.objects.filter(
        objet_id=activite.pk, type_evenement="relance_sans_destinataire"
    ).exists()


def test_une_activite_suspendue_n_est_pas_relancee(socle):  # noqa: F811
    """
    Relancer une structure a qui une autorite a interdit d'avancer serait faux.
    """
    activite = _activite(socle, date_fin=date.today() - timedelta(days=30))
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    assert taches.relancer_les_retards() == 0


def test_on_ne_relance_pas_la_meme_activite_chaque_nuit(socle):  # noqa: F811
    """
    Sans intervalle, le responsable cesserait de lire et l'escalade ne servirait
    plus a rien.
    """
    _activite(socle, date_fin=date.today() - timedelta(days=10))
    assert taches.relancer_les_retards() == 1
    assert taches.relancer_les_retards() == 0


def test_la_relance_automatique_n_a_pas_d_emetteur(socle):  # noqa: F811
    """
    Personne ne l'a signee : lui attribuer un agent serait faux.

    Le destinataire, lui, est le **directeur de la tete** et non le
    responsable nomme de l'activite — l'escalade du §16 remonte a qui peut
    arbitrer.
    """
    _activite(socle, date_fin=date.today() - timedelta(days=10))
    taches.relancer_les_retards()

    with connection.cursor() as curseur:
        curseur.execute("SELECT nature, emetteur_id, destinataire_id FROM relance")
        lignes = curseur.fetchall()

    assert len(lignes) == 1
    nature, emetteur, destinataire = lignes[0]
    assert (nature, emetteur) == ("automatique", None)
    assert destinataire == socle["directeur"].pk


# =====================================================================
#  Exercice
# =====================================================================


def test_l_exercice_suivant_s_ouvre_en_decembre(db):
    assert taches.ouvrir_exercice_suivant("2026-12-01") is True
    assert Exercice.objects.filter(annee=2027, ouvert=True).exists()


def test_rien_ne_s_ouvre_le_reste_de_l_annee(db):
    assert taches.ouvrir_exercice_suivant("2026-07-01") is False
    assert not Exercice.objects.filter(annee=2027).exists()


def test_l_ouverture_ne_clot_pas_le_precedent(db):
    """
    Clore un exercice interdit toute saisie retroactive, et rien ne dit quand
    cela doit arriver — un plan se rend parfois en janvier pour l'annee ecoulee.
    """
    en_cours = Exercice.objects.get(ouvert=True)
    taches.ouvrir_exercice_suivant("2026-12-01")
    en_cours.refresh_from_db()
    assert en_cours.ouvert is True


def test_ouvrir_deux_fois_ne_cree_qu_un_exercice(db):
    taches.ouvrir_exercice_suivant("2026-12-01")
    assert taches.ouvrir_exercice_suivant("2026-12-02") is False
    assert Exercice.objects.filter(annee=2027).count() == 1


# =====================================================================
#  Le filet
# =====================================================================


def test_toutes_les_taches_sont_decouvertes_par_celery():
    """
    Filet. Celery cherche `tasks.py` par defaut ; le depot ecrit `taches.py`.
    Sans `related_name="taches"` dans `config/celery.py`, **aucune tache ne
    serait jamais executee** — et l'echec est silencieux : le worker demarre,
    et rien ne tourne.
    """
    from config.celery import app

    app.loader.import_default_modules()
    enregistrees = set(app.tasks)
    attendues = {
        "activite.recalculer_agregats",
        "activite.engendrer_obligations",
        "activite.relancer_les_retards",
        "activite.ouvrir_exercice_suivant",
    }
    assert attendues <= enregistrees, f"Manquent : {sorted(attendues - enregistrees)}"


# La verification « toute tache ecrite est planifiee » a demenage dans
# `noyau/tests/test_socle.py` : elle porte sur l'ordonnanceur entier, et non sur
# ce pilier. Ecrite ici, elle enumerait les taches des activites et laissait
# passer une tache de gouvernance jamais planifiee — ce qui est arrive.

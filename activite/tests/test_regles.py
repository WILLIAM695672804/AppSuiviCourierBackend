"""
La definition du retard, et le fait qu'elle soit unique.

Le danger de ce module n'est pas qu'il calcule faux — c'est qu'il calcule
**autrement que la vue SQL**. Deux definitions du retard ont deja coexiste dans
ce projet ; le dernier test de ce fichier existe pour qu'elles ne recommencent
pas.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from activite import regles
from activite.modeles import Activite, ActiviteSuspension, AxeStrategique, VueActiviteEtat
from activite.tests.test_schema import socle  # noqa: F401
from noyau.journal.contexte import acteur
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache

AUJOURD_HUI = date(2026, 7, 1)


@pytest.fixture(autouse=True)
def cache_propre():
    """Le cache des parametres traverse les tests s'il n'est pas vide."""
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
    return Activite.objects.create(**{**defauts, **surcharges})


# =====================================================================
#  La regle qui fait foi
# =====================================================================


def test_la_definition_du_retard_est_actee_et_non_une_hypothese(db):
    """
    A2 est tranchee. La ligne porte `statut = 'acte'` et une source : c'est ce
    qui la distingue des quatre regles inventees par la conception.
    """
    parametre = Parametre.objects.get(cle="activite.definition_retard")
    assert parametre.valeur == regles.ECHEANCE_DEPASSEE
    assert parametre.statut == "acte"
    assert "Arbitrage n° 2" in parametre.source


def test_l_ecart_a_l_attendu_reste_une_hypothese(db):
    """
    Trancher A2 ne transforme pas l'autre regle en decision : elle n'a toujours
    aucune source. Elle cesse seulement de decider de l'etat.
    """
    for cle in ("activite.mode_avancement_attendu", "activite.seuil_retard_points"):
        assert Parametre.objects.get(cle=cle).statut == "hypothese"


# =====================================================================
#  L'etat affiche
# =====================================================================


def test_une_activite_dont_l_echeance_est_passee_est_en_retard(socle):  # noqa: F811
    activite = _activite(socle, date_fin=date(2026, 6, 1))
    assert regles.etat_affiche(activite, aujourd_hui=AUJOURD_HUI) == regles.EN_RETARD


def test_une_activite_qui_n_a_pas_commence_est_programmee(socle):  # noqa: F811
    activite = _activite(socle, date_debut=date(2026, 9, 1), date_fin=date(2026, 12, 1))
    assert regles.etat_affiche(activite, aujourd_hui=AUJOURD_HUI) == regles.PROGRAMMEE


def test_un_avancement_faible_ne_suffit_pas_a_mettre_en_retard(socle):  # noqa: F811
    """
    Le coeur de l'arbitrage. A 20 % d'avancement au milieu de sa periode, cette
    activite serait « en retard » selon l'ecart a l'attendu — elle ne l'est pas
    selon la regle sourcee, parce que son echeance n'est pas passee.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        Activite.objects.filter(pk=activite.pk).update(avancement_calcule=20)
    activite.refresh_from_db()

    assert regles.ecart_a_attendu(activite, aujourd_hui=AUJOURD_HUI) < -10
    assert regles.etat_affiche(activite, aujourd_hui=AUJOURD_HUI) == regles.EN_COURS


def test_une_activite_suspendue_n_est_pas_en_retard(socle):  # noqa: F811
    """
    Reprocher un retard a une structure a qui une autorite a interdit d'avancer
    serait faux. La suspension prime, echeance passee ou non.
    """
    activite = _activite(socle, date_fin=date(2026, 6, 1))
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    activite.refresh_from_db()

    assert regles.etat_affiche(activite, aujourd_hui=AUJOURD_HUI) == regles.SUSPENDUE
    assert regles.est_en_retard(activite, aujourd_hui=AUJOURD_HUI) is False


def test_une_activite_realisee_apres_l_echeance_n_est_plus_en_retard(socle):  # noqa: F811
    """L'etat, pas la date, dit si le travail a ete fait."""
    activite = _activite(socle, date_fin=date(2026, 6, 1))
    with acteur(socle["agent"]):
        Activite.objects.filter(pk=activite.pk).update(etat=Activite.REALISEE)
    activite.refresh_from_db()

    assert regles.etat_affiche(activite, aujourd_hui=AUJOURD_HUI) == regles.REALISEE


# =====================================================================
#  L'ecart a l'attendu, devenu indicatif
# =====================================================================


def test_l_avancement_attendu_est_lineaire_sur_la_periode(socle):  # noqa: F811
    activite = _activite(socle, date_debut=date(2026, 1, 1), date_fin=date(2026, 1, 11))
    attendu = regles.avancement_attendu(activite, aujourd_hui=date(2026, 1, 6))
    assert attendu == Decimal("50.00")


def test_l_attendu_est_indefini_avant_le_debut(socle):  # noqa: F811
    """Un attendu de zero se lirait comme une mesure, alors qu'il n'y a rien a
    attendre encore."""
    activite = _activite(socle, date_debut=date(2026, 9, 1), date_fin=date(2026, 12, 1))
    assert regles.avancement_attendu(activite, aujourd_hui=AUJOURD_HUI) is None
    assert regles.ecart_a_attendu(activite, aujourd_hui=AUJOURD_HUI) is None


def test_basculer_le_parametre_change_la_regle_appliquee(socle):  # noqa: F811
    """
    Le jour ou la DSR trancherait autrement, c'est une ligne en base et non un
    redeploiement. Ce test le prouve — il ne valide pas l'autre regle.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        Activite.objects.filter(pk=activite.pk).update(avancement_calcule=20)
    activite.refresh_from_db()
    assert regles.est_en_retard(activite, aujourd_hui=AUJOURD_HUI) is False

    Parametre.objects.filter(cle="activite.definition_retard").update(valeur=regles.ECART_A_ATTENDU)
    vider_cache()
    assert regles.est_en_retard(activite, aujourd_hui=AUJOURD_HUI) is True


# =====================================================================
#  Le filet
# =====================================================================


def test_les_deux_definitions_du_retard_concordent(socle):  # noqa: F811
    """
    Python et SQL doivent dire la meme chose.

    La vue `v_activite_etat` sert aux registres et aux agregats ; `regles.py`
    sert aux cas unitaires. Si elles divergent, deux ecrans affichent deux
    chiffres — exactement ce que trancher A2 devait faire cesser.

    Le test travaille a la date du jour, la vue utilisant `CURRENT_DATE` : c'est
    le seul repere que les deux partagent.
    """
    hier = date.today() - timedelta(days=1)
    demain = date.today() + timedelta(days=1)

    cas = [
        _activite(socle, intitule="Echue", date_debut=date(2026, 1, 1), date_fin=hier),
        _activite(socle, intitule="En cours", date_debut=date(2026, 1, 1), date_fin=demain),
        _activite(socle, intitule="A venir", date_debut=demain, date_fin=demain),
    ]
    realisee = _activite(socle, intitule="Faite", date_debut=date(2026, 1, 1), date_fin=hier)
    with acteur(socle["agent"]):
        Activite.objects.filter(pk=realisee.pk).update(etat=Activite.REALISEE)
    realisee.refresh_from_db()
    cas.append(realisee)

    suspendue = _activite(socle, intitule="Gelee", date_debut=date(2026, 1, 1), date_fin=hier)
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=suspendue, motif="Budget gele", suspendu_par=socle["agent"]
        )
    suspendue.refresh_from_db()
    cas.append(suspendue)

    selon_sql = {v.id: v.etat_affiche for v in VueActiviteEtat.objects.all()}
    for activite in cas:
        assert regles.etat_affiche(activite) == selon_sql[activite.pk], activite.intitule

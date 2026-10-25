"""
Le schema du pilier activites, par ce qu'il refuse et par ce qu'il calcule.

Ces tests ne verifient pas que les tables existent — une migration appliquee le
dit deja. Ils verifient que les **regles posees au moteur** tiennent : le code
attribue, l'avancement recalcule, le refus d'avancer une activite suspendue, la
coherence de l'etat de suspension.

C'est le seul endroit ou elles sont eprouvees. Elles ne sont pas dans
`services.py` et ne doivent pas y etre : une regle tenue par le moteur vaut
aussi pour une reprise de donnees et pour une correction faite en SQL direct.
"""

from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.utils import ProgrammingError

from activite.modeles import (
    Activite,
    ActiviteSuspension,
    AxeStrategique,
    Exercice,
    PlanActions,
    Tache,
)
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.organisation.modeles import NiveauHierarchique, Poste, Structure


@pytest.fixture
def socle(db):
    """
    Le minimum pour qu'une activite existe : une structure, un agent, un plan.

    **Et un directeur.** La relance s'adresse au responsable de la tete de
    structure, pas au responsable nomme de l'activite : une structure sans
    poste de tete pourvu n'est relancable par personne (A81), et les tests de
    `relancer_les_retards` ne verifieraient plus que le refus d'emettre.

    Les niveaux hierarchiques et l'exercice en cours sont **livres par le
    schema**, pas crees ici : les recreer masquerait le jour ou ils
    disparaitraient du SQL.
    """
    niveau = NiveauHierarchique.objects.get(code="DIR")
    structure = Structure.objects.create(
        code="DSI",
        libelle="Direction des systemes",
        niveau_hierarchique=niveau,
        valide_du=date(2026, 1, 1),
    )
    poste = Poste.objects.create(
        structure=structure,
        libelle="Directeur des systemes d'information",
        niveau_hierarchique=niveau,
        est_responsable=True,
        valide_du=date(2026, 1, 1),
    )
    agent = Utilisateur.objects.create(nom="Ateba", prenom="Joseph")
    directeur = Utilisateur.objects.create(nom="Ekwalla", prenom="Marthe", poste=poste)
    exercice = Exercice.objects.get(ouvert=True)
    plan = PlanActions.objects.create(structure=structure, exercice=exercice)
    return {
        "structure": structure,
        "agent": agent,
        "directeur": directeur,
        "plan": plan,
    }


def _activite(socle, **surcharges) -> Activite:
    defauts = {
        "plan": socle["plan"],
        "axe_strategique": AxeStrategique.objects.get(code="A1"),
        "intitule": "Refonte du reseau",
        "responsable": socle["agent"],
        "date_debut": date(2026, 1, 1),
        "date_fin": date(2026, 12, 31),
    }
    return Activite.objects.create(**{**defauts, **surcharges})


def _tache(activite, intitule: str, prevue, **surcharges) -> Tache:
    """Une tache sur toute l'annee de l'activite : RG-8 veut des mois entiers."""
    defauts = {
        "activite": activite,
        "intitule": intitule,
        "valeur_prevue": prevue,
        "date_debut": date(2026, 1, 1),
        "date_fin": date(2026, 12, 31),
    }
    return Tache.objects.create(**{**defauts, **surcharges})


# =====================================================================
#  Referentiel livre
# =====================================================================


def test_les_trois_axes_strategiques_sont_charges(db):
    """Referentiel ferme, communique le 11 aout 2026. Ni un de plus, ni un de moins."""
    assert list(AxeStrategique.objects.values_list("code", flat=True)) == ["A1", "A2", "A3"]


def test_l_exercice_en_cours_existe_des_l_installation(db):
    """Sans lui, la base n'est pas utilisable a la premiere connexion."""
    assert Exercice.objects.filter(ouvert=True).exists()


# =====================================================================
#  Ce que le moteur calcule
# =====================================================================


def test_le_code_de_l_activite_est_attribue_et_jamais_saisi(socle):
    """
    `PAA-<code structure>-<numero>`, numerote par plan — comme le numero du
    courrier.

    Le `refresh_from_db()` n'est pas une precaution : le code est pose par un
    declencheur `BEFORE INSERT`, et Django ne relit pas la ligne apres
    l'insertion. L'objet en memoire porte la chaine vide tant qu'on ne le
    recharge pas. Les services devront le faire.
    """
    premiere = _activite(socle)
    seconde = _activite(socle, intitule="Migration des postes")
    premiere.refresh_from_db()
    seconde.refresh_from_db()
    assert premiere.code == "PAA-DSI-01"
    assert seconde.code == "PAA-DSI-02"


def test_l_avancement_est_la_somme_brute_des_valeurs_obtenues(socle):
    """
    RG-5 et RG-7 (ADR 049). Une tache prevue a 30 et declaree a 15 apporte 15
    points a l'activite, sans conversion ni normalisation.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        etude = _tache(activite, "Etude", 30)
        deploiement = _tache(activite, "Deploiement", 70)

    activite.refresh_from_db()
    assert activite.avancement_calcule == 0

    with acteur(socle["agent"]):
        Tache.objects.filter(pk=etude.pk).update(valeur_obtenue=15)
        Tache.objects.filter(pk=deploiement.pk).update(valeur_obtenue=35)

    activite.refresh_from_db()
    assert activite.avancement_calcule == 50


def test_une_tache_invalidee_cesse_de_compter(socle):
    """Le declencheur ne somme que les taches en vigueur."""
    from django.utils import timezone

    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 100, valeur_obtenue=40)
    activite.refresh_from_db()
    assert activite.avancement_calcule == 40

    with acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(invalide_le=timezone.now())
    activite.refresh_from_db()
    assert activite.avancement_calcule == 0


def test_la_date_de_realisation_suit_la_valeur_obtenue(socle):
    """
    Posee le jour ou la tache atteint sa part, effacee si elle redescend : la
    date ne se saisit plus, elle se deduit (ADR 049).
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 40)
        Tache.objects.filter(pk=tache.pk).update(valeur_obtenue=40)
    tache.refresh_from_db()
    assert tache.fait_le == date.today()

    with acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(valeur_obtenue=20)
    tache.refresh_from_db()
    assert tache.fait_le is None


# =====================================================================
#  Ce que le moteur refuse
# =====================================================================


def test_une_activite_suspendue_n_accepte_plus_d_avancement(socle):
    """
    §19. La regle est au moteur et non dans le code : c'est la seule facon
    qu'elle tienne aussi pour une correction faite en SQL direct.

    Le declencheur leve un `check_violation`, que psycopg remonte en
    `IntegrityError` — et non une erreur applicative. Le service devra la
    traduire en refus lisible pour l'agent.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    activite.refresh_from_db()
    assert activite.etat == Activite.SUSPENDUE

    with pytest.raises(IntegrityError, match="suspendue"), acteur(socle["agent"]):
        Activite.objects.filter(pk=activite.pk).update(avancement_calcule=50)


def test_une_tache_d_activite_suspendue_n_avance_pas(socle):
    """
    §19, par ricochet : la declaration porte sur la tache (RG-4), mais le
    declencheur recalcule l'activite, et c'est la que la garde refuse.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 100)
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )

    with pytest.raises(IntegrityError, match="suspendue"), acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(valeur_obtenue=50)


def test_deux_suspensions_ouvertes_sont_impossibles(socle):
    """Deux suspensions ouvertes rendraient la reprise ambigue."""
    activite = _activite(socle)
    with acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    with pytest.raises(IntegrityError), acteur(socle["agent"]):
        ActiviteSuspension.objects.create(
            activite=activite, motif="Autre motif", suspendu_par=socle["agent"]
        )


def test_la_reprise_ramene_l_activite_en_cours(socle):
    """
    A la reprise, l'etat revient a « en cours » et non a ce qu'il etait avant :
    une activite qu'on reprend n'est, par definition, pas realisee.
    """
    from django.utils import timezone

    activite = _activite(socle)
    with acteur(socle["agent"]):
        suspension = ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    with acteur(socle["agent"]):
        suspension.repris_le = timezone.now()
        suspension.repris_par = socle["agent"]
        suspension.save()

    activite.refresh_from_db()
    assert activite.etat == Activite.EN_COURS


def test_un_plan_retourne_sans_motif_est_refuse(socle):
    """Un plan renvoye sans motif n'est pas corrige : il est resoumis a l'identique."""
    plan = socle["plan"]
    with pytest.raises(IntegrityError), transaction.atomic():
        PlanActions.objects.filter(pk=plan.pk).update(statut=PlanActions.RETOURNE)


def test_la_valeur_obtenue_ne_depasse_pas_la_valeur_prevue(socle):
    """RG-6, au moteur : une reprise en SQL direct y est tenue aussi."""
    activite = _activite(socle)
    with pytest.raises(IntegrityError), transaction.atomic():
        _tache(activite, "Etude", 30, valeur_obtenue=31)


@pytest.mark.parametrize("prevue", [0, -5, 101])
def test_la_valeur_prevue_est_bornee(socle, prevue):
    """RG-2. Strictement positive : une tache de valeur nulle ne se realise jamais."""
    activite = _activite(socle)
    with pytest.raises(IntegrityError), transaction.atomic():
        _tache(activite, "Etude", prevue)


def test_une_tache_se_situe_en_mois_entiers(socle):
    """RG-8. Un quantieme au milieu du mois est refuse."""
    activite = _activite(socle)
    with pytest.raises(IntegrityError), transaction.atomic():
        _tache(activite, "Etude", 100, date_debut=date(2026, 3, 15))


# =====================================================================
#  Historisation
# =====================================================================


def test_modifier_une_activite_sans_acteur_est_refuse(socle):
    """
    RNF-TRACE-01. Une modification enregistree sans acteur retire toute valeur
    probante a l'audit, et l'oubli passerait inapercu jusqu'au jour ou l'on
    aurait besoin de la trace.
    """
    activite = _activite(socle)
    with pytest.raises(ProgrammingError, match="sans acteur identifie"), transaction.atomic():
        Activite.objects.filter(pk=activite.pk).update(intitule="Autre intitule")


def test_avec_un_acteur_la_modification_passe_et_laisse_sa_trace(socle):
    from noyau.journal.modeles import ChampHistorique

    activite = _activite(socle)
    with acteur(socle["agent"]):
        Activite.objects.filter(pk=activite.pk).update(intitule="Refonte du reseau etendu")

    trace = ChampHistorique.objects.get(table_cible="activite", colonne="intitule")
    assert trace.valeur_avant == "Refonte du reseau"
    assert trace.valeur_apres == "Refonte du reseau etendu"
    assert trace.acteur_id == socle["agent"].pk


# =====================================================================
#  La vue d'etat
# =====================================================================


def test_l_etat_affiche_deduit_le_retard_des_dates(socle):
    """
    Arbitrage n° 2 : trois etats stockes, cinq affiches. Les stocker imposerait
    de reecrire toutes les lignes chaque nuit pour un resultat que la date
    donne deja.
    """
    from activite.modeles import VueActiviteEtat

    hier = date.today() - timedelta(days=1)
    echue = _activite(socle, date_debut=date(2026, 1, 1), date_fin=hier)
    future = _activite(
        socle,
        intitule="Chantier suivant",
        date_debut=date.today() + timedelta(days=30),
        date_fin=date.today() + timedelta(days=60),
    )

    etats = {v.id: v.etat_affiche for v in VueActiviteEtat.objects.all()}
    assert etats[echue.pk] == "en_retard"
    assert etats[future.pk] == "programmee"


def test_la_criticite_demande_le_retard_ET_une_contrainte_echue(socle):
    """
    §20. Le retard seul ne suffit pas — sans quoi la moitie du plan serait
    critique et le mot ne trierait plus rien.
    """
    from activite.modeles import VueActiviteEtat

    hier = date.today() - timedelta(days=1)
    activite = _activite(socle, date_fin=hier)
    assert VueActiviteEtat.objects.get(pk=activite.pk).contrainte_echue is False

    # Une tache dont le dernier mois est passe et qui n'a pas obtenu sa part.
    _tache(
        activite,
        "Recette",
        100,
        date_debut=date(2025, 1, 1),
        date_fin=date(2025, 1, 31),
    )
    assert VueActiviteEtat.objects.get(pk=activite.pk).contrainte_echue is True


# =====================================================================
#  Le taux retenu — ADR 030
# =====================================================================


def test_le_taux_retenu_suit_le_recalibrage(socle):
    """
    `avancement_retenu` est une colonne **generee** : elle bascule sans que
    personne ne l'ecrive. C'est ce qui evite que chacun des consommateurs de
    l'avancement ecrive son propre COALESCE, et qu'un seul l'oublie.

    Depuis l'ADR 049, la DSR recalibre une tache, et le taux retenu de
    l'activite est la somme des valeurs retenues — recalibrees ou declarees.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        etude = _tache(activite, "Etude", 40, valeur_obtenue=40)
        _tache(activite, "Deploiement", 60, valeur_obtenue=40)
    activite.refresh_from_db()
    assert activite.avancement_retenu == 80
    assert activite.avancement_recalibre is None

    with acteur(socle["agent"]):
        Tache.objects.filter(pk=etude.pk).update(
            valeur_recalibree=10, recalibrage_motif="Non justifie."
        )
    activite.refresh_from_db()
    assert activite.avancement_calcule == 80
    assert activite.avancement_recalibre == 50
    assert activite.avancement_retenu == 50

    with acteur(socle["agent"]):
        Tache.objects.filter(pk=etude.pk).update(valeur_recalibree=None)
    activite.refresh_from_db()
    assert activite.avancement_recalibre is None
    assert activite.avancement_retenu == 80


def test_un_recalibrage_sans_motif_est_refuse_par_le_moteur(socle):
    """
    Meme regle que `paa_retour_motive`, et tenue au meme endroit : une reprise
    de donnees ne doit pas pouvoir poser un desaccord muet.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 100, valeur_obtenue=80)
    with pytest.raises(IntegrityError), transaction.atomic(), acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(valeur_recalibree=50)


def test_un_recalibrage_ne_depasse_pas_la_part_de_la_tache(socle):
    """La DSR est tenue par la meme borne que la structure (RG-6)."""
    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 30)
    with pytest.raises(IntegrityError), transaction.atomic(), acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(valeur_recalibree=31, recalibrage_motif="Trop.")


def test_une_activite_suspendue_ne_se_recalibre_pas(socle):
    """
    Le declencheur livre ne surveillait que `avancement_calcule`. Laisser
    passer le recalibrage aurait rouvert par la fenetre ce que le §19 ferme.
    """
    activite = _activite(socle)
    with acteur(socle["agent"]):
        tache = _tache(activite, "Etude", 100, valeur_obtenue=80)
        ActiviteSuspension.objects.create(
            activite=activite, motif="Budget gele", suspendu_par=socle["agent"]
        )
    activite.refresh_from_db()
    assert activite.etat == "suspendue"

    with pytest.raises(IntegrityError), transaction.atomic(), acteur(socle["agent"]):
        Tache.objects.filter(pk=tache.pk).update(
            valeur_recalibree=50, recalibrage_motif="Non justifie."
        )

"""
Le schema du pilier gouvernance, par ce qu'il refuse et par ce qu'il calcule.

Le point le plus important de ce fichier est le premier : **une seule table
d'engagement, trois origines** (ADR 006). Si quelqu'un ajoutait un jour une
table jumelle pour les prescriptions ou les recommandations, les regles se
mettraient a diverger sans que rien ne le signale — le projet a deja paye cela
avec les deux definitions du retard.
"""

from datetime import date, timedelta

import pytest
from django.db import IntegrityError, connection, transaction

from gouvernance.modeles import (
    CongeDroit,
    CongePeriode,
    Disponibilite,
    Engagement,
    EngagementJalon,
    EngagementObservation,
    EngagementStructure,
    EntiteExterne,
    OrganeGestion,
    OrganisationExterne,
    Representation,
    Seance,
    VueEngagementEtat,
)
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.organisation.modeles import NiveauHierarchique, Structure


@pytest.fixture
def socle(db):
    niveau = NiveauHierarchique.objects.get(code="DIR")
    dsi = Structure.objects.create(
        code="DSI",
        libelle="Systemes d'information",
        niveau_hierarchique=niveau,
        valide_du=date(2026, 1, 1),
    )
    daf = Structure.objects.create(
        code="DAF",
        libelle="Affaires financieres",
        niveau_hierarchique=niveau,
        valide_du=date(2026, 1, 1),
    )
    dg = Utilisateur.objects.create(nom="Kingue", prenom="Emmanuel")
    dsr = Utilisateur.objects.create(nom="Mbarga", prenom="Serge")
    return {"dsi": dsi, "daf": daf, "dg": dg, "dsr": dsr}


@pytest.fixture
def seance(socle):
    return Seance.objects.create(
        reference="CODIR-2026-06",
        type_seance=Seance.CODIR,
        intitule="CODIR du 12 juin 2026",
        date_seance=date(2026, 6, 12),
        president=socle["dg"],
        structure=socle["dsi"],
        echeance_depot=date(2026, 6, 26),
    )


def _engagement(socle, seance_, **surcharges) -> Engagement:
    defauts = {
        "origine": Engagement.INSTANCE,
        "instance": "codir",
        "seance": seance_,
        "date_engagement": date(2026, 6, 12),
        "objet": "Fiabiliser le reseau du terminal",
        "prise_par": socle["dg"],
        "saisie_par": socle["dsr"],
    }
    engagement = Engagement.objects.create(**{**defauts, **surcharges})
    engagement.refresh_from_db()
    return engagement


# =====================================================================
#  ADR 006 — une seule table, trois origines
# =====================================================================


def test_il_n_y_a_qu_une_table_d_engagement(db):
    """
    Filet de l'ADR 006. Trois tables jumelles auraient triple chaque regle —
    calcul de l'etat, de l'avancement, du feu, de la relance — et garanti qu'un
    jour deux ecrans afficheraient deux chiffres.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = current_schema()
               AND table_name IN ('decision_reunion','prescription','recommandation',
                                  'prescription_filiale','recommandation_externe')
            """
        )
        assert curseur.fetchall() == []


def test_les_trois_origines_vivent_dans_la_meme_table(socle, seance):
    entite = EntiteExterne.objects.create(
        sigle="SEPBC",
        libelle="Societe d'exploitation",
        nature="filiale",
        valide_du=date(2026, 1, 1),
    )
    organe = OrganeGestion.objects.create(entite_externe=entite, organe="conseil_administration")
    organisation = OrganisationExterne.objects.create(
        sigle="AGPAOC",
        libelle="Association de gestion des ports",
        nature="organisation_portuaire",
    )

    _engagement(socle, seance)
    _engagement(
        socle,
        seance,
        origine=Engagement.ORGANE_FILIALE,
        instance=None,
        seance=None,
        organe_gestion=organe,
        objet="Redresser les comptes",
    )
    _engagement(
        socle,
        seance,
        origine=Engagement.ORGANISATION_EXTERNE,
        instance=None,
        seance=None,
        organisation_externe=organisation,
        objet="Harmoniser les tarifs",
    )

    assert Engagement.objects.count() == 3
    assert set(Engagement.objects.values_list("origine", flat=True)) == {
        "instance",
        "organe_filiale",
        "organisation_externe",
    }


def test_un_engagement_sans_provenance_est_refuse(socle, seance):
    """
    Il ne serait rattachable a aucun ecran : ni au registre des decisions, ni
    aux filiales, ni aux representations.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        _engagement(
            socle,
            seance,
            origine=Engagement.ORGANE_FILIALE,
            instance=None,
            seance=None,
            organe_gestion=None,
        )


def test_une_recommandation_externe_n_est_pas_rendue_par_le_codir(socle, seance):
    """`instance` ne qualifie qu'un engagement interne."""
    organisation = OrganisationExterne.objects.create(
        sigle="AGPAOC", libelle="Association", nature="organisation_portuaire"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        _engagement(
            socle,
            seance,
            origine=Engagement.ORGANISATION_EXTERNE,
            instance="codir",
            seance=None,
            organisation_externe=organisation,
        )


# =====================================================================
#  Ce que le moteur calcule
# =====================================================================


def test_la_reference_est_attribuee_par_origine_et_par_annee(socle, seance):
    """`DEC` pour une decision, `PRE` pour une prescription, `REC` pour une
    recommandation. Jamais saisie, comme le numero du courrier."""
    premier = _engagement(socle, seance)
    second = _engagement(socle, seance, objet="Deuxieme decision")
    assert premier.reference == "DEC-2026-0001"
    assert second.reference == "DEC-2026-0002"


def test_l_avancement_est_la_moyenne_des_structures_chargees(socle, seance):
    """
    A parts egales — c'est une hypothese (A17), pas une regle sourcee. Rien ne
    dit qu'une structure pilote pese plus que ses co-chargees.
    """
    engagement = _engagement(socle, seance)
    with acteur(socle["dsr"]):
        EngagementStructure.objects.create(
            engagement=engagement, structure=socle["dsi"], rang=1, avancement=80
        )
        EngagementStructure.objects.create(
            engagement=engagement, structure=socle["daf"], rang=2, avancement=20
        )

    engagement.refresh_from_db()
    assert engagement.avancement == 50


def test_le_rang_1_est_la_structure_pilote(socle, seance):
    """Colonne calculee par la base. Sans pilote designe, personne ne repond
    quand l'instance demande ou cela en est."""
    engagement = _engagement(socle, seance)
    pilote = EngagementStructure.objects.create(
        engagement=engagement, structure=socle["dsi"], rang=1
    )
    co = EngagementStructure.objects.create(engagement=engagement, structure=socle["daf"], rang=2)
    pilote.refresh_from_db()
    co.refresh_from_db()
    assert (pilote.pilote, co.pilote) == (True, False)


def test_deux_structures_ne_partagent_pas_un_rang(socle, seance):
    engagement = _engagement(socle, seance)
    EngagementStructure.objects.create(engagement=engagement, structure=socle["dsi"], rang=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        EngagementStructure.objects.create(engagement=engagement, structure=socle["daf"], rang=1)


# =====================================================================
#  L'etat affiche
# =====================================================================


def test_l_etat_se_deduit_des_dates_et_de_l_avancement(socle, seance):
    """
    Cinq etats affiches, deux stockes. Meme arbitrage que pour les activites :
    les stocker imposerait de reecrire toutes les lignes chaque nuit.
    """
    hier = date.today() - timedelta(days=1)
    a_lancer = _engagement(socle, seance, echeance=date(2030, 1, 1))
    en_retard = _engagement(socle, seance, objet="Echu", echeance=hier)

    etats = {v.id: v.etat_affiche for v in VueEngagementEtat.objects.all()}
    assert etats[a_lancer.pk] == "a_lancer"
    assert etats[en_retard.pk] == "en_retard"


def test_un_engagement_suspendu_n_est_pas_en_retard(socle, seance):
    """Reprocher un retard a une structure a qui une autorite a interdit
    d'avancer serait faux — meme regle que pour les activites."""
    from django.utils import timezone

    hier = date.today() - timedelta(days=1)
    engagement = _engagement(socle, seance, echeance=hier)
    with acteur(socle["dg"]):
        Engagement.objects.filter(pk=engagement.pk).update(
            suspendu_le=timezone.now(),
            suspendu_par=socle["dg"],
            motif_suspension="Arbitrage budgetaire",
        )
    assert VueEngagementEtat.objects.get(pk=engagement.pk).etat_affiche == "suspendu"


def test_une_suspension_sans_motif_est_refusee(socle, seance):
    from django.utils import timezone

    engagement = _engagement(socle, seance)
    with pytest.raises(IntegrityError), acteur(socle["dg"]):
        Engagement.objects.filter(pk=engagement.pk).update(suspendu_le=timezone.now())


def test_un_jalon_echu_distingue_le_retard_de_l_oubli(socle, seance):
    """C'est le meme raisonnement que la criticite du §20."""
    hier = date.today() - timedelta(days=1)
    engagement = _engagement(socle, seance, echeance=hier)
    assert VueEngagementEtat.objects.get(pk=engagement.pk).jalon_echu is False

    EngagementJalon.objects.create(
        engagement=engagement, libelle="Remettre le cahier des charges", echeance=hier
    )
    assert VueEngagementEtat.objects.get(pk=engagement.pk).jalon_echu is True


def test_les_relances_se_comptent(socle, seance):
    """Une decision relancee trois fois est un signal. D'ou le drapeau plutot
    qu'une seconde table : les deux s'affichent dans le meme fil."""
    engagement = _engagement(socle, seance)
    EngagementObservation.objects.create(
        engagement=engagement, texte="Point d'etape", auteur=socle["dsr"]
    )
    EngagementObservation.objects.create(
        engagement=engagement,
        texte="Merci de rendre compte",
        relance=True,
        auteur=socle["dsr"],
    )
    assert VueEngagementEtat.objects.get(pk=engagement.pk).relances == 1


# =====================================================================
#  Disponibilite
# =====================================================================


def test_deux_absences_ne_se_chevauchent_pas(socle):
    """
    Contrainte d'exclusion GiST, au moteur. Deux absences simultanees
    rendraient la question « qui le remplace ? » sans reponse, et aucun code
    applicatif ne tient cette garantie sous concurrence.
    """
    Disponibilite.objects.create(
        utilisateur=socle["dg"],
        type_absence="mission",
        du=date(2026, 7, 1),
        au=date(2026, 7, 15),
        saisi_par=socle["dsr"],
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Disponibilite.objects.create(
            utilisateur=socle["dg"],
            type_absence="conge_annuel",
            du=date(2026, 7, 10),
            au=date(2026, 7, 20),
            saisi_par=socle["dsr"],
        )


def test_deux_absences_qui_se_suivent_sont_acceptees(socle):
    """Le chevauchement, pas la contiguite : un retour de mission suivi d'un
    conge est un cas ordinaire."""
    Disponibilite.objects.create(
        utilisateur=socle["dg"],
        type_absence="mission",
        du=date(2026, 7, 1),
        au=date(2026, 7, 15),
        saisi_par=socle["dsr"],
    )
    Disponibilite.objects.create(
        utilisateur=socle["dg"],
        type_absence="conge_annuel",
        du=date(2026, 7, 16),
        au=date(2026, 7, 31),
        saisi_par=socle["dsr"],
    )
    assert Disponibilite.objects.filter(utilisateur=socle["dg"]).count() == 2


def test_on_ne_se_remplace_pas_soi_meme(socle):
    with pytest.raises(IntegrityError), transaction.atomic():
        Disponibilite.objects.create(
            utilisateur=socle["dg"],
            type_absence="mission",
            du=date(2026, 7, 1),
            au=date(2026, 7, 15),
            interimaire=socle["dg"],
            saisi_par=socle["dsr"],
        )


# =====================================================================
#  Conges et representations
# =====================================================================


def test_un_conge_reporte_sans_motif_est_refuse(socle):
    """Le directeur resoumettrait la meme periode. Meme regle que le renvoi
    d'un plan d'actions."""
    droit = CongeDroit.objects.create(utilisateur=socle["dg"], annee=2026)
    with pytest.raises(IntegrityError), transaction.atomic():
        CongePeriode.objects.create(
            conge_droit=droit,
            du=date(2026, 8, 1),
            au=date(2026, 8, 20),
            etat=CongePeriode.REPORTE,
        )


def test_on_ne_participe_pas_a_plus_de_reunions_qu_il_n_y_en_a(socle):
    """Un taux de participation superieur a 100 % ne signalerait rien : il
    ferait douter de tout le reste de l'ecran."""
    organisation = OrganisationExterne.objects.create(
        sigle="AGPAOC", libelle="Association", nature="organisation_portuaire"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Representation.objects.create(
            organisation_externe=organisation,
            representant=socle["dg"],
            mandat_du=date(2026, 1, 1),
            mandat_au=date(2028, 12, 31),
            reunions_tenues=4,
            reunions_participees=6,
        )


def test_un_organe_ne_recoit_pas_plus_de_documents_qu_il_n_en_attend(socle):
    entite = EntiteExterne.objects.create(
        sigle="SEPBC",
        libelle="Societe d'exploitation",
        nature="filiale",
        valide_du=date(2026, 1, 1),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganeGestion.objects.create(
            entite_externe=entite,
            organe="assemblee_generale",
            documents_attendus=3,
            documents_recus=5,
        )


# =====================================================================
#  Le lien avec les activites — ce que le renommage devait preserver
# =====================================================================


def test_un_engagement_peut_toujours_suspendre_une_activite(socle, seance):
    """
    ADR 006. Une decision du CODIR qui suspend une activite reste **la meme
    ligne** que celle que la gouvernance suit — c'est toute la raison d'avoir
    renomme la table plutot que d'en creer une seconde.
    """
    from datetime import date as _date

    from activite.modeles import Activite, ActiviteSuspension, AxeStrategique, Exercice, PlanActions

    engagement = _engagement(socle, seance)
    plan = PlanActions.objects.create(
        structure=socle["dsi"], exercice=Exercice.objects.get(ouvert=True)
    )
    activite = Activite.objects.create(
        plan=plan,
        axe_strategique=AxeStrategique.objects.get(code="A1"),
        intitule="Refonte du reseau",
        responsable=socle["dsr"],
        date_debut=_date(2026, 1, 1),
        date_fin=_date(2026, 12, 31),
    )

    with acteur(socle["dg"]):
        ActiviteSuspension.objects.create(
            activite=activite,
            decision_reunion=engagement,
            motif="Decision du CODIR du 12 juin",
            suspendu_par=socle["dg"],
        )

    activite.refresh_from_db()
    assert activite.etat == Activite.SUSPENDUE
    assert activite.suspensions.first().decision_reunion_id == engagement.pk

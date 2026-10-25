"""
Les rapports periodiques et leur export — `/api/pilotage/rapports*`, D-03.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **Un rapport ne change plus une fois la periode close.** C'est ce qui le
    distingue d'un tableau de bord, et c'est la regression invisible : un
    document date dont les chiffres bougent apres coup ne se verifie pas, il se
    conteste. D'ou les tests de bornes — une obligation echue apres la periode
    ne doit pas entrer dans le rapport, meme si elle est en retard aujourd'hui.
 2. **Le perimetre ne se contourne pas par une adresse.** Un sigle hors portee
    rend 404 (D5), et une portee bornee ne consolide jamais « l'institution ».
 3. **L'export laisse une trace.** Sortir une donnee du systeme est un acte
    (§3.12) ; un export non trace est exactement ce qu'un audit cherche a
    detecter et ne trouverait pas.
 4. **« Non mesuré » n'est pas zero** — ADR 011, comme partout ailleurs dans le
    pilotage.
"""

from datetime import date

import pytest
from django.core.management import call_command

from activite.modeles import CalendrierProduction, Obligation
from noyau.identite.modeles import Utilisateur
from noyau.journal.modeles import JournalAcces
from noyau.organisation.modeles import Structure
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache
from pilotage import periodes

BACKEND = "noyau.identite.authentification.BackendAnnuaire"

RAPPORTS = "/api/pilotage/rapports"
EXPORT = "/api/pilotage/rapports/export"


@pytest.fixture(autouse=True)
def parametres_neufs():
    vider_cache()
    yield
    vider_cache()


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


def _obligation(sigle: str, echeance: date, depose_le: date | None = None) -> Obligation:
    """Une production attendue, engendree depuis son calendrier — jamais seule."""
    structure = Structure.objects.en_vigueur().get(code=sigle)
    calendrier, _ = CalendrierProduction.objects.get_or_create(
        structure=structure,
        nature="rapport_mensuel",
        defaults={
            "intitule": "Rapport mensuel d'activité",
            "periodicite": "mensuelle",
            "valide_du": date(echeance.year - 2, 1, 1),
        },
    )
    # La periode est celle du mois de l'echeance, et non un decalage calcule :
    # le socle interdit deux obligations pour la meme periode d'un calendrier
    # (`obligation_unique_par_periode`), et un rapport trimestriel en cree trois
    # d'affilee.
    debut = echeance.replace(day=1)

    return Obligation.objects.create(
        calendrier_production=calendrier,
        structure=structure,
        intitule="Rapport mensuel d'activité",
        periode_libelle=f"{debut.month:02d}/{debut.year}",
        periode_debut=debut,
        periode_fin=echeance,
        echeance=echeance,
        depose_le=depose_le,
        depose_par=(Utilisateur.objects.get(identifiant_annuaire="dsr") if depose_le else None),
    )


def _lignes(corps: dict, titre: str) -> dict[str, dict]:
    """Les lignes d'une section, indexees par libelle — les tests se lisent mieux."""
    section = next(s for s in corps["sections"] if s["titre"] == titre)
    return {ligne["libelle"]: ligne for ligne in section["lignes"]}


# =====================================================================
#  Les periodes
#
#  Du calendrier, a une exception pres : le mois d'ouverture de l'exercice est
#  un parametre (A52). D'ou `django_db` sans semis — la table `parametre` est
#  vide, et `valeur()` rend le defaut, qui est justement ce qu'on veut verifier.
# =====================================================================


def test_la_derniere_periode_close_n_est_pas_celle_en_cours(db):
    """
    Le 14 aout, le dernier mois clos est juillet.

    C'est toute la difference avec un tableau de bord : un rapport d'aout
    edite le 14 aurait couvert quatorze jours en en portant trente et un.
    """
    periode = periodes.derniere_close(periodes.MOIS, aujourd_hui=date(2026, 8, 14))

    assert periode.annee == 2026
    assert periode.rang == 7
    assert periode.debut == date(2026, 7, 1)
    assert periode.fin == date(2026, 7, 31)
    assert periode.libelle == "Juillet 2026"


def test_en_janvier_la_derniere_periode_close_est_dans_l_annee_precedente(db):
    """Le passage d'annee : le rang 0 n'existe pas, il vaut le dernier de N-1."""
    mois = periodes.derniere_close(periodes.MOIS, aujourd_hui=date(2026, 1, 9))
    trimestre = periodes.derniere_close(periodes.TRIMESTRE, aujourd_hui=date(2026, 1, 9))

    assert (mois.annee, mois.rang) == (2025, 12)
    assert (trimestre.annee, trimestre.rang) == (2025, 4)
    assert trimestre.debut == date(2025, 10, 1)


def test_le_trimestre_en_cours_est_ramene_au_precedent(db):
    """
    Demander une periode non close n'est pas une erreur : elle est ramenee.

    Repondre 400 aurait casse un lien partage la veille d'une cloture, sans que
    personne n'ait rien fait de mal. C'est le raisonnement de l'ADR 009,
    applique au temps.
    """
    periode, ramenee = periodes.resoudre(periodes.TRIMESTRE, 2026, 3, aujourd_hui=date(2026, 8, 14))

    assert ramenee is True
    assert (periode.annee, periode.rang) == (2026, 2)
    assert periode.libelle == "2e trimestre 2026 (avril à juin)"


def test_une_periode_close_demandee_est_servie_telle_quelle(db):
    periode, ramenee = periodes.resoudre(periodes.TRIMESTRE, 2026, 1, aujourd_hui=date(2026, 8, 14))

    assert ramenee is False
    assert periode.code == "2026-T1"
    assert (periode.debut, periode.fin) == (date(2026, 1, 1), date(2026, 3, 31))


def test_l_exercice_precedent_est_l_annee_d_avant(db):
    exercice = periodes.derniere_close(periodes.ANNEE, aujourd_hui=date(2026, 8, 14))

    assert exercice.libelle == "Exercice 2025"
    assert periodes.precedente(exercice).libelle == "Exercice 2024"


def test_l_exercice_s_ouvre_en_janvier_par_defaut(jeu):
    """
    La valeur semee est 1, et c'est une **hypothese** (A52).

    Le test la lit en base plutot que de la supposer : le jour ou une direction
    tranchera pour juillet, c'est ce test qui dira que les rapports ont change
    de bornes — plutot qu'un lecteur de rapport, trois mois plus tard.
    """
    assert Parametre.objects.get(cle="pilotage.mois_debut_exercice").statut == "hypothese"
    assert periodes.mois_debut_exercice() == 1


def test_un_exercice_ouvert_en_juillet_decale_tout(jeu):
    """
    Le premier trimestre de l'exercice devient juillet-septembre.

    C'est la raison d'etre du parametre : avec une annee civile ecrite en dur,
    un rapport trimestriel du Port aurait porte le bon titre et les mauvaises
    dates — l'erreur la plus difficile a voir sur un document qu'on transmet.
    """
    Parametre.objects.filter(cle="pilotage.mois_debut_exercice").update(valeur="7")
    vider_cache()

    # Le 5 juillet 2027 : l'exercice 2026 est entierement clos, ses quatre
    # trimestres sont demandables. Un jour plus tot, le quatrieme aurait ete
    # ramene au troisieme — il n'etait pas fini.
    premier = periodes.resoudre(periodes.TRIMESTRE, 2026, 1, aujourd_hui=date(2027, 7, 5))[0]
    dernier = periodes.resoudre(periodes.TRIMESTRE, 2026, 4, aujourd_hui=date(2027, 7, 5))[0]

    assert (premier.debut, premier.fin) == (date(2026, 7, 1), date(2026, 9, 30))
    # Le quatrieme trimestre de l'exercice 2026 tombe en 2027 : c'est ce qu'un
    # calcul cale sur l'annee civile aurait rate.
    assert (dernier.debut, dernier.fin) == (date(2027, 4, 1), date(2027, 6, 30))


def test_une_granularite_inconnue_vaut_le_mois(db):
    """Une faute de frappe dans une adresse ne doit pas sortir un rapport annuel."""
    periode, _ = periodes.resoudre("decennie", aujourd_hui=date(2026, 8, 14))

    assert periode.granularite == periodes.MOIS


# =====================================================================
#  Les gardes
# =====================================================================


@pytest.mark.parametrize("chemin", [RAPPORTS, EXPORT])
def test_sans_session_aucun_rapport_ne_sort(client, jeu, chemin):
    assert client.get(chemin).status_code == 401


@pytest.mark.parametrize("chemin", [RAPPORTS, EXPORT])
def test_un_collaborateur_sans_lecture_d_activite_n_a_pas_de_rapport(connecte, chemin):
    """`agent.dsi` porte COLLAB : ni ACT_LEC ni STAT."""
    assert connecte("agent.dsi").get(chemin).status_code == 401


def test_le_controle_de_gestion_sort_le_rapport_de_l_institution(connecte):
    corps = connecte("dcg").get(RAPPORTS).json()

    assert corps["perimetre"] == "institution"
    assert corps["perimetreLibelle"] == "Ensemble de l'institution"
    assert corps["peutVoirInstitution"] is True


def test_un_point_focal_ne_consolide_jamais_l_institution(connecte):
    """
    Sa portee est `structure` : demander l'institution la lui rendrait sous un
    nom qui n'est pas le sien. Le serveur ramene, et le dit.
    """
    corps = connecte("focal.dsi").get(f"{RAPPORTS}?perimetre=institution").json()

    assert corps["perimetre"] == "structure"
    assert corps["structureSigle"] == "DSI"
    assert corps["peutVoirInstitution"] is False


def test_une_structure_hors_perimetre_est_introuvable(connecte):
    """404 et non 403 : repondre « pas le droit » confirmerait l'existence (D5)."""
    assert connecte("focal.dsi").get(f"{RAPPORTS}?structure=DAF").status_code == 404


# =====================================================================
#  Le contenu — ce qui est borne a la periode
# =====================================================================


def test_une_obligation_echue_apres_la_periode_n_y_entre_pas(connecte):
    """
    La borne haute. Sans elle, le rapport de mars grossirait chaque mois.
    """
    _obligation("DSI", date(2026, 3, 10), depose_le=date(2026, 3, 9))
    _obligation("DSI", date(2026, 5, 10))

    corps = connecte("focal.dsi").get(f"{RAPPORTS}?periode=mois&annee=2026&rang=3").json()
    lignes = _lignes(corps, "Rituels de production")

    assert lignes["Productions attendues"]["valeur"] == "1"
    assert lignes["Déposées à l'échéance"]["valeur"] == "1 / 1"
    assert lignes["Jamais déposées à ce jour"]["valeur"] == "0"


def test_une_obligation_deposee_en_retard_reste_a_sa_periode(connecte):
    """
    Bornee a l'echeance, pas au depot. Rattacher la production au mois du depot
    aurait fait disparaitre le retard du rapport de mars — et un retard qui
    s'efface tout seul n'est jamais corrige.
    """
    _obligation("DSI", date(2026, 3, 10), depose_le=date(2026, 4, 2))

    corps = connecte("focal.dsi").get(f"{RAPPORTS}?periode=mois&annee=2026&rang=3").json()
    lignes = _lignes(corps, "Rituels de production")

    assert lignes["Productions attendues"]["valeur"] == "1"
    assert lignes["Déposées à l'échéance"]["valeur"] == "0 / 1"


def test_un_trimestre_agrege_ses_trois_mois(connecte):
    _obligation("DSI", date(2026, 1, 10), depose_le=date(2026, 1, 9))
    _obligation("DSI", date(2026, 2, 10), depose_le=date(2026, 2, 15))
    _obligation("DSI", date(2026, 3, 10), depose_le=date(2026, 3, 1))

    corps = connecte("focal.dsi").get(f"{RAPPORTS}?periode=trimestre&annee=2026&rang=1").json()
    lignes = _lignes(corps, "Rituels de production")

    assert corps["periode"]["code"] == "2026-T1"
    assert lignes["Déposées à l'échéance"]["valeur"] == "2 / 3"


def test_sans_production_attendue_le_taux_n_est_pas_a_zero(connecte):
    """ADR 011 : aucune echeance dans la periode ne fait pas 0 % de ponctualite."""
    corps = connecte("focal.dsi").get(f"{RAPPORTS}?periode=mois&annee=2026&rang=2").json()
    lignes = _lignes(corps, "Rituels de production")

    assert lignes["Déposées à l'échéance"]["valeur"] == "Aucune attendue"
    assert lignes["Déposées à l'échéance"]["feu"] == "inconnu"
    assert lignes["Déposées à l'échéance"]["variation"] is None


def test_le_courrier_occupe_une_section_plutot_que_de_disparaitre(connecte):
    """
    Un rapport a quatre sections chez l'un et cinq chez l'autre se lit comme une
    panne ; l'absence, elle, est la meme pour tout le monde.

    Depuis l'ADR 036 la section se mesure : deux volumes, qui rendent zero sans
    etat d'ame, et un taux, qui rend « Non mesuré » tant qu'aucun courrier n'a
    ete cloture — jamais zero pour cent (ADR 011).
    """
    corps = connecte("dcg").get(RAPPORTS).json()
    lignes = _lignes(corps, "Courrier")

    assert lignes["Courriers enregistrés"]["valeur"] == "0"
    assert lignes["Courriers clôturés"]["valeur"] == "0"
    assert lignes["Courriers traités dans le délai"]["valeur"] == "Non mesuré"
    assert lignes["Courriers traités dans le délai"]["feu"] == "inconnu"
    assert corps["nonMesure"] == []


def test_le_rapport_nomme_la_periode_de_comparaison(connecte):
    """Un rapport sans comparaison est une photographie, pas un instrument."""
    corps = connecte("dcg").get(f"{RAPPORTS}?periode=trimestre&annee=2026&rang=1").json()

    assert corps["comparaison"] == "4e trimestre 2025 (octobre à décembre)"


def test_le_rapport_dit_qu_il_a_ete_ramene(connecte):
    corps = connecte("dcg").get(f"{RAPPORTS}?periode=annee&annee=2030&rang=1").json()

    assert corps["periodeRamenee"] is True
    assert corps["periode"]["granularite"] == "annee"


# =====================================================================
#  L'export
# =====================================================================


def test_l_export_sert_un_csv_nomme(connecte):
    reponse = connecte("focal.dsi").get(f"{EXPORT}?periode=trimestre&annee=2026&rang=1")

    assert reponse.status_code == 200
    assert reponse["Content-Type"] == "text/csv; charset=utf-8"
    assert 'filename="rapport-DSI-2026-T1.csv"' in reponse["Content-Disposition"]


def test_le_csv_commence_par_un_bom_et_separe_au_point_virgule(connecte):
    """
    Sans BOM, Excel lit le fichier en ANSI et affiche « ActivitÃ©s » : le
    rapport parait faux alors qu'il est juste, et personne ne le rouvre.
    """
    contenu = connecte("dcg").get(EXPORT).content.decode("utf-8")

    assert contenu.startswith("﻿")
    assert "Section;Indicateur;Valeur;Évolution;Précision" in contenu
    assert "Activités;" in contenu


def test_le_csv_ouvre_sur_l_entete_institutionnel(connecte):
    """
    Un rapport exporte circule hors de l'application : sans en-tete, rien ne
    dit de quelle institution il sort. C'est le modele `Entête DSR à utiliser`,
    en version texte — bilingue comme l'exigent les actes au Cameroun.
    """
    contenu = connecte("dcg").get(EXPORT).content.decode("utf-8")
    premieres = contenu.lstrip("﻿").splitlines()[:5]

    assert premieres[0] == "République du Cameroun;Republic of Cameroon"
    assert premieres[2] == "Port autonome de Douala (P.A.D);Port Authority of Douala (P.A.D)"
    assert premieres[4].startswith("Division du suivi et de la relance;")


def test_le_csv_porte_les_memes_lignes_que_l_ecran(connecte):
    """
    Le meme contenu, dans le meme ordre. Un export qui divergerait de l'ecran
    obligerait a se demander lequel dit vrai.
    """
    session = connecte("dcg")
    corps = session.get(f"{RAPPORTS}?periode=mois&annee=2026&rang=3").json()
    contenu = session.get(f"{EXPORT}?periode=mois&annee=2026&rang=3").content.decode("utf-8")

    attendues = [ligne["libelle"] for section in corps["sections"] for ligne in section["lignes"]]
    positions = [contenu.index(libelle) for libelle in attendues]

    assert positions == sorted(positions)


def test_l_export_est_trace_comme_une_sortie_de_donnees(connecte):
    """
    §3.12 : sortir une donnee du systeme est un acte, quel que soit son volume.
    Un tableur fabrique par le navigateur n'aurait laisse aucune trace.
    """
    avant = JournalAcces.objects.filter(objet_type="rapport_pilotage").count()

    connecte("dcg").get(EXPORT)

    lignes = JournalAcces.objects.filter(objet_type="rapport_pilotage")
    assert lignes.count() == avant + 1
    assert lignes.order_by("-survenu_le").first().action == "export"


def test_consulter_le_rapport_a_l_ecran_ne_trace_rien(connecte):
    """
    La contrepartie du test precedent. Tracer chaque ouverture d'un tableau de
    bord aurait noye le journal sous des lignes que personne n'aurait relues —
    et c'est l'export qu'on y cherche.
    """
    connecte("dcg").get(RAPPORTS)

    assert JournalAcces.objects.filter(objet_type="rapport_pilotage").count() == 0

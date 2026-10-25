"""
Les restitutions du pilotage — `/api/pilotage/*`, `/api/direction/*`,
`/api/comite/*`.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **« Non mesuré » n'est pas zero.** C'est l'ADR 011, et c'est la seule
    regression qui ne se voit pas : un taux a 0 % s'affiche comme un echec, se
    commente en seance, et personne ne remarque qu'aucune donnee ne le
    soutenait. Plusieurs tests ci-dessous ne verifient rien d'autre.
 2. **Le perimetre ne se contourne pas par une adresse.** Le tableau de bord
    d'une structure hors perimetre rend 404 (D5), et le perimetre demande est
    ramene a ce que la portee permet plutot que refuse (ADR 009).
 3. **Les gardes sont posees.** Une route de pilotage sans `auth=exige(...)`
    ne produit aucune erreur : elle ouvre les chiffres de l'institution.
 4. **Le cockpit tient sur un ecran.** Le plafond d'alertes est une regle de
    serveur, pas une regle de CSS.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from activite.modeles import CalendrierProduction, Obligation
from exploitation.modeles import PointChenal, ReleveChenal
from gouvernance.modeles import Disponibilite
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache
from pilotage.modeles import IndicateurProgramme, MesureProgramme

BACKEND = "noyau.identite.authentification.BackendAnnuaire"

COCKPIT = "/api/pilotage/cockpit"
SYNTHESE = "/api/pilotage/synthese"
STRUCTURES = "/api/pilotage/structures"
TABLEAU = "/api/pilotage/tableau-de-bord"
STATISTIQUES = "/api/pilotage/statistiques"
ANALYSES = "/api/pilotage/analyses"
PROGRAMME = "/api/pilotage/programme"
VUE_DIRECTION = "/api/direction/vue-ensemble"
VUE_COMITE = "/api/comite/vue-ensemble"


@pytest.fixture(autouse=True)
def parametres_neufs():
    """
    Le cache des parametres vit dans le process, pas dans la transaction.

    Sans ce vidage, un test qui modifie un seuil le laisserait en cache pour
    tous les suivants, alors que la base a ete rendue a son etat initial. Le
    symptome serait un test qui passe seul et echoue en suite complete — le
    genre d'echec qu'on met une demi-journee a comprendre.
    """
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
    """
    Une production attendue du calendrier officiel.

    Une obligation est **engendree depuis le calendrier, jamais saisie a la
    main** : le test cree donc la ligne de calendrier qui la porte, plutot que
    de la detacher de sa source.
    """
    structure = Structure.objects.en_vigueur().get(code=sigle)
    calendrier, _ = CalendrierProduction.objects.get_or_create(
        structure=structure,
        nature="rapport_mensuel",
        defaults={
            "intitule": "Rapport mensuel d'activité",
            "periodicite": "mensuelle",
            "valide_du": date(echeance.year - 1, 1, 1),
        },
    )
    # Une periode par obligation : le socle interdit deux obligations pour la
    # meme periode d'un meme calendrier (`obligation_unique_par_periode`), et
    # c'est bien ce qu'il doit faire.
    rang = Obligation.objects.filter(calendrier_production=calendrier).count()
    debut = echeance.replace(day=1) - timedelta(days=31 * rang)

    return Obligation.objects.create(
        calendrier_production=calendrier,
        structure=structure,
        intitule="Rapport mensuel d'activité",
        periode_libelle=f"{debut.month:02d}/{debut.year}",
        periode_debut=debut,
        periode_fin=echeance,
        echeance=echeance,
        depose_le=depose_le,
        # `obligation_depot_complet` exige les deux ensemble : un depot sans
        # deposant ne se conteste pas.
        depose_par=(Utilisateur.objects.get(identifiant_annuaire="dsr") if depose_le else None),
    )


# =====================================================================
#  Les gardes
#
#  Une route de restitution sans garde ne casse rien : elle ouvre. D'ou un
#  test par route, et non un test « les routes sont gardees ».
# =====================================================================


@pytest.mark.parametrize(
    "chemin",
    [
        COCKPIT,
        SYNTHESE,
        STRUCTURES,
        TABLEAU,
        STATISTIQUES,
        ANALYSES,
        PROGRAMME,
        VUE_DIRECTION,
        VUE_COMITE,
    ],
)
def test_sans_session_aucune_restitution_ne_repond(client, jeu, chemin):
    assert client.get(chemin).status_code == 401


def test_le_cockpit_est_ferme_a_qui_ne_le_porte_pas(connecte):
    """`agent.dsi` lit ses dossiers ; il ne lit pas l'institution."""
    assert connecte("agent.dsi").get(COCKPIT).status_code == 401


def test_les_analyses_sont_fermees_sans_permission_statistique(connecte):
    assert connecte("agent.dsi").get(ANALYSES).status_code == 401


def test_la_vue_du_comite_est_fermee_au_directeur_general(connecte):
    """
    Le Directeur general porte VUE_DG et **pas** VUE_CODIR.

    Ce n'est pas un oubli : ce sont deux restitutions de deux instances, et
    celle du Comite est celle du college des directeurs — pas celle de son
    president.
    """
    assert connecte("dg").get(VUE_COMITE).status_code == 401


def test_la_vue_de_la_direction_generale_est_fermee_au_comite(connecte):
    assert connecte("dir.daf").get(VUE_DIRECTION).status_code == 401


# =====================================================================
#  Le cockpit executif — §3.1
# =====================================================================


def test_le_cockpit_repond_sans_aucune_donnee(connecte):
    """
    Un depot fraichement seme n'a ni activite ni decision. Le cockpit doit
    neanmoins s'ouvrir : un ecran d'accueil qui plante au premier jour de mise
    en service ne sera jamais rouvert.
    """
    corps = connecte("dg").get(COCKPIT).json()

    assert corps["decisionsEnRetard"] == 0
    assert corps["alertes"] == []
    assert len(corps["indicateurs"]) == 4


def test_le_cockpit_dit_ce_qu_il_ne_mesure_pas(connecte):
    """Le courrier occupe une ligne entiere plutot que de disparaitre."""
    indicateurs = connecte("dg").get(COCKPIT).json()["indicateurs"]
    courrier = next(i for i in indicateurs if i["libelle"] == "Traitement du courrier")

    assert courrier["valeur"] == "Non mesuré"
    assert courrier["variation"] is None
    assert courrier["favorable"] is None


def test_une_execution_absente_ne_produit_aucune_variation(connecte):
    """
    Une fleche contre une mesure absente serait une progression inventee.
    C'est l'ADR 011, et c'est ce qui distingue `null` de zero.
    """
    indicateurs = connecte("dg").get(COCKPIT).json()["indicateurs"]
    execution = next(i for i in indicateurs if i["libelle"] == "Exécution des activités")

    assert execution["valeur"] == "Non mesuré"
    assert execution["variation"] is None


def test_les_alertes_ne_debordent_pas_de_l_ecran(connecte):
    """
    « Un seul ecran » est une contrainte de serveur avant d'etre une contrainte
    de mise en page : quarante alertes font defiler l'ecran quoi qu'en dise le
    CSS.
    """
    from pilotage.cockpit import PLAFOND_ALERTES

    hier = date.today() - timedelta(days=3)
    for numero in range(PLAFOND_ALERTES + 5):
        obligation = _obligation("DSI", hier)
        obligation.intitule = f"Production {numero}"
        obligation.save(update_fields=["intitule"])

    corps = connecte("dg").get(COCKPIT).json()
    assert len(corps["alertes"]) <= PLAFOND_ALERTES


# =====================================================================
#  Le tableau de bord d'une structure — §3.4 et §3.5
# =====================================================================


def test_sans_sigle_l_agent_recoit_sa_structure(connecte):
    corps = connecte("focal.dsi").get(STRUCTURES).json()
    assert corps["structureSigle"] == "DSI"


def test_une_structure_hors_perimetre_est_introuvable(connecte):
    """
    404 et non 403 (D5) : repondre « vous n'avez pas le droit » confirmerait
    l'existence de la structure et de ses chiffres a qui n'a pas a les
    connaitre.
    """
    assert connecte("focal.dsi").get(f"{STRUCTURES}?sigle=DAF").status_code == 404


def test_le_selecteur_ne_propose_que_le_perimetre(connecte):
    """C'est le serveur qui decide si le selecteur apparait, pas le front."""
    corps = connecte("focal.dsi").get(STRUCTURES).json()
    sigles = [s["sigle"] for s in corps["structuresAccessibles"]]

    assert sigles == ["DSI"]


def test_un_responsable_voit_sa_branche(connecte):
    corps = connecte("dir.dsi").get(STRUCTURES).json()
    sigles = [s["sigle"] for s in corps["structuresAccessibles"]]

    assert "DSI" in sigles and "DSI-ET" in sigles
    assert "DAF" not in sigles


def test_le_bloc_courrier_est_servi_avec_sa_raison(connecte):
    """
    Vide, il aurait laisse croire que la structure ne recoit aucun courrier ;
    omis, il aurait fait croire a une panne d'affichage.
    """
    corps = connecte("focal.dsi").get(STRUCTURES).json()

    assert len(corps["courrier"]) == 2
    assert all(bloc["valeur"] == "Non mesuré" for bloc in corps["courrier"])
    assert all(bloc["feu"] == "inconnu" for bloc in corps["courrier"])
    assert all(bloc["note"] for bloc in corps["courrier"])


def test_une_production_en_retard_appelle_une_action_nommee(connecte):
    """« 3 obligations en retard » n'appelle aucun geste ; une ligne nommee si."""
    _obligation("DSI", date.today() - timedelta(days=10))

    corps = connecte("focal.dsi").get(STRUCTURES).json()
    lignes = corps["aTraiter"]

    assert any("Rapport mensuel" in ligne["libelle"] for ligne in lignes)
    assert all(ligne["chemin"] for ligne in lignes)


def test_une_structure_non_classee_n_a_pas_de_rang_invente(connecte):
    """
    Toutes les structures ne sont pas classees : seules celles dont le niveau
    hierarchique porte `ligne_statistiques`. Un rang invente pour un service
    aurait ete lu comme un rang reel.
    """
    service = Structure.objects.en_vigueur().get(code="DSI-ET")
    niveau = service.niveau_hierarchique
    niveau.ligne_statistiques = False
    niveau.save(update_fields=["ligne_statistiques"])

    reponse = connecte("dir.dsi").get(f"{STRUCTURES}?sigle=DSI-ET")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["structureSigle"] == "DSI-ET"
    assert corps["rang"] is None
    assert corps["scoreGlobal"] is None


# =====================================================================
#  Le tableau de bord et ses trois perimetres
# =====================================================================


def test_le_perimetre_demande_trop_large_est_ramene_et_dit(connecte):
    """
    Un onglet reste ouvert apres un changement d'habilitation n'est pas une
    tentative d'intrusion. Le serveur ramene, il ne refuse pas (ADR 009).
    """
    corps = connecte("focal.dsi").get(f"{TABLEAU}?perimetre=institution").json()

    assert corps["perimetreDemande"] == "institution"
    assert corps["perimetreApplique"] == "structure"
    assert corps["perimetreLibelle"]


def test_une_portee_propre_ne_voit_que_ses_dossiers(connecte):
    """
    `agent.dsi` entre par `DOS_LEC` et non par `ACT_LEC` : il instruit des
    dossiers sans lire de plan d'actions. Sa portee `propre` ramene tout
    perimetre demande a « mes dossiers ».
    """
    corps = connecte("agent.dsi").get(f"{TABLEAU}?perimetre=institution").json()
    assert corps["perimetreApplique"] == "mesDossiers"


def test_le_directeur_general_regarde_l_institution(connecte):
    corps = connecte("dg").get(f"{TABLEAU}?perimetre=institution").json()

    assert corps["perimetreApplique"] == "institution"
    assert corps["perimetreLibelle"] == "Port autonome de Douala"


def test_un_perimetre_inconnu_vaut_le_plus_restreint(connecte):
    """Une faute de frappe dans une adresse n'ouvre pas l'institution."""
    corps = connecte("focal.dsi").get(f"{TABLEAU}?perimetre=tout").json()
    assert corps["perimetreApplique"] == "mesDossiers"


def test_la_periode_change_l_amplitude_de_la_serie(connecte):
    mois = connecte("dg").get(f"{TABLEAU}?periode=mois").json()
    annee = connecte("dg").get(f"{TABLEAU}?periode=annee").json()

    assert len(mois["serie"]) == 1
    assert len(annee["serie"]) == 12


def test_le_taux_de_respect_est_nul_faute_d_echeance_passee(connecte):
    """`null`, et non 0 % : aucune production n'etait attendue."""
    corps = connecte("dg").get(TABLEAU).json()
    assert corps["tauxRespect"] is None


def test_le_tableau_de_bord_nomme_ce_qui_est_en_retard(connecte):
    _obligation("DSI", date.today() - timedelta(days=7))

    corps = connecte("dg").get(TABLEAU).json()
    assert corps["retards"]
    assert corps["retards"][0]["structure"] == "DSI"
    assert corps["retards"][0]["retardJours"] == 7


# =====================================================================
#  Statistiques annuelles
# =====================================================================


def test_les_statistiques_sont_filtrees_au_perimetre(connecte):
    """
    Contrairement aux analyses croisees : elles descendent au detail d'une
    structure, et le §3.5 interdit au point focal de voir celles des autres.
    """
    corps = connecte("dir.dsi").get(STATISTIQUES).json()
    sigles = [ligne["sigle"] for ligne in corps["parStructure"]]

    assert "DSI" in sigles
    assert "DAF" not in sigles


def test_le_seuil_de_respect_vient_du_serveur(connecte):
    """Il etait ecrit en dur dans le front. Voir A31."""
    corps = connecte("dcg").get(STATISTIQUES).json()
    assert corps["seuilAttendu"] == 80


def test_le_seuil_de_respect_s_administre_sans_redeploiement(connecte):
    """
    Une valeur inventee qu'on ne peut pas corriger est une valeur qu'on finit
    par croire. Le seuil vit dans la table `parametre`, en `hypothese`.
    """
    Parametre.objects.filter(cle="pilotage.seuil_respect_echeances").update(valeur="95")
    vider_cache()  # le service met les parametres en cache pour tout le process

    corps = connecte("dcg").get(STATISTIQUES).json()
    assert corps["seuilAttendu"] == 95


def test_l_ecart_moyen_au_depot_est_positif_quand_on_depose_en_avance(connecte):
    echeance = date.today() - timedelta(days=5)
    _obligation("DSI", echeance, depose_le=echeance - timedelta(days=3))

    corps = connecte("dcg").get(STATISTIQUES).json()
    dsi = next(ligne for ligne in corps["parStructure"] if ligne["sigle"] == "DSI")

    assert dsi["ecartMoyen"] == 3.0
    assert dsi["respect"] == 100.0


def test_une_structure_sans_obligation_n_a_pas_de_taux_a_zero(connecte):
    corps = connecte("dcg").get(STATISTIQUES).json()
    lignes = [ligne for ligne in corps["parStructure"] if ligne["volume"] == 0]

    assert lignes
    assert all(ligne["respect"] is None for ligne in lignes)
    assert all(ligne["feu"] == "inconnu" for ligne in lignes)


def test_les_statistiques_n_ont_plus_rien_a_declarer_comme_absent(connecte):
    """
    La liste est vide depuis l'ADR 036, et le champ reste servi.

    Il portait trois lignes, puis deux quand le pilier dossiers a ete mis en
    service, puis zero quand la cloture a eu une route. Le retirer du schema
    aurait oblige a le reintroduire au prochain pilier — et, entre-temps, une
    absence n'aurait plus eu ou se dire (ADR 011).
    """
    corps = connecte("dcg").get(STATISTIQUES).json()

    assert corps["nonMesure"] == []


# =====================================================================
#  Analyses croisees — §3.11
# =====================================================================


def test_les_deux_mesures_absentes_sortent_a_null(connecte):
    """
    Quatre mesures attendues, deux disponibles. Zero aurait rendu toute
    l'institution mediocre, avec un ecart-type rassurant et faux.

    Les deux `null` ne disent plus la meme chose : le courrier n'a **aucun
    outil**, les dossiers n'ont **aucune matiere** sur ce jeu — aucun n'est
    clos. Les deux se corrigent differemment, et les notes des ecrans le
    distinguent.
    """
    corps = connecte("dcg").get(ANALYSES).json()

    assert corps["moyennes"]["courrier"] is None
    assert corps["moyennes"]["dossiers"] is None
    assert all(ligne["courrier"] is None for ligne in corps["lignes"])


def test_la_dispersion_ne_porte_que_sur_les_mesures_disponibles(connecte):
    """
    Une seule mesure disponible : aucune dispersion a constater, et non une
    dispersion nulle qu'on aurait pu comparer a celle d'une autre structure.
    """
    echeance = date.today() - timedelta(days=2)
    _obligation("DSI", echeance, depose_le=echeance)

    corps = connecte("dcg").get(ANALYSES).json()
    dsi = next(ligne for ligne in corps["lignes"] if ligne["sigle"] == "DSI")

    assert dsi["delais"] == 100.0
    assert dsi["activites"] is None
    assert dsi["dispersion"] == 0


def test_le_serveur_dit_lui_meme_que_l_analyse_est_incomplete(connecte):
    constats = connecte("dcg").get(ANALYSES).json()["constats"]
    assert any(constat["feu"] == "inconnu" for constat in constats)
    assert any(
        "mesure" in constat["texte"] or "mesurés" in constat["texte"] for constat in constats
    )


# =====================================================================
#  Indicateurs cibles du programme — §3.11 et §9
# =====================================================================


def test_les_quatre_indicateurs_sont_semes(connecte):
    corps = connecte("dcg").get(PROGRAMME).json()
    codes = [ligne["code"] for ligne in corps["indicateurs"]]

    assert codes == ["PROG-ACT", "PROG-RIT", "PROG-DEC", "PROG-COUR"]


def test_une_cible_non_fixee_ne_vaut_pas_zero(connecte):
    """
    Une cible inventee aurait ete lue comme un engagement de l'institution ;
    une cible a zero aurait ete atteinte d'avance. Voir A32.
    """
    corps = connecte("dcg").get(PROGRAMME).json()

    assert all(ligne["cible"] is None for ligne in corps["indicateurs"])
    assert all(ligne["feu"] == "inconnu" for ligne in corps["indicateurs"])


def test_un_indicateur_non_calculable_reste_non_mesure(connecte):
    corps = connecte("dcg").get(PROGRAMME).json()
    courrier = next(ligne for ligne in corps["indicateurs"] if ligne["code"] == "PROG-COUR")

    assert courrier["valeurN"] is None
    assert courrier["valeurN1"] is None


def test_une_valeur_rapportee_prime_sur_la_valeur_calculee(connecte):
    """
    C'est le rapporteur qui engage sa signature devant l'instance, pas le
    serveur. Le jour ou les deux divergent, c'est un ecart a expliquer.
    """
    indicateur = IndicateurProgramme.objects.get(code="PROG-DEC")
    MesureProgramme.objects.create(
        indicateur=indicateur, annee=date.today().year, valeur=Decimal("42.00")
    )

    corps = connecte("dcg").get(PROGRAMME).json()
    decisions = next(ligne for ligne in corps["indicateurs"] if ligne["code"] == "PROG-DEC")

    assert decisions["valeurN"] == 42.0


def test_la_cible_atteinte_se_colore_des_qu_elle_est_fixee(connecte):
    indicateur = IndicateurProgramme.objects.get(code="PROG-DEC")
    indicateur.cible = Decimal("10.00")
    indicateur.save(update_fields=["cible"])
    MesureProgramme.objects.create(
        indicateur=indicateur, annee=date.today().year, valeur=Decimal("12.00")
    )

    corps = connecte("dcg").get(PROGRAMME).json()
    decisions = next(ligne for ligne in corps["indicateurs"] if ligne["code"] == "PROG-DEC")

    assert decisions["feu"] == "vert"


def test_le_compteur_des_non_mesures_ouvre_la_liste(connecte):
    """
    Un tableau de bord du programme dont la moitie des lignes est vide doit
    l'annoncer avant d'annoncer ses reussites.
    """
    compteurs = connecte("dcg").get(PROGRAMME).json()["compteurs"]
    assert compteurs[0]["libelle"] == "Indicateurs non mesurés"


# =====================================================================
#  Note de synthese d'instance
# =====================================================================


def test_la_synthese_s_ecrit_sans_seance_programmee(connecte):
    corps = connecte("dg").get(SYNTHESE).json()

    assert corps["seance"] == "Aucune séance programmée"
    assert corps["faitsMarquants"]


def test_les_faits_marquants_sont_des_phrases(connecte):
    """
    Un lecteur en seance ne recompose pas « 62 » et « 71 » en « l'execution a
    progresse de neuf points ».
    """
    faits = connecte("dg").get(SYNTHESE).json()["faitsMarquants"]
    assert all(fait.endswith(".") for fait in faits)


def test_la_note_dit_ce_qu_elle_ne_mesure_pas(connecte):
    """Une note qui passerait le courrier sous silence le ferait croire sain."""
    faits = connecte("dg").get(SYNTHESE).json()["faitsMarquants"]
    assert any("courrier" in fait for fait in faits)


def test_sans_anomalie_la_note_le_dit_plutot_que_de_se_taire(connecte):
    points = connecte("dg").get(SYNTHESE).json()["pointsDAttention"]

    assert points[0]["titre"] == "Aucun point d'attention"
    assert points[0]["feu"] == "vert"


# =====================================================================
#  Vue d'ensemble de la Direction generale
# =====================================================================


def test_la_vue_de_la_direction_generale_porte_cinq_series(connecte):
    """Cinq graphiques, aucun tableau, aucune action — §3.1."""
    corps = connecte("dg").get(VUE_DIRECTION).json()

    for serie in (
        "ecartExecution",
        "executionParStructure",
        "retardsParStructure",
        "respectDelais",
        "decisionsExecutees",
    ):
        assert serie in corps


def test_sans_releve_le_bloc_chenal_est_absent_et_non_a_zero(connecte):
    """Une cote a zero signifierait que le chenal est comble."""
    corps = connecte("dg").get(VUE_DIRECTION).json()

    assert corps["chenal"] is None
    assert corps["recouvrements"] is None


def test_le_bilan_de_disponibilite_compte_les_presents_comme_une_part(connecte):
    """
    Un anneau qui ne montrerait que les absents dirait la meme chose quel que
    soit l'effectif.
    """
    aujourd_hui = date.today()
    absent = Utilisateur.objects.get(identifiant_annuaire="dir.dsi")
    Disponibilite.objects.create(
        utilisateur=absent,
        type_absence="mission",
        du=aujourd_hui - timedelta(days=1),
        au=aujourd_hui + timedelta(days=3),
        saisi_par=absent,
    )

    bilan = connecte("dg").get(VUE_DIRECTION).json()["disponibilite"]

    assert bilan["absents"] == 1
    assert bilan["sansInterim"] == 1
    assert bilan["presents"] == bilan["effectif"] - 1
    # « Presents » en tete, puis les motifs.
    assert bilan["parts"][0]["libelle"] == "Présents"
    assert {"libelle": "Mission", "valeur": 1} in bilan["parts"]


def test_sans_dispo_le_bilan_de_disponibilite_est_absent(connecte):
    """
    La route exige `VUE_DG`, mais le nom des absents releve de `DISPO`. Un bloc
    masque a l'affichage fuit des qu'on ouvre les outils du navigateur.
    """
    from noyau.habilitation.modeles import Permission, ProfilPermission

    ProfilPermission.objects.filter(permission=Permission.objects.get(code="DISPO")).delete()

    corps = connecte("dg").get(VUE_DIRECTION).json()

    assert corps["disponibilite"] is None


def test_le_chenal_remonte_le_point_le_plus_contraint(connecte):
    """Un navire passe par le moins profond, pas par le moyen."""
    aujourd_hui = date.today()
    rdr = Structure.objects.en_vigueur().get(code="RDR")
    for nom, cote in [("Passe d'entrée", "11.60"), ("Souille de Bonabéri", "8.20")]:
        ReleveChenal.objects.create(
            point=PointChenal.objects.get(nom=nom),
            releve_le=aujourd_hui,
            cote=cote,
            structure=rdr,
        )

    chenal = connecte("dg").get(VUE_DIRECTION).json()["chenal"]

    assert chenal["point"] == "Souille de Bonabéri"
    assert chenal["feu"] == "rouge"


def test_un_mois_sans_production_ne_dessine_pas_un_zero(connecte):
    """
    Zero pour cent aurait dit que rien n'a ete depose, quand rien n'etait
    attendu.
    """
    corps = connecte("dg").get(VUE_DIRECTION).json()
    assert corps["respectDelais"] == []


def test_les_reperes_disent_le_courrier_non_mesure(connecte):
    reperes = connecte("dg").get(VUE_DIRECTION).json()["reperes"]
    courrier = next(r for r in reperes if r["libelle"] == "Courriers traités dans le délai")

    assert courrier["valeur"] == "Non mesuré"


# =====================================================================
#  Vue d'ensemble du Comite de direction
# =====================================================================


def test_le_membre_voit_le_score_et_le_rang_de_sa_direction(connecte):
    """
    Le classement ne sort plus colonne par colonne (ADR 026) : le membre y lit
    sa position, et le college se lit par agregats.
    """
    corps = connecte("dir.daf").get(VUE_COMITE).json()

    assert corps["structureSigle"] == "DAF"
    assert "scoreParStructure" not in corps

    position = corps["positionMembre"]
    assert position["structureSigle"] == "DAF"
    assert position["rang"] >= 1
    assert position["rang"] <= position["totalStructures"]
    assert position["totalStructures"] > 1


def test_la_dispersion_du_college_est_servie(connecte):
    corps = connecte("dir.daf").get(VUE_COMITE).json()

    assert "dispersion" in corps
    assert "evolutionScoreMoyen" in corps


def test_les_activites_sont_reparties_par_etat_deduit(connecte):
    """
    L'etat vient de `v_activite_etat` : compter la colonne `etat` aurait montre
    zero retard, puisque « en retard » ne s'y stocke pas.
    """
    corps = connecte("dir.daf").get(VUE_COMITE).json()
    assert isinstance(corps["activitesParEtat"], list)


def test_les_decisions_du_comite_se_repartissent_en_trois_etats(connecte):
    corps = connecte("dir.daf").get(VUE_COMITE).json()
    libelles = [part["libelle"] for part in corps["decisionsParEtat"]]

    assert libelles == ["Exécutées", "En cours", "En retard"]

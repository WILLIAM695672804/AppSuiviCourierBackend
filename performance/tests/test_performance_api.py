"""
La matrice, le dictionnaire et le calendrier — `/api/performance/*`.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **Un critere non mesurable ne vaut pas zero.** Le critere courrier reste
    inconnu tant qu'aucun courrier n'a ete cloture sur la periode (ADR 036) ;
    s'il comptait pour zero, toute l'institution plafonnerait aux deux tiers de
    sa note et le classement serait faux tout en paraissant complet.
 2. **Le classement n'est pas filtre au perimetre.** Un classement filtre
    n'est pas un classement : chacun s'y verrait premier.
 3. **La separation lecture / administration.** Consulter un classement et
    changer la regle qui le produit ne sont pas le meme geste.
 4. **Le refus plutot que la valeur par defaut.** Une echeance illisible, une
    nature inconnue, un code deja pris : on refuse, parce que la valeur de
    repli se serait appliquee en silence a toute une production.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.db.models import F

from activite.modeles import CalendrierProduction, Obligation
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from performance.modeles import Critere, Indicateur

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
MATRICE = "/api/performance/matrice"
DICTIONNAIRE = "/api/performance/dictionnaire"
CALENDRIER = "/api/performance/calendrier"
INDICATEURS = "/api/performance/indicateurs"


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


@pytest.fixture
def mois_clos():
    """Un mois entierement revolu, pour que `provisoire` soit faux."""
    premier = date.today().replace(day=1)
    precedent = premier - timedelta(days=1)
    return precedent.year, precedent.month


# =====================================================================
#  Les gardes
# =====================================================================


def test_sans_session_la_matrice_est_fermee(client, jeu):
    assert client.get(MATRICE).status_code == 401


def test_un_agent_sans_SCORE_ne_voit_pas_le_classement(connecte):
    assert connecte("agent.dsi").get(MATRICE).status_code == 401


def test_l_administrateur_fonctionnel_ne_lit_pas_le_classement(connecte):
    """Il distribue les droits ; le pilotage ne le regarde pas (RNF-SEC-02)."""
    assert connecte("admin").get(MATRICE).status_code == 401


def test_le_directeur_general_lit_le_classement(connecte):
    assert connecte("dg").get(MATRICE).status_code == 200


def test_lire_le_classement_ne_donne_pas_le_droit_de_l_administrer(connecte):
    """`dg` porte SCORE et non SCORE_ADM : il lit, il ne redefinit pas."""
    reponse = connecte("dg").post(INDICATEURS, {}, content_type="application/json")
    assert reponse.status_code == 401


# =====================================================================
#  La matrice
# =====================================================================


def test_le_mois_en_cours_est_annonce_provisoire(connecte):
    """
    Une structure dont le rapport est du le 5 du mois suivant n'a rien depose
    le 12 du mois courant : la classer reviendrait a la punir d'un delai
    qu'elle respecte.
    """
    aujourd_hui = date.today()
    corps = (
        connecte("dsr").get(f"{MATRICE}?annee={aujourd_hui.year}&mois={aujourd_hui.month}").json()
    )

    assert corps["provisoire"] is True


def test_un_mois_revolu_n_est_pas_provisoire(connecte, mois_clos):
    annee, mois = mois_clos
    corps = connecte("dsr").get(f"{MATRICE}?annee={annee}&mois={mois}").json()

    assert corps["provisoire"] is False


def test_sans_periode_la_matrice_repond_pour_le_mois_courant(connecte):
    """La DSR ouvre l'ecran pour voir venir, pas pour relire le mois dernier."""
    aujourd_hui = date.today()
    periode = connecte("dsr").get(MATRICE).json()["periode"]

    assert (periode["annee"], periode["rang"]) == (aujourd_hui.year, aujourd_hui.month)
    assert periode["granularite"] == "mois"


def test_le_classement_porte_les_structures_marquees_ligne_statistiques(connecte):
    """
    Le drapeau est administre, pas ecrit dans le code : c'est a
    l'administrateur de retirer du classement les etages trop fins. Filtrer
    sur `parent IS NULL` n'aurait classe que la Direction Generale, qui ne se
    compare a personne.

    Lu par `dir.dsi`, qui ne consolide pas : la maille est celle du drapeau.
    """
    attendues = {
        s.code
        for s in Structure.objects.en_vigueur().filter(niveau_hierarchique__ligne_statistiques=True)
    }
    lignes = connecte("dir.dsi").get(MATRICE).json()["lignes"]

    assert {ligne["structureSigle"] for ligne in lignes} == attendues


def test_qui_consolide_voit_une_ligne_par_tete_de_structure(connecte):
    """
    Au-dessus d'un directeur, la sous-structure n'existe pas : la DSR et le
    Directeur general lisent le classement par tetes, et les services y sont
    comptes dans leur direction.
    """
    sigles = {ligne["structureSigle"] for ligne in connecte("dsr").get(MATRICE).json()["lignes"]}

    assert "DSI" in sigles
    assert "DSI-ET" not in sigles


def test_un_directeur_garde_le_detail_de_ses_services(connecte):
    sigles = {
        ligne["structureSigle"] for ligne in connecte("dir.dsi").get(MATRICE).json()["lignes"]
    }

    assert "DSI-ET" in sigles


def test_le_perimetre_ne_filtre_pas_le_classement(connecte):
    """
    Un chef de division n'a qu'un sous-arbre pour perimetre et voit pourtant
    tout le classement : un classement filtre n'est pas un classement.
    """
    lignes = connecte("dir.dsi").get(MATRICE).json()["lignes"]

    assert len(lignes) > 1


def test_le_courrier_non_mesure_sort_a_feu_inconnu(connecte):
    """
    Aucun courrier cloture sur la periode. Son critere sort a « inconnu » et
    non a « rouge » : « on ne sait pas » n'est pas « c'est nul ».

    Depuis l'ADR 036 le critere se mesure ; ce qui manque ici est la matiere,
    plus l'outil. Le feu attendu, lui, ne change pas.
    """
    ligne = connecte("dsr").get(MATRICE).json()["lignes"][0]
    courrier = next(c for c in ligne["criteres"] if c["code"] == "COUR")

    assert courrier["feu"] == "inconnu"


def test_un_critere_non_mesure_ne_plombe_pas_le_score_global(connecte, mois_clos):
    """
    Le score se renormalise sur les criteres mesures. Sans cela, une structure
    parfaite sur tout ce qui est mesurable plafonnerait a 34 % — un tiers
    exactement, celui du critere courrier non mesure.
    """
    annee, mois = mois_clos
    # Une tete de structure, et non la racine : depuis que la DSR consolide, la
    # Direction generale ne porte plus de ligne au classement — elle n'a pas de
    # tete, et ne se compare a rien.
    structure = Structure.objects.en_vigueur().filter(tete_id=F("id")).order_by("code").first()
    assert structure is not None

    _obligation_deposee_a_temps(structure, annee, mois)

    ligne = next(
        c
        for c in connecte("dsr").get(f"{MATRICE}?annee={annee}&mois={mois}").json()["lignes"]
        if c["structureSigle"] == structure.code
    )

    assert ligne["scoreGlobal"] > 34


def test_deux_scores_egaux_partagent_le_meme_rang(connecte):
    """
    Departager sur le sigle aurait fait dependre le rang de l'alphabet, ce
    qu'aucune direction n'accepterait.
    """
    lignes = connecte("dsr").get(MATRICE).json()["lignes"]
    rangs = {ligne["scoreGlobal"]: set() for ligne in lignes}
    for ligne in lignes:
        rangs[ligne["scoreGlobal"]].add(ligne["rang"])

    assert all(len(valeurs) == 1 for valeurs in rangs.values())


def test_le_classement_va_du_meilleur_au_moins_bon(connecte):
    lignes = connecte("dsr").get(MATRICE).json()["lignes"]
    scores = [ligne["scoreGlobal"] for ligne in lignes]

    assert scores == sorted(scores, reverse=True)


# =====================================================================
#  La fiche d'une structure
# =====================================================================


def test_la_fiche_decompose_le_score_en_sous_indicateurs(connecte):
    """
    Un score global sans sa decomposition est indefendable : un directeur
    classe neuvieme doit voir lequel des criteres l'y place.
    """
    sigle = connecte("dsr").get(MATRICE).json()["lignes"][0]["structureSigle"]
    fiche = connecte("dsr").get(f"{MATRICE}/{sigle}").json()

    assert fiche["structureSigle"] == sigle
    assert all(critere["sousIndicateurs"] for critere in fiche["criteres"])


def test_la_fiche_porte_douze_mois_du_plus_ancien_au_plus_recent(connecte):
    """C'est l'ordre d'une courbe : le temps va de gauche a droite."""
    sigle = connecte("dsr").get(MATRICE).json()["lignes"][0]["structureSigle"]
    historique = connecte("dsr").get(f"{MATRICE}/{sigle}").json()["historique"]

    assert len(historique) == 12


def test_une_structure_inconnue_repond_404_et_non_un_score_vide(connecte):
    """Une fiche vide se lirait comme un score de zero."""
    assert connecte("dsr").get(f"{MATRICE}/INEXISTANT").status_code == 404


def test_le_sous_indicateur_du_courrier_dit_pourquoi_il_est_vide(connecte):
    """
    C'est la premiere question que posera un directeur mal classe.

    Depuis l'ADR 036 la raison a change sans que la regle bouge : ce n'est plus
    « le pilier n'est pas en service » mais « aucun courrier cloture ce
    mois-ci ». Dire lequel des deux importe — le premier appelle un developpeur,
    le second un agent.
    """
    sigle = connecte("dsr").get(MATRICE).json()["lignes"][0]["structureSigle"]
    fiche = connecte("dsr").get(f"{MATRICE}/{sigle}").json()
    courrier = next(c for c in fiche["criteres"] if c["code"] == "COUR")

    assert any("Aucun courrier clôturé" in sous["valeur"] for sous in courrier["sousIndicateurs"])
    assert all(sous["feu"] == "inconnu" for sous in courrier["sousIndicateurs"])


# =====================================================================
#  Le dictionnaire
# =====================================================================


def test_le_dictionnaire_porte_les_cinq_champs_du_paragraphe_3_3(connecte):
    """« definition, formule de calcul, source, periodicite, responsable »."""
    indicateur = connecte("dsr").get(DICTIONNAIRE).json()["indicateurs"][0]

    for champ in ("definition", "formule", "source", "periodicite", "responsable"):
        assert indicateur[champ]


def test_chaque_critere_de_la_matrice_est_documente(connecte):
    """
    Un chiffre affiche dont la formule n'est ecrite nulle part n'est pas
    contestable, donc jamais corrige.
    """
    corps = connecte("dsr").get(DICTIONNAIRE).json()
    documentes = {i["critere"] for i in corps["indicateurs"]}

    for critere in Critere.objects.filter(actif=True):
        assert critere.libelle in documentes


def test_les_criteres_partent_avec_le_dictionnaire(connecte):
    """
    Le formulaire de création propose les axes existants. Une liste écrite dans
    le front se serait désynchronisée au premier critère ajouté, et la saisie
    aurait été refusée sans que l'agent comprenne pourquoi.
    """
    criteres = connecte("dsr").get(DICTIONNAIRE).json()["criteres"]

    assert {c["code"] for c in criteres} == {
        critere.code for critere in Critere.objects.filter(actif=True)
    }
    assert all(c["poids"] > 0 for c in criteres)


def test_la_grille_de_cotation_des_risques_est_vide(connecte):
    """
    Le §3.3 la mentionne, aucun document ne la definit, et une grille inventee
    serait appliquee telle quelle. Voir A26.
    """
    assert connecte("dsr").get(DICTIONNAIRE).json()["risques"] == []


def test_un_indicateur_se_definit_et_part_au_journal(connecte):
    """« Qui a changé la règle, et quand » est la première question posée le
    jour où un classement surprend."""
    reponse = connecte("dsr").post(
        INDICATEURS,
        {
            "code": "ACT-TENUE",
            "libelle": "Tenue du plan d'actions",
            "definition": "Part des activités dont l'échéance a été tenue.",
            "formule": "activités tenues ÷ activités échues × 100",
            "source": "Pilier activités",
            "periodicite": "Mensuelle",
            "responsable": "DSR",
            "unite": "%",
            "seuilVert": 90,
            "seuilOrange": 70,
            "critere": "Exécution des activités",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    indicateur = Indicateur.objects.get(code="ACT-TENUE")
    assert indicateur.critere is not None and indicateur.critere.code == "ACT"
    assert indicateur.periodicite == "mensuelle"
    assert _evenements("indicateur_defini") == 1


def test_un_code_deja_pris_est_refuse(connecte):
    """Le code sert de reference dans les documents de la DSR : le reutiliser
    rendrait faux tout ce qui le cite."""
    reponse = connecte("dsr").post(
        INDICATEURS,
        {
            "code": "ACT-HEURE",
            "libelle": "Doublon",
            "definition": "…",
            "formule": "…",
            "source": "…",
            "periodicite": "Mensuelle",
            "responsable": "DSR",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "code_pris"


def test_un_seuil_orange_au_dessus_du_vert_est_refuse(connecte):
    reponse = connecte("dsr").post(
        INDICATEURS,
        {
            "code": "TEST-SEUIL",
            "libelle": "Seuils inversés",
            "definition": "…",
            "formule": "…",
            "source": "…",
            "periodicite": "Mensuelle",
            "responsable": "DSR",
            "seuilVert": 50,
            "seuilOrange": 80,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "seuils_incoherents"


def test_un_critere_inconnu_est_refuse_et_non_mis_a_null(connecte):
    """Un indicateur detache de son critere ne se voit qu'au moment ou le
    score ne bouge pas."""
    reponse = connecte("dsr").post(
        INDICATEURS,
        {
            "code": "TEST-AXE",
            "libelle": "Critère fantôme",
            "definition": "…",
            "formule": "…",
            "source": "…",
            "periodicite": "Mensuelle",
            "responsable": "DSR",
            "critere": "Qualité de service",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "critere_inconnu"


# =====================================================================
#  Le calendrier
# =====================================================================


def test_le_calendrier_regroupe_par_production_et_non_par_structure(connecte):
    """
    Quinze directions produisant le meme rapport mensuel feraient quinze lignes
    identiques ou personne ne verrait qu'il en manque une.
    """
    for structure in Structure.objects.en_vigueur()[:3]:
        CalendrierProduction.objects.create(
            structure=structure,
            nature="rapport_mensuel",
            intitule="Rapport mensuel d'activité",
            periodicite="mensuelle",
            jour_echeance=5,
            actif=True,
            valide_du=date.today(),
        )

    lignes = connecte("dsr").get(CALENDRIER).json()["lignes"]
    intitules = [ligne["production"] for ligne in lignes]

    assert intitules == ["Rapport mensuel d'activité"]
    assert lignes[0]["structuresAttendues"] == 3


def test_l_echeance_se_lit_en_toutes_lettres(connecte):
    """`jour_echeance = 5` aurait oblige le front a reconstruire la phrase, et
    deux ecrans auraient fini par la formuler differemment."""
    structure = Structure.objects.en_vigueur().first()
    assert structure is not None
    CalendrierProduction.objects.create(
        structure=structure,
        nature="rapport_sectoriel",
        intitule="Rapport trimestriel",
        periodicite="trimestrielle",
        jour_echeance=10,
        actif=True,
        valide_du=date.today(),
    )

    ligne = connecte("dsr").get(CALENDRIER).json()["lignes"][0]

    assert ligne["echeance"] == "le 10 du mois suivant la fin du trimestre"


def test_le_cycle_en_cours_ne_compte_pas_comme_manquant(connecte):
    """Une production due le mois prochain n'est pas en retard aujourd'hui."""
    structure = Structure.objects.en_vigueur().filter(parent__isnull=True).first()
    assert structure is not None

    ligne = CalendrierProduction.objects.create(
        structure=structure,
        nature="rapport_mensuel",
        intitule="Rapport à venir",
        periodicite="mensuelle",
        jour_echeance=5,
        actif=True,
        valide_du=date.today(),
    )
    Obligation.objects.create(
        calendrier_production=ligne,
        structure=structure,
        intitule="Rapport à venir",
        periode_libelle="Période en cours",
        periode_debut=date.today(),
        periode_fin=date.today() + timedelta(days=20),
        echeance=date.today() + timedelta(days=30),
    )

    lignes = {c["production"]: c for c in connecte("dsr").get(CALENDRIER).json()["lignes"]}

    assert lignes["Rapport à venir"]["recus"] == 0
    assert lignes["Rapport à venir"]["feu"] == "inconnu"


def test_une_production_s_inscrit_pour_toutes_les_structures_classees(connecte):
    """
    Le nombre saisi a l'ecran n'est pas retenu : un chiffre saisi a la main
    aurait diverge du referentiel des la creation de la direction suivante.
    """
    attendues = (
        Structure.objects.en_vigueur().filter(niveau_hierarchique__ligne_statistiques=True).count()
    )

    reponse = connecte("dsr").post(
        CALENDRIER,
        {
            "production": "Note de conjoncture",
            "nature": "Rapport sectoriel",
            "periodicite": "Trimestrielle",
            "echeance": "le 10 du mois suivant la fin du trimestre",
            "relanceAutomatique": True,
            "joursAvantRelance": 5,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    lignes = CalendrierProduction.objects.filter(intitule="Note de conjoncture")
    assert lignes.count() == attendues
    assert lignes.first().jour_echeance == 10


def test_une_echeance_sans_jour_lisible_est_refusee(connecte):
    """Retenir un 1er par defaut aurait avance toutes les echeances de la
    production, sans que personne ne l'ait demande."""
    reponse = connecte("dsr").post(
        CALENDRIER,
        {
            "production": "Note illisible",
            "nature": "Rapport sectoriel",
            "periodicite": "Mensuelle",
            "echeance": "dès que possible",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "echeance_illisible"


def test_une_nature_hors_referentiel_est_refusee(connecte):
    """« PV », « P.V. », « proces verbal » : une nature libre aurait produit
    autant de valeurs que de saisies."""
    reponse = connecte("dsr").post(
        CALENDRIER,
        {
            "production": "Compte rendu libre",
            "nature": "Mémo interne",
            "periodicite": "Mensuelle",
            "echeance": "le 5 du mois suivant",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "nature_inconnue"


def test_le_compteur_signale_les_productions_sans_relance(connecte):
    """Une echeance sans relance est une echeance qui ne sera pas tenue —
    §3.3."""
    structure = Structure.objects.en_vigueur().first()
    assert structure is not None
    CalendrierProduction.objects.create(
        structure=structure,
        nature="rapport_mensuel",
        intitule="Rapport sans relance",
        periodicite="mensuelle",
        jour_echeance=5,
        relance_automatique=False,
        actif=True,
        valide_du=date.today(),
    )

    compteurs = {c["libelle"]: c for c in connecte("dsr").get(CALENDRIER).json()["compteurs"]}
    sans_relance = compteurs["Sans relance automatique"]

    assert sans_relance["valeur"] > 0
    assert sans_relance["feu"] == "orange"


# =====================================================================
#  Utilitaires
# =====================================================================


def _evenements(type_evenement: str) -> int:
    """Le journal se lit au curseur brut : la table est partitionnee et non
    geree par l'ORM."""
    from django.db import connection

    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT count(*) FROM evenement WHERE type_evenement = %s", [type_evenement]
        )
        return curseur.fetchone()[0]


def _obligation_deposee_a_temps(structure: Structure, annee: int, mois: int) -> None:
    """Une obligation echue dans le mois observe, deposee avant son echeance."""
    from performance.matrice import bornes

    debut, fin = bornes(annee, mois)
    ligne = CalendrierProduction.objects.create(
        structure=structure,
        nature="rapport_mensuel",
        intitule="Rapport de test",
        periodicite="mensuelle",
        jour_echeance=5,
        actif=True,
        valide_du=debut,
    )
    Obligation.objects.create(
        calendrier_production=ligne,
        structure=structure,
        intitule="Rapport de test",
        periode_libelle="Mois observé",
        periode_debut=debut,
        periode_fin=fin,
        echeance=fin,
        depose_le=debut,
        # Le socle exige les deux ensemble (`obligation_depot_complet`) : un
        # depot sans deposant ne se conteste pas.
        depose_par=Utilisateur.objects.get(identifiant_annuaire="focal.dsi"),
    )

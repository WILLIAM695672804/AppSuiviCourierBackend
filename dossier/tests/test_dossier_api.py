"""
Les dossiers a instruire — `/api/dossiers/*`.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **Le perimetre.** Un agent en portee `propre` ne doit voir que les dossiers
    dont il est instructeur. L'oubli de `restreindre()` ne produit aucune
    erreur — juste une fuite de noms de demandeurs.
 2. **Le delai qui ne se suspend pas.** Demander un complement ne repousse pas
    l'echeance, et le registre continue de compter les jours. C'est la regle du
    §3.7, et c'est celle qu'un raccourci de confort ferait sauter en premier.
 3. **Le motif de retour.** RF-BPM-06 : sans motif, l'etape precedente devine.
 4. **La fusion refusee.** Une variable non fournie arrete tout : laisser
    `{demandeur}` en clair dans un courrier signe ne se repare pas.
 5. **La regle d'affectation ecrite.** RF-BPM-02 : la fiche doit dire pourquoi
    le dossier est arrive la, y compris quand aucune regle ne s'applique.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from dossier.modeles import (
    ETAPE_CLOS,
    ETAPE_INSTRUCTION,
    ETAPE_VALIDATION,
    Dossier,
    ModeleCourrier,
    PieceDossier,
    RegleAffectation,
    VersionPiece,
)
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
REGISTRE = "/api/dossiers"
MODELES = "/api/dossiers/modeles"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    # Les seuils du pilier vivent en base (A37, A38) et `parametres.valeur()`
    # les met en cache : sans ce vidage, un test heriterait de la valeur lue
    # par le precedent, dans une base qui n'existe plus.
    vider_cache()
    yield
    vider_cache()


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(
            Utilisateur.objects.get(identifiant_annuaire=identifiant), backend=BACKEND
        )
        return client

    return _connecter


def _dossier(
    reference: str,
    *,
    structure: str = "DSI",
    instructeur: str | None = None,
    echeance: date | None = None,
    etape: str = ETAPE_INSTRUCTION,
    type_dossier: str = "demande",
    clos_le: date | None = None,
) -> Dossier:
    aujourd_hui = date.today()
    return Dossier.objects.create(
        reference=reference,
        objet=f"Objet du dossier {reference}",
        type_dossier=type_dossier,
        demandeur="Société Camrail",
        structure=Structure.objects.en_vigueur().get(code=structure),
        instructeur=(
            Utilisateur.objects.get(identifiant_annuaire=instructeur) if instructeur else None
        ),
        regle_affectation_texte="Règle d'essai.",
        ouvert_le=aujourd_hui - timedelta(days=10),
        echeance=echeance or aujourd_hui + timedelta(days=20),
        etape=etape,
        clos_le=clos_le,
    )


# =====================================================================
#  Le registre
# =====================================================================


def test_le_registre_repond_sans_aucun_dossier(connecte):
    """Une base sans dossier rend une liste vide, pas une erreur."""
    reponse = connecte("dir.dsi").get(REGISTRE)
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["dossiers"] == []
    assert corps["total"] == 0
    assert len(corps["compteurs"]) == 4


def test_le_registre_compte_les_jours_restants_et_non_l_echeance(connecte):
    """
    La colonne decisive est ce qui reste, pas la date.

    Un instructeur qui balaie sa liste le matin cherche ce qui lui reste ; le
    negatif dit le retard sans qu'il ait a soustraire de tete.
    """
    _dossier("DOS-2026-0001", echeance=date.today() + timedelta(days=5))
    _dossier("DOS-2026-0002", echeance=date.today() - timedelta(days=3))

    corps = connecte("dir.dsi").get(REGISTRE).json()
    restants = {ligne["reference"]: ligne["joursRestants"] for ligne in corps["dossiers"]}

    assert restants["DOS-2026-0001"] == 5
    assert restants["DOS-2026-0002"] == -3


def test_un_dossier_hors_delai_est_rouge_et_compte_comme_tel(connecte):
    _dossier("DOS-2026-0001", echeance=date.today() - timedelta(days=1))

    corps = connecte("dir.dsi").get(REGISTRE).json()
    ligne = corps["dossiers"][0]

    assert ligne["etat"] == "Hors délai"
    assert ligne["feu"] == "rouge"
    assert corps["compteurs"][0]["libelle"] == "Hors délai"
    assert corps["compteurs"][0]["valeur"] == 1


def test_un_dossier_clos_n_est_ni_vert_ni_rouge(connecte):
    """
    Le colorer en vert aurait fait passer pour une reussite un dossier clos
    avec trois semaines de retard.
    """
    _dossier(
        "DOS-2026-0001",
        etape=ETAPE_CLOS,
        clos_le=date.today(),
        echeance=date.today() - timedelta(days=5),
    )

    ligne = connecte("dir.dsi").get(REGISTRE).json()["dossiers"][0]
    assert ligne["etat"] == "Clos"
    assert ligne["feu"] == "inconnu"


def test_le_registre_ne_montre_pas_les_dossiers_d_une_autre_structure(connecte):
    """
    §3.4 : la directrice de la DSI voit sa branche, service des etudes compris,
    et rien de la DAF. Le nom d'un demandeur est une donnee de la DAF.
    """
    _dossier("DOS-2026-0001", structure="DSI")
    _dossier("DOS-2026-0002", structure="DSI-ET")
    _dossier("DOS-2026-0003", structure="DAF")

    corps = connecte("dir.dsi").get(REGISTRE).json()
    references = sorted(ligne["reference"] for ligne in corps["dossiers"])

    assert references == ["DOS-2026-0001", "DOS-2026-0002"]


def test_en_portee_propre_l_agent_ne_voit_que_ses_dossiers(connecte):
    """
    `agent.dsi` est en portee `propre`. Sans `champ_agent`, la restriction se
    serait degradee au niveau de la structure — c'est-a-dire a tous les
    dossiers de la DSI.
    """
    _dossier("DOS-2026-0001", structure="DSI-ET", instructeur="agent.dsi")
    _dossier("DOS-2026-0002", structure="DSI-ET")

    corps = connecte("agent.dsi").get(REGISTRE).json()
    references = [ligne["reference"] for ligne in corps["dossiers"]]

    assert references == ["DOS-2026-0001"]


def test_un_filtre_inconnu_ne_vide_pas_l_ecran(connecte):
    """Un filtre mal orthographie qui vide la liste se lit comme une panne."""
    _dossier("DOS-2026-0001")

    corps = connecte("dir.dsi").get(REGISTRE, {"etat": "Hors delai"}).json()
    assert corps["total"] == 1


def test_le_registre_est_refuse_sans_permission(connecte):
    """`focal.dsi` (POINT_FOCAL) ne porte pas `DOS_LEC`."""
    assert connecte("focal.dsi").get(REGISTRE).status_code == 401


# =====================================================================
#  L'ouverture
# =====================================================================


def test_ouvrir_un_dossier_depuis_un_courrier_garde_la_reference(connecte):
    """
    Le dossier garde la reference du courrier, et c'est tout : le courrier
    poursuit son propre circuit.
    """
    reponse = connecte("dir.dsi").post(
        REGISTRE,
        {
            "courrierId": 4211,
            "courrierReference": "ARR-2026-0189",
            "type": "Autorisation",
            "objet": "Occupation temporaire du domaine portuaire",
            "demandeur": "Société Camrail",
            "echeance": (date.today() + timedelta(days=30)).isoformat(),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201

    dossier = Dossier.objects.get(pk=reponse.json()["id"])
    assert dossier.courrier_origine_reference == "ARR-2026-0189"
    assert dossier.courrier_origine_id == 4211
    assert dossier.reference.startswith(f"DOS-{date.today().year}-")


def test_un_depot_direct_s_ouvre_sans_courrier(connecte):
    reponse = connecte("dir.dsi").post(
        REGISTRE,
        {
            "courrierId": 0,
            "type": "Demande",
            "objet": "Raccordement électrique du terre-plein",
            "demandeur": "Société Camrail",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201
    assert Dossier.objects.get(pk=reponse.json()["id"]).courrier_origine_id is None


def test_un_dossier_ne_s_ouvre_pas_deja_en_retard(connecte):
    """Le registre demarrerait avec une alerte que personne n'a causee."""
    reponse = connecte("dir.dsi").post(
        REGISTRE,
        {
            "type": "Demande",
            "objet": "Raccordement électrique du terre-plein",
            "demandeur": "Société Camrail",
            "echeance": (date.today() - timedelta(days=1)).isoformat(),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert "déjà passée" in reponse.json()["message"]


def test_sans_regle_applicable_la_fiche_le_dit_en_toutes_lettres(connecte):
    """
    RF-BPM-02 : l'affectation dynamique doit s'expliquer. Quand aucune regle ne
    couvre le dossier, la phrase le dit — c'est moins bien qu'une regle, et
    c'est visible, ce qui vaut mieux qu'un rattachement invente.
    """
    reponse = connecte("dir.dsi").post(
        REGISTRE,
        {
            "type": "Demande",
            "objet": "Raccordement électrique du terre-plein",
            "demandeur": "Société Camrail",
        },
        content_type="application/json",
    )
    fiche = connecte("dir.dsi").get(f"{REGISTRE}/{reponse.json()['id']}").json()

    assert "Aucune règle d'affectation" in fiche["regleAffectation"]
    assert fiche["seuil"] is None


def test_une_regle_a_seuil_ne_s_applique_pas_sans_montant(connecte):
    """
    La reputer satisfaite aurait envoye au comite des engagements des dossiers
    dont personne n'a chiffre l'enjeu.
    """
    RegleAffectation.objects.create(
        libelle="Les autorisations de plus de 50 millions relèvent de la DAF.",
        type_dossier="autorisation",
        montant_minimum=50_000_000,
        structure=Structure.objects.en_vigueur().get(code="DAF"),
    )

    sans_montant = connecte("dir.dsi").post(
        REGISTRE,
        {
            "type": "Autorisation",
            "objet": "Occupation temporaire du domaine portuaire",
            "demandeur": "Société Camrail",
        },
        content_type="application/json",
    )
    assert Dossier.objects.get(pk=sans_montant.json()["id"]).structure.code == "DSI"

    avec_montant = connecte("dir.dsi").post(
        REGISTRE,
        {
            "type": "Autorisation",
            "objet": "Occupation temporaire du domaine portuaire",
            "demandeur": "Société Camrail",
            "montant": 90_000_000,
        },
        content_type="application/json",
    )
    dossier = Dossier.objects.get(pk=avec_montant.json()["id"])
    assert dossier.structure.code == "DAF"
    assert dossier.regle_affectation_texte.startswith("Les autorisations")


def test_la_regle_la_plus_specifique_l_emporte(connecte):
    generale = Structure.objects.en_vigueur().get(code="DAF")
    precise = Structure.objects.en_vigueur().get(code="DCG")

    RegleAffectation.objects.create(
        libelle="Toutes les demandes relèvent de la DAF.",
        type_dossier="demande",
        structure=generale,
        priorite=10,
    )
    RegleAffectation.objects.create(
        libelle="Les demandes urgentes relèvent du contrôle de gestion.",
        type_dossier="demande",
        criticite="urgent",
        structure=precise,
        priorite=90,
    )

    reponse = connecte("dir.dsi").post(
        REGISTRE,
        {
            "type": "Demande",
            "objet": "Raccordement électrique du terre-plein",
            "demandeur": "Société Camrail",
            "criticite": "Urgent",
        },
        content_type="application/json",
    )
    assert Dossier.objects.get(pk=reponse.json()["id"]).structure.code == "DCG"


def test_ouvrir_est_refuse_sans_permission_d_instruction(connecte):
    """`dg` porte `DOS_LEC` et pas `DOS_INS` : il lit, il n'instruit pas."""
    reponse = connecte("dg").post(
        REGISTRE,
        {
            "type": "Demande",
            "objet": "Raccordement électrique du terre-plein",
            "demandeur": "Société Camrail",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 401


# =====================================================================
#  La fiche d'instruction
# =====================================================================


def test_la_fiche_montre_le_circuit_en_entier(connecte):
    """Un instructeur doit savoir qui validera apres lui."""
    dossier = _dossier("DOS-2026-0001", etape=ETAPE_VALIDATION)

    fiche = connecte("dir.dsi").get(f"{REGISTRE}/{dossier.pk}").json()
    etapes = fiche["etapes"]

    assert [etape["libelle"] for etape in etapes] == [
        "Qualification",
        "Instruction",
        "Validation",
        "Notification",
        "Clos",
    ]
    assert [etape["franchie"] for etape in etapes] == [True, True, False, False, False]


def test_les_versions_d_une_piece_restent_toutes_listees(connecte):
    """
    RF-GED-04 : sans les precedentes, on ne peut plus dire sur quoi la decision
    a ete prise.
    """
    dossier = _dossier("DOS-2026-0001")
    piece = PieceDossier.objects.create(
        dossier=dossier, nom="Rapport d'expertise", format_fichier="PDF"
    )
    for rang in (1, 2, 3):
        VersionPiece.objects.create(
            piece=piece,
            version=rang,
            taille_octets=1024 * rang,
            empreinte=f"empreinte-{rang}",
            chemin_stockage=f"/fonds/{rang}",
        )

    fiche = connecte("dir.dsi").get(f"{REGISTRE}/{dossier.pk}").json()
    versions = fiche["pieces"][0]["versions"]

    assert [version["version"] for version in versions] == [1, 2, 3]
    assert [version["courante"] for version in versions] == [False, False, True]


def test_un_dossier_hors_perimetre_rend_404_et_non_403(connecte):
    """Un 403 confirmerait l'existence du dossier et de son demandeur (D5)."""
    dossier = _dossier("DOS-2026-0001", structure="DAF")

    assert connecte("dir.dsi").get(f"{REGISTRE}/{dossier.pk}").status_code == 404


# =====================================================================
#  Les complements
# =====================================================================


def test_demander_un_complement_ne_repousse_pas_l_echeance(connecte):
    """
    §3.7 : le demandeur qui ne repond pas ne dispense pas l'institution de son
    obligation de reponse. Les confondre offrirait a l'instructeur un moyen
    simple de n'etre jamais en retard.
    """
    dossier = _dossier("DOS-2026-0001", echeance=date.today() + timedelta(days=5))

    reponse = connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/complements",
        {
            "objet": "Copie certifiée du titre foncier",
            "echeance": (date.today() + timedelta(days=45)).isoformat(),
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201

    dossier.refresh_from_db()
    assert dossier.echeance == date.today() + timedelta(days=5)


def test_l_attente_d_un_complement_ne_masque_pas_le_retard(connecte):
    """
    Le retard l'emporte sur l'attente : sinon l'instructeur lirait « en
    attente » et se croirait couvert.
    """
    dossier = _dossier("DOS-2026-0001", echeance=date.today() - timedelta(days=2))
    connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/complements",
        {
            "objet": "Copie certifiée du titre foncier",
            "echeance": (date.today() + timedelta(days=10)).isoformat(),
        },
        content_type="application/json",
    )

    ligne = connecte("dir.dsi").get(REGISTRE).json()["dossiers"][0]
    assert ligne["etat"] == "Hors délai"


def test_un_complement_recu_libere_l_etat_du_dossier(connecte):
    dossier = _dossier("DOS-2026-0001")
    client = connecte("dir.dsi")
    complement = client.post(
        f"{REGISTRE}/{dossier.pk}/complements",
        {
            "objet": "Copie certifiée du titre foncier",
            "echeance": (date.today() + timedelta(days=10)).isoformat(),
        },
        content_type="application/json",
    ).json()["id"]

    assert client.get(REGISTRE).json()["dossiers"][0]["etat"] == "En attente de complément"

    client.post(
        f"{REGISTRE}/{dossier.pk}/complements/{complement}/reception",
        content_type="application/json",
    )
    assert client.get(REGISTRE).json()["dossiers"][0]["etat"] == "En cours"


# =====================================================================
#  Le retour a une etape anterieure
# =====================================================================


def test_un_retour_sans_motif_est_refuse(connecte):
    """RF-BPM-06 : sans motif, l'etape precedente devine ce qu'on lui reproche."""
    dossier = _dossier("DOS-2026-0001", etape=ETAPE_VALIDATION)

    reponse = connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/retour",
        {"etapeCible": "Instruction", "motif": "À revoir"},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert "motif" in reponse.json()["message"].lower()


def test_un_retour_vers_une_etape_posterieure_est_refuse(connecte):
    """Ce ne serait pas un retour, mais une avancee deguisee."""
    dossier = _dossier("DOS-2026-0001", etape=ETAPE_INSTRUCTION)

    reponse = connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/retour",
        {
            "etapeCible": "Validation",
            "motif": "Le dossier doit repasser par la validation hiérarchique.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_un_retour_garde_les_deux_etapes_au_journal(connecte):
    """
    C'est cette paire qui permet, six mois plus tard, de reconstituer le chemin
    reel du dossier et pas seulement son etat final.
    """
    dossier = _dossier("DOS-2026-0001", etape=ETAPE_VALIDATION)
    client = connecte("dir.dsi")

    client.post(
        f"{REGISTRE}/{dossier.pk}/retour",
        {
            "etapeCible": "Instruction",
            "motif": "La pièce d'identité du mandataire est absente du dossier.",
        },
        content_type="application/json",
    )

    fiche = client.get(f"{REGISTRE}/{dossier.pk}").json()
    retour = next(
        fait for fait in fiche["historique"] if fait["type"] == "Retour à l'étape antérieure"
    )

    assert retour["etapeAvant"] == "Validation"
    assert retour["etapeApres"] == "Instruction"
    assert fiche["etat"] == "Retourné"


def test_l_instructeur_peut_retourner_un_dossier(connecte):
    """
    Le §3.7 confie ce geste a l'agent instructeur. Le reserver a `DOS_VAL`
    laissait l'instructeur sans recours devant un dossier mal oriente.
    """
    dossier = _dossier(
        "DOS-2026-0001", structure="DSI-ET", instructeur="agent.dsi", etape=ETAPE_VALIDATION
    )

    reponse = connecte("agent.dsi").post(
        f"{REGISTRE}/{dossier.pk}/retour",
        {
            "etapeCible": "Instruction",
            "motif": "La pièce d'identité du mandataire est absente du dossier.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201


# =====================================================================
#  La bibliotheque des courriers-type
# =====================================================================


def test_la_bibliotheque_est_semee_et_sert_le_corps_entier(connecte):
    """
    Un agent qui choisit un modele sur trois lignes de resume decouvre ce qu'il
    a envoye apres l'avoir envoye.
    """
    corps = connecte("dir.dsi").get(MODELES).json()
    assert len(corps["modeles"]) >= 5

    accuse = next(modele for modele in corps["modeles"] if modele["code"] == "MOD-ACC")
    assert "Madame, Monsieur" in accuse["corps"]
    assert "reference" in accuse["variables"]


def test_les_variables_sont_derivees_du_corps(connecte):
    """
    Deux listes divergent, et la premiere fusion qui laisse un `{demandeur}` en
    clair dans un courrier signe est de celles qu'on n'oublie pas.
    """
    ModeleCourrier.objects.create(
        code="MOD-TEST",
        libelle="Modèle d'essai",
        typologie="Essai",
        corps="Bonjour {demandeur}, votre dossier {reference} avance. {demandeur} encore.",
    )

    corps = connecte("dir.dsi").get(MODELES).json()
    modele = next(ligne for ligne in corps["modeles"] if ligne["code"] == "MOD-TEST")

    assert modele["variables"] == ["demandeur", "reference"]


def test_une_fusion_a_variable_manquante_est_refusee(connecte):
    dossier = _dossier("DOS-2026-0001")
    modele = ModeleCourrier.objects.get(code="MOD-ACC")

    reponse = connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/fusion",
        {"modeleId": modele.pk, "valeurs": {"reference": "DOS-2026-0001"}},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert "objet" in reponse.json()["message"]


def test_une_fusion_complete_rend_le_texte_et_compte_l_usage(connecte):
    dossier = _dossier("DOS-2026-0001")
    modele = ModeleCourrier.objects.get(code="MOD-ACC")
    valeurs = {
        variable: "valeur"
        for variable in (
            "reference",
            "objet",
            "ouvertLe",
            "structure",
            "echeance",
            "instructeur",
        )
    }

    reponse = connecte("dir.dsi").post(
        f"{REGISTRE}/{dossier.pk}/fusion",
        {"modeleId": modele.pk, "valeurs": valeurs},
        content_type="application/json",
    )
    assert reponse.status_code == 201
    assert "{" not in reponse.json()["texte"]

    modele.refresh_from_db()
    assert modele.utilisations == 1


# =====================================================================
#  Ce que le pilotage lit
# =====================================================================


def test_le_taux_d_instruction_est_non_mesure_sans_dossier_clos(connecte):
    """
    ADR 011 : une structure qui n'a rien encore cloture n'instruit pas mal,
    elle n'a pas fini. Zero pour cent aurait dit l'inverse.
    """
    from pilotage import mesures

    _dossier("DOS-2026-0001")
    assert mesures.instruction_dossiers() is None


def test_le_taux_d_instruction_se_calcule_des_la_premiere_cloture(connecte):
    """La moitie de la question A30 se ferme ici."""
    from pilotage import mesures

    _dossier(
        "DOS-2026-0001",
        etape=ETAPE_CLOS,
        clos_le=date.today() - timedelta(days=2),
        echeance=date.today(),
    )
    _dossier(
        "DOS-2026-0002",
        etape=ETAPE_CLOS,
        clos_le=date.today(),
        echeance=date.today() - timedelta(days=5),
    )

    assert mesures.instruction_dossiers() == 50.0


def test_le_tableau_de_bord_personnel_compte_les_dossiers_de_l_agent(connecte):
    """
    La ligne « Dossiers dont vous êtes responsable » porte sur l'agent nommé
    instructeur, pas sur sa structure. « Votre service en a trente » et « vous
    en avez deux » n'appellent pas le même geste.
    """
    from dossier.lecture import dossiers_de_l_agent

    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")

    _dossier("DOS-2026-0001", structure="DSI-ET", instructeur="agent.dsi")
    _dossier(
        "DOS-2026-0002",
        structure="DSI-ET",
        instructeur="agent.dsi",
        echeance=date.today() - timedelta(days=2),
    )
    # Même service, mais confié à personne : il ne compte pas pour l'agent.
    _dossier("DOS-2026-0003", structure="DSI-ET")
    # Clos : il ne reste rien à faire dessus.
    _dossier(
        "DOS-2026-0004",
        structure="DSI-ET",
        instructeur="agent.dsi",
        etape=ETAPE_CLOS,
        clos_le=date.today(),
    )

    assert dossiers_de_l_agent(agent) == (1, 2)

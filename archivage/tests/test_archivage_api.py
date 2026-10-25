"""
L'archivage — `/api/archivage/*`.

Ce que ces tests protegent :

 1. **On ne verse pas sans regle visee.** Deux anomalies bloquantes, et elles
    le restent quoi qu'en dise `anomaliesAcceptees` : verser un dossier dont
    personne ne dit combien de temps on le garde revient a le perdre
    proprement.
 2. **Ce qui a ete verse l'a ete sous la regle d'alors.** La DUA et le sort
    final sont recopies dans le versement. Les relire dans le referentiel
    aurait fait bouger les dates d'elimination a chaque revision.
 3. **La chaine tient.** Chaque maillon porte l'empreinte du precedent : c'est
    ce chainage qui prouve qu'aucune etape n'a ete retiree entre deux autres.
 4. **Le taux de conformite sort a `null` sur un fonds vide.** Ni 0, ni 100 :
    seuls ces deux-la seraient recopies dans un rapport de controle (ADR 011).
 5. **Rien ne supprime.** Le sort final se propose ; aucune route ne detruit.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from archivage.modeles import ETAT_VERSE, RegleConservation, Versement
from dossier.modeles import ETAPE_CLOS, ETAPE_INSTRUCTION, Dossier
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
REFERENTIEL = "/api/archivage/referentiel"
VERSEMENTS = "/api/archivage/versements"
CONFORMITE = "/api/archivage/conformite"


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


def _dossier_clos(
    reference: str,
    *,
    type_dossier: str = "demande",
    clos_il_y_a: int = 30,
    structure: str = "DSI",
) -> Dossier:
    aujourd_hui = date.today()
    return Dossier.objects.create(
        reference=reference,
        objet=f"Objet du dossier {reference}",
        type_dossier=type_dossier,
        demandeur="Société Camrail",
        structure=Structure.objects.en_vigueur().get(code=structure),
        regle_affectation_texte="Règle d'essai.",
        ouvert_le=aujourd_hui - timedelta(days=clos_il_y_a + 30),
        echeance=aujourd_hui - timedelta(days=clos_il_y_a),
        etape=ETAPE_CLOS,
        clos_le=aujourd_hui - timedelta(days=clos_il_y_a),
    )


def _regle(
    typologie: str = "Demande",
    *,
    dua: int = 5,
    sort_final: str = "conservation",
    visee: bool = True,
) -> RegleConservation:
    archiviste = Utilisateur.objects.get(identifiant_annuaire="archiviste")
    return RegleConservation.objects.create(
        typologie=typologie,
        description=f"Conservation des dossiers de type {typologie}.",
        dua=dua,
        sort_final=sort_final,
        fondement_juridique="Instruction d'archivage du PAD — texte d'essai.",
        validee_par=archiviste if visee else None,
        validee_le=date.today() if visee else None,
    )


# =====================================================================
#  Le referentiel de conservation
# =====================================================================


def test_le_referentiel_repond_vide_sans_regle(connecte):
    corps = connecte("archiviste").get(REFERENTIEL).json()

    assert corps["regles"] == []
    assert corps["enAttenteValidation"] == 0


def test_une_regle_creee_n_est_pas_visee(connecte):
    """
    RF-ADM-05 : c'est le service des archives qui rend la regle applicable, pas
    celui qui la saisit. La creer deja visee lui aurait retire sa competence
    par voie logicielle.
    """
    reponse = connecte("archiviste").post(
        REFERENTIEL,
        {
            "typologie": "Demande",
            "description": "Dossiers de demande instruits par les directions.",
            "dua": 5,
            "sortFinal": "Conservation définitive",
            "fondementJuridique": "Instruction d'archivage du PAD, article 4.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201

    regle = RegleConservation.objects.get(pk=reponse.json()["id"])
    assert regle.validee_le is None
    assert regle.visee is False

    corps = connecte("archiviste").get(REFERENTIEL).json()
    assert corps["enAttenteValidation"] == 1
    assert corps["regles"][0]["valideeLe"] is None


def test_une_regle_sans_fondement_juridique_est_refusee(connecte):
    """Sans texte, la règle n'est pas opposable : un archiviste répond par un texte."""
    reponse = connecte("archiviste").post(
        REFERENTIEL,
        {
            "typologie": "Demande",
            "description": "Dossiers de demande.",
            "dua": 5,
            "sortFinal": "Conservation définitive",
            "fondementJuridique": "   ",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_une_dua_de_zero_annee_est_refusee(connecte):
    """« Détruire le jour de la clôture » n'est pas une durée de conservation."""
    reponse = connecte("archiviste").post(
        REFERENTIEL,
        {
            "typologie": "Demande",
            "description": "Dossiers de demande.",
            "dua": 0,
            "sortFinal": "Destruction",
            "fondementJuridique": "Instruction d'archivage du PAD, article 4.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_deux_durees_pour_une_meme_typologie_sont_refusees(connecte):
    """Deux DUA voudraient dire deux dates d'élimination, et aucune ne ferait foi."""
    _regle("Demande")

    reponse = connecte("archiviste").post(
        REFERENTIEL,
        {
            "typologie": "Demande",
            "description": "Doublon.",
            "dua": 10,
            "sortFinal": "Destruction",
            "fondementJuridique": "Instruction d'archivage du PAD, article 4.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_le_visa_porte_le_nom_du_signataire(connecte):
    regle = _regle("Demande", visee=False)

    reponse = connecte("archiviste").post(
        f"{REFERENTIEL}/{regle.pk}/validation", content_type="application/json"
    )
    assert reponse.status_code == 201

    regle.refresh_from_db()
    assert regle.validee_le == date.today()
    assert regle.validee_par.identifiant_annuaire == "archiviste"


def test_une_regle_visee_n_est_pas_revisee(connecte):
    """Le second visa effacerait le nom du premier signataire."""
    regle = _regle("Demande")

    reponse = connecte("archiviste").post(
        f"{REFERENTIEL}/{regle.pk}/validation", content_type="application/json"
    )
    assert reponse.status_code == 409


def test_le_referentiel_est_refuse_sans_permission_d_archivage(connecte):
    """`dir.dsi` (RESP) instruit des dossiers ; il ne tient pas le fonds."""
    assert connecte("dir.dsi").get(REFERENTIEL).status_code == 401


# =====================================================================
#  La file des versements
# =====================================================================


def test_la_file_ne_retient_que_les_dossiers_clos(connecte):
    """La DUA court a partir de la cloture : un dossier ouvert n'a pas d'echeance."""
    _regle("Demande")
    _dossier_clos("DOS-2026-0001")
    Dossier.objects.create(
        reference="DOS-2026-0002",
        objet="Dossier encore en instruction",
        type_dossier="demande",
        demandeur="Société Camrail",
        structure=Structure.objects.en_vigueur().get(code="DSI"),
        regle_affectation_texte="Règle d'essai.",
        ouvert_le=date.today() - timedelta(days=5),
        echeance=date.today() + timedelta(days=25),
        etape=ETAPE_INSTRUCTION,
    )

    corps = connecte("archiviste").get(VERSEMENTS).json()
    references = [ligne["reference"] for ligne in corps["versements"]]

    assert references == ["DOS-2026-0001"]


def test_la_file_est_triee_par_echeance_du_sort_final(connecte):
    """
    Ce qui presse n'est pas ce qui est vieux, c'est ce qui arrive a terme : un
    dossier clos hier dont la DUA est d'un an passe devant un dossier clos il y
    a quatre ans dont la DUA est de dix.
    """
    _regle("Demande", dua=1)
    _regle("Requête", dua=10)
    _dossier_clos("DOS-VIEUX", type_dossier="requete", clos_il_y_a=4 * 365)
    _dossier_clos("DOS-RECENT", type_dossier="demande", clos_il_y_a=1)

    corps = connecte("archiviste").get(VERSEMENTS).json()
    references = [ligne["reference"] for ligne in corps["versements"]]

    assert references == ["DOS-RECENT", "DOS-VIEUX"]


def test_un_dossier_non_verse_porte_un_identifiant_negatif(connecte):
    """
    C'est la seule facon d'ouvrir sa fiche avant le versement, et donc de voir
    ce qui l'empeche.
    """
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")

    ligne = connecte("archiviste").get(VERSEMENTS).json()["versements"][0]
    assert ligne["id"] == -dossier.pk

    fiche = connecte("archiviste").get(f"{VERSEMENTS}/{ligne['id']}").json()
    assert fiche["reference"] == "DOS-2026-0001"
    assert fiche["chaineIntegrite"] == []


# =====================================================================
#  Le versement
# =====================================================================


def test_sans_regle_le_versement_est_refuse_meme_en_acceptant_les_anomalies(connecte):
    """
    L'anomalie bloquante ne se passe pas outre. La verifier apres
    `anomaliesAcceptees` aurait suffi a la rendre contournable d'une case a
    cocher.
    """
    dossier = _dossier_clos("DOS-2026-0001")

    reponse = connecte("archiviste").post(
        f"{VERSEMENTS}/{-dossier.pk}/versement",
        {"observation": "Je verse quand même.", "anomaliesAcceptees": True},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert not Versement.objects.exists()


def test_une_regle_non_visee_ne_permet_pas_de_verser(connecte):
    """Une regle sans visa existe, elle se lit, et elle ne decide de rien."""
    _regle("Demande", visee=False)
    dossier = _dossier_clos("DOS-2026-0001")

    reponse = connecte("archiviste").post(
        f"{VERSEMENTS}/{-dossier.pk}/versement",
        {"anomaliesAcceptees": True},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_un_dossier_non_clos_ne_se_verse_pas(connecte):
    _regle("Demande")
    dossier = Dossier.objects.create(
        reference="DOS-2026-0002",
        objet="Dossier encore en instruction",
        type_dossier="demande",
        demandeur="Société Camrail",
        structure=Structure.objects.en_vigueur().get(code="DSI"),
        regle_affectation_texte="Règle d'essai.",
        ouvert_le=date.today() - timedelta(days=5),
        echeance=date.today() + timedelta(days=25),
        etape=ETAPE_INSTRUCTION,
    )

    reponse = connecte("archiviste").post(
        f"{VERSEMENTS}/{-dossier.pk}/versement",
        {},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_le_versement_fige_la_duree_et_le_sort_final(connecte):
    """
    Ce qui a ete verse l'a ete sous la regle d'alors. Relire le referentiel
    aurait fait bouger les dates d'elimination a chaque revision — y compris
    celles de dossiers verses dix ans plus tot.
    """
    regle = _regle("Demande", dua=5, sort_final="conservation")
    dossier = _dossier_clos("DOS-2026-0001", clos_il_y_a=0)

    reponse = connecte("archiviste").post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    )
    assert reponse.status_code == 201

    versement = Versement.objects.get(pk=reponse.json()["id"])
    assert versement.dua_appliquee == 5
    assert versement.sort_final_applique == "conservation"
    assert versement.echeance_sort_final.year == date.today().year + 5
    assert versement.etat == ETAT_VERSE

    regle.dua = 30
    regle.sort_final = "destruction"
    regle.save(update_fields=["dua", "sort_final"])

    versement.refresh_from_db()
    assert versement.dua_appliquee == 5
    assert versement.echeance_sort_final.year == date.today().year + 5


def test_un_dossier_ne_se_verse_pas_deux_fois(connecte):
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")
    client = connecte("archiviste")

    premier = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    )
    assert premier.status_code == 201

    second = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    )
    assert second.status_code == 409


def test_le_versement_ouvre_la_chaine_d_empreintes(connecte):
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")
    client = connecte("archiviste")

    identifiant = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    ).json()["id"]

    fiche = client.get(f"{VERSEMENTS}/{identifiant}").json()
    chaine = fiche["chaineIntegrite"]

    assert len(chaine) == 1
    assert chaine[0]["etape"] == "Versement aux archives"
    assert len(chaine[0]["empreinte"]) == 64
    assert fiche["etat"] == "Versé"


# =====================================================================
#  La preuve d'integrite
# =====================================================================


def test_chaque_preuve_chaine_le_maillon_precedent(connecte):
    """
    RF-GED-09 : une empreinte isolee prouve qu'un fichier n'a pas bouge, une
    chaine prouve qu'aucune etape n'a ete retiree entre deux autres.
    """
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")
    client = connecte("archiviste")

    identifiant = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    ).json()["id"]

    for destinataire in ("Cour des comptes", "Direction générale"):
        reponse = client.post(
            f"{VERSEMENTS}/{identifiant}/preuve",
            {"motif": "Contrôle sur pièces", "destinataire": destinataire},
            content_type="application/json",
        )
        assert reponse.status_code == 201

    versement = Versement.objects.get(pk=identifiant)
    maillons = list(versement.maillons.order_by("rang"))

    assert [maillon.rang for maillon in maillons] == [1, 2, 3]
    assert maillons[0].empreinte_precedente is None
    assert maillons[1].empreinte_precedente == maillons[0].empreinte
    assert maillons[2].empreinte_precedente == maillons[1].empreinte


def test_la_preuve_nomme_l_absence_de_tiers_de_confiance(connecte):
    """
    A40 : l'horodatage est celui de l'application. C'est une limite, et elle
    est ecrite dans la reponse plutot que decouverte devant un juge.
    """
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")
    client = connecte("archiviste")

    identifiant = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    ).json()["id"]

    preuve = client.post(
        f"{VERSEMENTS}/{identifiant}/preuve",
        {"motif": "Contrôle sur pièces", "destinataire": "Cour des comptes"},
        content_type="application/json",
    ).json()

    assert preuve["algorithme"] == "SHA-256"
    assert "sans tiers de confiance" in preuve["autorite"]


def test_une_preuve_sans_motif_est_refusee(connecte):
    """Savoir pourquoi la preuve est sortie fait partie de ce qu'elle prouve."""
    _regle("Demande")
    dossier = _dossier_clos("DOS-2026-0001")
    client = connecte("archiviste")

    identifiant = client.post(
        f"{VERSEMENTS}/{-dossier.pk}/versement", {}, content_type="application/json"
    ).json()["id"]

    reponse = client.post(
        f"{VERSEMENTS}/{identifiant}/preuve",
        {"motif": "   ", "destinataire": "Cour des comptes"},
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  La conformite
# =====================================================================


def test_le_taux_de_conformite_est_nul_sur_un_fonds_vide(connecte):
    """
    ADR 011 : sur zero dossier clos, 0 % et 100 % sont aussi faux l'un que
    l'autre — mais eux seraient recopies tels quels dans un rapport.
    """
    corps = connecte("archiviste").get(CONFORMITE).json()
    assert corps["tauxConformite"] is None


def test_est_non_conforme_le_dossier_dont_l_echeance_est_passee_sans_versement(connecte):
    """
    La conformite n'est pas le taux de versement : un dossier clos dont la DUA
    court encore est en regle, meme non verse. Ce qui manque a l'appel, c'est
    celui dont le sort final est echu et que personne n'a traite.
    """
    _regle("Demande", dua=1)
    _dossier_clos("DOS-ECHU", clos_il_y_a=400)
    a_jour = _dossier_clos("DOS-VERSE", clos_il_y_a=400)
    client = connecte("archiviste")

    client.post(f"{VERSEMENTS}/{-a_jour.pk}/versement", {}, content_type="application/json")

    corps = client.get(CONFORMITE).json()
    assert corps["tauxConformite"] == 50.0
    assert [ligne["reference"] for ligne in corps["echeancesDepassees"]] == ["DOS-ECHU"]


def test_une_typologie_sans_regle_est_nommee(connecte):
    """
    La nommer est le seul geste utile : c'est une regle a ecrire, pas un
    dossier a corriger.
    """
    _dossier_clos("DOS-2026-0001", type_dossier="reclamation")

    corps = connecte("archiviste").get(CONFORMITE).json()
    assert "Réclamation" in corps["typologiesSansRegle"]


def test_la_conformite_est_refusee_a_qui_n_est_ni_auditeur_ni_archiviste(connecte):
    assert connecte("dir.dsi").get(CONFORMITE).status_code == 401

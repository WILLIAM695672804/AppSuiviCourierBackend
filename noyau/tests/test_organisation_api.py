"""
L'administration de l'organigramme — `/api/organisation/*`.

Ce routeur ecrit ce que `/api/referentiels/*` se contente de lire, et sous une
autre garde : la derogation de l'ADR 007 ouvre la **lecture** de l'organigramme
a toute session, jamais son ecriture. Les premiers tests portent donc sur cette
frontiere — c'est la seule qui, franchie par erreur, ne produirait aucun
message.

Le reste eprouve ce que l'ecran affiche : les compteurs qui empechent de
modifier un etage a l'aveugle, et la vacance des postes.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import NiveauHierarchique, Poste, Structure

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
STRUCTURES = "/api/organisation/structures"
NIVEAUX = "/api/organisation/niveaux"
POSTES = "/api/organisation/postes"
AFFECTATIONS = "/api/organisation/affectations"


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


def par_libelle(reponse) -> dict[str, dict]:
    return {ligne["libelle"]: ligne for ligne in reponse.json()}


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_l_organigramme_ne_s_administre_pas(client, jeu):
    assert client.get(NIVEAUX).status_code == 401


def test_une_session_sans_ADM_ORG_ne_suffit_pas(connecte):
    """
    La frontiere avec l'ADR 007 : `agent.dsi` lit l'organigramme entier par
    `/referentiels/structures`, et n'ecrit rien ici. 401 et non 403 — c'est ce
    que rend `ExigePermission` sur tout le depot.
    """
    assert connecte("agent.dsi").get(NIVEAUX).status_code == 401
    assert connecte("agent.dsi").get(POSTES).status_code == 401


def test_le_directeur_general_n_administre_pas_l_organigramme(connecte):
    """
    Deux mains distinctes, et l'institution y a tenu : le DG porte toutes les
    permissions metier et pas `ADM_ORG`. Ce test tombe le jour ou un profil
    ramasse l'administration par commodite.
    """
    assert connecte("dg").get(NIVEAUX).status_code == 401


def test_l_administrateur_fonctionnel_administre(connecte):
    assert connecte("admin").get(NIVEAUX).status_code == 200
    assert connecte("admin").get(POSTES).status_code == 200


# =====================================================================
#  Les niveaux
# =====================================================================


def test_les_niveaux_sortent_du_sommet_vers_la_base(connecte):
    rangs = [ligne["rang"] for ligne in connecte("admin").get(NIVEAUX).json()]
    assert rangs == sorted(rangs)


def test_le_chainage_des_niveaux_est_pose_par_la_migration(connecte):
    """
    Le socle seme quatre etages sans les rattacher. La migration 0003 les
    chaine dans l'ordre du rang — c'est le seul rattachement que le semis
    initial permette de deduire sans inventer.
    """
    niveaux = par_libelle(connecte("admin").get(NIVEAUX))

    assert niveaux["Direction Generale"]["niveauParentId"] is None
    assert niveaux["Direction"]["niveauParentId"] == niveaux["Direction Generale"]["id"]
    assert niveaux["Service"]["niveauParentId"] == niveaux["Departement"]["id"]


def test_seule_la_direction_generale_porte_la_signature(connecte):
    """B-04 : le numero de depart s'attribue a la signature, et elle appartient
    au sommet."""
    niveaux = par_libelle(connecte("admin").get(NIVEAUX))

    assert niveaux["Direction Generale"]["porteSignature"] is True
    assert [n["libelle"] for n in niveaux.values() if n["porteSignature"]] == ["Direction Generale"]


def test_les_compteurs_ne_retiennent_que_les_lignes_en_vigueur(connecte):
    """
    Ce sont eux qui portent l'avertissement de l'ecran — « 4 structures
    utilisent ce niveau ». Compter une direction dissoute ferait refuser une
    modification que rien n'empeche.
    """
    from noyau.journal.contexte import acteur as contexte_acteur
    from noyau.organisation.modeles import Structure

    avant = par_libelle(connecte("admin").get(NIVEAUX))["Direction"]["nombreStructures"]

    dissoute = Structure.objects.en_vigueur().get(code="DCG")
    with contexte_acteur(Utilisateur.objects.get(identifiant_annuaire="dsr")):
        dissoute.valide_au = date.today()
        dissoute.save(update_fields=["valide_au"])

    apres = par_libelle(connecte("admin").get(NIVEAUX))["Direction"]["nombreStructures"]
    assert apres == avant - 1


def test_creer_un_niveau_l_inscrit_au_journal(connecte):
    reponse = connecte("admin").post(
        NIVEAUX,
        {
            "code": "BUR",
            "libelle": "Bureau",
            # Les rangs 1 a 6 sont tenus depuis la migration 0017 (DG, DIR,
            # DIR_ADJ, SOUS_DIR, DEP, SERV). Le bureau se pose sous le service.
            "rang": 7,
            "peutCoter": False,
            "porteSignature": False,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert reponse.json()["libelle"] == "Bureau"
    # Un etage neuf ne porte rien : c'est ce que le registre doit dire.
    assert reponse.json()["nombreStructures"] == 0
    assert _dernier_evenement("niveau_cree") is not None


def test_un_rang_deja_tenu_est_refuse(connecte):
    """
    Le socle porte un index unique partiel sur le rang. Sans ce refus, une
    faute de frappe rendrait un 500 au lieu d'une phrase lisible.
    """
    reponse = connecte("admin").post(
        NIVEAUX,
        {"code": "AUTRE", "libelle": "Autre direction", "rang": 2},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert "Direction" in reponse.json()["message"]
    assert reponse.json()["code"] == "rang_pris"


def test_un_code_deja_pris_est_refuse(connecte):
    reponse = connecte("admin").post(
        NIVEAUX,
        {"code": "DIR", "libelle": "Direction bis", "rang": 9},
        content_type="application/json",
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "code_niveau_pris"


def test_modifier_ne_touche_que_ce_qui_est_envoye(connecte):
    """
    `None` veut dire « ne touche pas ». Sans cette distinction, un formulaire
    qui n'envoie que le libelle decocherait les quatre autorisations.
    """
    niveau = NiveauHierarchique.objects.get(code="DG")
    reponse = connecte("admin").patch(
        f"{NIVEAUX}/{niveau.pk}",
        {"libelle": "Direction Generale du Port"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    assert reponse.json()["libelle"] == "Direction Generale du Port"
    assert reponse.json()["porteSignature"] is True


def test_un_niveau_ne_se_rattache_pas_a_lui_meme(connecte):
    """Une boucle rendrait l'arbre infini a l'affichage — le seul defaut qu'un
    utilisateur ne peut pas contourner."""
    niveau = NiveauHierarchique.objects.get(code="SERV")
    reponse = connecte("admin").patch(
        f"{NIVEAUX}/{niveau.pk}",
        {"niveauParentId": niveau.pk},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "niveau_parent_reflexif"


def test_le_rang_ne_se_modifie_pas(connecte):
    """
    Il ordonne tout le referentiel. Le schema ne l'accepte pas : envoye, il est
    ignore — django-ninja ne rend pas d'erreur sur un champ inconnu, et c'est
    voulu ici, l'ecran ne le propose pas.
    """
    niveau = NiveauHierarchique.objects.get(code="SERV")
    connecte("admin").patch(f"{NIVEAUX}/{niveau.pk}", {"rang": 1}, content_type="application/json")

    niveau.refresh_from_db()
    assert niveau.rang == 6  # SERV, pousse au rang 6 par la migration 0017


def test_une_modification_sans_ecart_n_inscrit_rien(connecte):
    """Un evenement qui enregistre huit valeurs identiques ne dit plus rien de
    ce qui s'est passe."""
    niveau = NiveauHierarchique.objects.get(code="DG")
    avant = _compter_evenements("niveau_modifie")

    connecte("admin").patch(
        f"{NIVEAUX}/{niveau.pk}",
        {"libelle": niveau.libelle, "porteSignature": True},
        content_type="application/json",
    )

    assert _compter_evenements("niveau_modifie") == avant


# =====================================================================
#  Les postes
# =====================================================================


def test_le_poste_porte_le_libelle_du_niveau_pas_son_rang(connecte):
    """C'est un tableau qu'on lit : « Service » se lit mieux que « 4 ». Le
    referentiel de saisie, lui, rend le rang."""
    postes = connecte("admin").get(POSTES).json()
    assert all(isinstance(p["niveau"], str) for p in postes)
    assert "Direction Generale" in {p["niveau"] for p in postes}


def test_un_poste_sans_profil_par_defaut_le_dit(connecte):
    """« Non defini » et jamais une chaine vide : une cellule vide se lit comme
    une donnee manquante a l'affichage, pas comme un choix."""
    postes = connecte("admin").get(POSTES).json()
    assert {p["profilParDefaut"] for p in postes} == {"Non defini"}


def test_un_compte_suspendu_libere_le_poste(connecte):
    """
    C'est la vacance que l'ecran doit montrer : compter un compte suspendu
    parmi les titulaires masquerait le trou dans le circuit.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    poste_id = agent.poste_id

    avant = {p["id"]: p for p in connecte("admin").get(POSTES).json()}[poste_id]
    assert avant["titulaires"] == 1

    agent.actif = False
    agent.save(update_fields=["actif"])

    apres = {p["id"]: p for p in connecte("admin").get(POSTES).json()}[poste_id]
    assert apres["titulaires"] == 0
    assert apres["postesPrevus"] == 1


def test_un_poste_clos_disparait_du_registre(connecte):
    poste = Poste.objects.en_vigueur().first()
    assert poste is not None
    poste.valide_au = date.today()
    poste.save(update_fields=["valide_au"])

    assert poste.pk not in {p["id"] for p in connecte("admin").get(POSTES).json()}


# =====================================================================
#  Les postes en ecriture — F-03
# =====================================================================


def test_un_poste_s_ouvre_sans_occupant(connecte):
    """
    Le poste est l'unite de la hierarchie, pas l'agent. Un poste vacant est un
    objet normal — c'est meme ce que l'ecran cherche a rendre visible.
    """
    structure = Structure.objects.en_vigueur().get(code="DSI")
    niveau = NiveauHierarchique.objects.get(code="SERV")

    reponse = connecte("admin").post(
        POSTES,
        {
            "structureId": structure.pk,
            "libelle": "Chef de la division reseaux",
            "niveauId": niveau.pk,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["titulaires"] == 0
    assert corps["postesPrevus"] == 1
    assert corps["structure"] == "DSI"
    # Le registre rend le libelle du niveau, pas son rang : c'est une lecture.
    assert corps["niveau"] == niveau.libelle


def test_l_ouverture_d_un_poste_s_inscrit_au_journal(connecte):
    avant = _compter_evenements("poste_cree")
    structure = Structure.objects.en_vigueur().get(code="DAF")
    niveau = NiveauHierarchique.objects.get(code="SERV")

    connecte("admin").post(
        POSTES,
        {"structureId": structure.pk, "libelle": "Agent comptable", "niveauId": niveau.pk},
        content_type="application/json",
    )

    assert _compter_evenements("poste_cree") == avant + 1
    assert "Agent comptable" in _dernier_evenement("poste_cree")


def test_un_effectif_de_zero_est_refuse(connecte):
    structure = Structure.objects.en_vigueur().first()
    niveau = NiveauHierarchique.objects.get(code="SERV")

    reponse = connecte("admin").post(
        POSTES,
        {
            "structureId": structure.pk,
            "libelle": "Poste fantome",
            "niveauId": niveau.pk,
            "effectifPrevu": 0,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "effectif_nul"


def test_un_effectif_invraisemblable_renvoie_a_la_question_ouverte(connecte):
    """
    Le plafond est une **hypothese** (A22), et le message le dit : « faites
    trancher A22 ». Un refus qui n'indique pas ou est ecrite la regle qu'il
    applique se lit comme un caprice du logiciel.
    """
    structure = Structure.objects.en_vigueur().first()
    niveau = NiveauHierarchique.objects.get(code="SERV")

    reponse = connecte("admin").post(
        POSTES,
        {
            "structureId": structure.pk,
            "libelle": "Bureau entier",
            "niveauId": niveau.pk,
            "effectifPrevu": 100,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert "A22" in reponse.json()["message"]


def test_le_superieur_d_un_poste_peut_relever_d_une_autre_structure(connecte):
    """
    C'est le cas ordinaire, pas l'exception : le superieur d'un directeur est le
    Directeur general, qui ne releve pas de la direction. Le refuser aurait casse
    la remontee au sommet.
    """
    sommet = Poste.objects.en_vigueur().filter(structure__code="DG").first()
    assert sommet is not None
    structure = Structure.objects.en_vigueur().get(code="DSI")
    niveau = NiveauHierarchique.objects.get(code="DIR")

    reponse = connecte("admin").post(
        POSTES,
        {
            "structureId": structure.pk,
            "libelle": "Directeur adjoint des systemes",
            "niveauId": niveau.pk,
            "posteSuperieurId": sommet.pk,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert reponse.json()["posteSuperieurId"] == sommet.pk


def test_un_poste_ne_peut_pas_devenir_son_propre_superieur(connecte):
    poste = Poste.objects.en_vigueur().first()

    reponse = connecte("admin").patch(
        f"{POSTES}/{poste.pk}",
        {"posteSuperieurId": poste.pk},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "poste_superieur_reflexif"


def test_un_rattachement_qui_boucle_est_refuse(connecte):
    """
    Sans ce refus, la remontee au sommet tourne indefiniment, et l'erreur
    apparait a la validation d'un courrier — pas a la saisie qui l'a causee.
    """
    chef = Poste.objects.en_vigueur().first()
    subordonne = Poste.objects.en_vigueur().exclude(pk=chef.pk).first()
    subordonne.poste_superieur = chef
    subordonne.save(update_fields=["poste_superieur"])

    reponse = connecte("admin").patch(
        f"{POSTES}/{chef.pk}",
        {"posteSuperieurId": subordonne.pk},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "cycle_hierarchique"


def test_la_structure_d_un_poste_ne_se_modifie_pas(connecte):
    """
    Elle n'est pas dans le schema de modification, et c'est delibere : deplacer
    un poste d'une direction a une autre ferait suivre l'historique des
    affectations, comme si les agents y avaient toujours travaille.
    """
    poste = Poste.objects.en_vigueur().select_related("structure").first()
    ailleurs = Structure.objects.en_vigueur().exclude(pk=poste.structure_id).first()

    reponse = connecte("admin").patch(
        f"{POSTES}/{poste.pk}",
        {"structureId": ailleurs.pk},
        content_type="application/json",
    )

    # Le champ inconnu est ignore par le schema : la structure ne bouge pas.
    assert reponse.status_code == 200
    assert reponse.json()["structure"] == poste.structure.code


def test_un_poste_occupe_ne_se_clot_pas(connecte):
    """
    L'agent se retrouverait rattache a un poste hors vigueur, invisible de tous
    les selecteurs, et son perimetre `poste` ne rendrait plus rien — sans
    qu'aucune erreur ne le dise.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")

    reponse = connecte("admin").post(
        f"{POSTES}/{agent.poste_id}/cloture",
        {"motif": "Reorganisation."},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "poste_occupe"


def test_un_poste_dont_des_subordonnes_dependent_ne_se_clot_pas(connecte):
    """
    Le chef est **vacant** a dessein : occupe, c'est l'autre refus qui aurait
    repondu, et le test n'aurait rien prouve de celui-ci.
    """
    chef = _poste_vacant()
    subordonne = Poste.objects.en_vigueur().exclude(pk=chef.pk).first()
    subordonne.poste_superieur = chef
    subordonne.save(update_fields=["poste_superieur"])

    reponse = connecte("admin").post(
        f"{POSTES}/{chef.pk}/cloture",
        {"motif": "Suppression du poste."},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "poste_avec_subordonnes"


def test_un_poste_vacant_se_clot_et_disparait_du_registre(connecte):
    structure = Structure.objects.en_vigueur().first()
    niveau = NiveauHierarchique.objects.get(code="SERV")
    cree = (
        connecte("admin")
        .post(
            POSTES,
            {"structureId": structure.pk, "libelle": "Poste provisoire", "niveauId": niveau.pk},
            content_type="application/json",
        )
        .json()
    )

    reponse = connecte("admin").post(
        f"{POSTES}/{cree['id']}/cloture",
        {"motif": "Ouvert par erreur."},
        content_type="application/json",
    )

    assert reponse.status_code == 204
    assert cree["id"] not in {p["id"] for p in connecte("admin").get(POSTES).json()}
    # La ligne n'est pas effacee : principe 1 de `modeles.py`.
    assert Poste.objects.filter(pk=cree["id"]).exists()


# =====================================================================
#  Les affectations — F-04
# =====================================================================


def test_le_semis_a_date_les_affectations_en_cours(connecte):
    """
    La migration ouvre une ligne pour chaque agent deja en poste. Sans elle,
    l'histoire commencerait a la premiere mutation, et ferait croire que
    personne n'a jamais occupe de poste auparavant.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    lignes = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()

    assert len(lignes) == 1
    assert lignes[0]["enCours"] is True
    assert lignes[0]["posteId"] == agent.poste_id


def test_un_compte_du_portail_n_a_aucune_affectation(connecte):
    """Les comptes usagers n'ont ni structure, ni poste (ADR 013) : le semis ne
    doit pas leur en inventer une."""
    usager = Utilisateur.objects.get(identifiant_annuaire="usager.sotrapal")
    assert connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={usager.pk}").json() == []


def test_une_mutation_clot_la_precedente_la_veille(connecte):
    """
    Deux occupations ne se chevauchent pas d'une journee. Sur un poste de
    validation, une journee a deux titulaires est une journee ou deux personnes
    ont pu signer au meme titre.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    ailleurs = Poste.objects.en_vigueur().exclude(pk=agent.poste_id).first()
    prise = date.today() + timedelta(days=7)

    reponse = connecte("admin").post(
        AFFECTATIONS,
        {
            "utilisateurId": agent.pk,
            "posteId": ailleurs.pk,
            "debut": prise.isoformat(),
            "motif": "Mutation.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201

    lignes = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()
    close = next(ligne for ligne in lignes if not ligne["enCours"])
    ouverte = next(ligne for ligne in lignes if ligne["enCours"])

    assert close["fin"] == (prise - timedelta(days=1)).isoformat()
    assert ouverte["debut"] == prise.isoformat()


def test_la_mutation_deplace_aussi_la_colonne_du_present(connecte):
    """
    La colonne dit le present, la table dit l'histoire, et les deux s'ecrivent
    ensemble (ADR 015). Les laisser diverger produirait un agent affiche a la
    DAF et cote a la DSI, sans qu'aucune des deux vues n'ait tort.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    ailleurs = (
        Poste.objects.en_vigueur()
        .exclude(structure_id=agent.structure_id)
        .select_related("structure")
        .first()
    )

    connecte("admin").post(
        AFFECTATIONS,
        {"utilisateurId": agent.pk, "posteId": ailleurs.pk},
        content_type="application/json",
    )

    agent.refresh_from_db()
    assert agent.poste_id == ailleurs.pk
    assert agent.structure_id == ailleurs.structure_id


def test_reaffecter_au_meme_poste_est_refuse(connecte):
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")

    reponse = connecte("admin").post(
        AFFECTATIONS,
        {"utilisateurId": agent.pk, "posteId": agent.poste_id},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "affectation_inchangee"


def test_une_fin_sans_suite_rend_le_poste_vacant(connecte):
    """
    C'est le depart, la retraite, la mise a disposition. L'agent se retrouve
    sans poste, et le tableau de bord compte le poste comme vacant — ce qu'on
    veut voir, pas ce qu'on veut cacher.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    poste_id = agent.poste_id
    ligne = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()[0]

    reponse = connecte("admin").post(
        f"{AFFECTATIONS}/{ligne['id']}/fin",
        {"motif": "Depart a la retraite."},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    assert reponse.json()["enCours"] is False

    agent.refresh_from_db()
    assert agent.poste_id is None

    postes = {p["id"]: p for p in connecte("admin").get(POSTES).json()}
    assert postes[poste_id]["titulaires"] == 0


def test_une_affectation_deja_close_ne_se_referme_pas(connecte):
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    ligne = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()[0]
    connecte("admin").post(
        f"{AFFECTATIONS}/{ligne['id']}/fin",
        {"motif": "Depart."},
        content_type="application/json",
    )

    reponse = connecte("admin").post(
        f"{AFFECTATIONS}/{ligne['id']}/fin",
        {"motif": "Depart, encore."},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "affectation_close"


def test_une_fin_anterieure_au_debut_est_refusee(connecte):
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    ligne = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()[0]

    reponse = connecte("admin").post(
        f"{AFFECTATIONS}/{ligne['id']}/fin",
        {
            "fin": (date.fromisoformat(ligne["debut"]) - timedelta(days=1)).isoformat(),
            "motif": "Erreur de saisie.",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "fin_avant_debut"


def test_la_fiche_du_compte_date_desormais_la_mutation(connecte):
    """
    Le point de l'ADR 015 : `modifier_compte` ecrivait `agent.poste`
    directement, et effacait l'occupant precedent. Il passe desormais par le
    service, et l'histoire s'ecrit meme quand la mutation vient d'un autre ecran.
    """
    agent = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    # Un second poste **dans la meme structure** : la route refuse un poste qui
    # ne releve pas de la structure envoyee, et ce n'est pas ce qu'on eprouve ici.
    ailleurs = Poste.objects.create(
        structure_id=agent.structure_id,
        libelle="Second agent des systemes",
        niveau_hierarchique_id=agent.poste.niveau_hierarchique_id,
        valide_du=date.today(),
    )

    connecte("admin").patch(
        f"/api/habilitations/utilisateurs/{agent.pk}",
        {"posteId": ailleurs.pk},
        content_type="application/json",
    )

    lignes = connecte("admin").get(f"{AFFECTATIONS}?utilisateurId={agent.pk}").json()
    assert len(lignes) == 2
    assert next(ligne for ligne in lignes if ligne["enCours"])["posteId"] == ailleurs.pk


def test_les_affectations_ne_s_administrent_pas_sans_ADM_ORG(connecte):
    assert connecte("agent.dsi").get(AFFECTATIONS).status_code == 401


# =====================================================================
#  Les structures — F-01
#
#  Elles s'ecrivaient sur `/gouvernance`, sous `ADM_STR`, permission de la DSR.
#  L'ADR 021 les a ramenees ici : creer une structure ouvre un poste, et c'est
#  le meme administrateur qui pourvoit ce poste ensuite.
# =====================================================================


def test_une_structure_ne_se_cree_pas_sans_ADM_ORG(connecte):
    """
    La DSR tenait ce geste. Elle ne le tient plus : elle lit le referentiel
    comme toute session (ADR 007), elle ne l'ecrit pas.
    """
    reponse = connecte("dsr").post(
        STRUCTURES,
        {"libelle": "Division nouvelle", "sigle": "DNV", "nature": "Division", "niveau": 3},
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_creer_une_structure_inscrit_un_evenement(connecte):
    avant = _compter_evenements("structure_creee")

    reponse = connecte("admin").post(
        STRUCTURES,
        {
            "libelle": "Division du controle interne",
            "sigle": "DCI",
            "nature": "Division",
            "niveau": 3,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert Structure.objects.filter(code="DCI", valide_au__isnull=True).exists()
    assert _compter_evenements("structure_creee") == avant + 1


def test_creer_une_structure_ouvre_son_poste_responsable(connecte):
    """
    Le couple qui justifie que la route vive ici : la structure et le poste
    vacant qui la surmonte s'ecrivent d'un seul mouvement. Une structure sans
    poste sommet n'accepterait aucune fille et ne pourrait recevoir personne.
    """
    parent = Structure.objects.en_vigueur().get(code="DG")
    superieur = Poste.objects.en_vigueur().get(structure=parent, libelle="Directeur General")

    reponse = connecte("admin").post(
        STRUCTURES,
        {
            "libelle": "Direction de la transformation",
            "sigle": "DTR",
            "nature": "Direction",
            "niveau": 2,
            "parentId": parent.pk,
            "posteResponsableLibelle": "Directeur de la transformation",
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    nouvelle = Structure.objects.get(pk=reponse.json()["id"])
    poste = Poste.objects.en_vigueur().select_related("profil_par_defaut").get(structure=nouvelle)

    assert nouvelle.parent_id == parent.pk
    assert poste.libelle == "Directeur de la transformation"
    assert poste.poste_superieur_id == superieur.pk
    assert poste.profil_par_defaut.code == "RESP"
    assert "Directeur de la transformation" in _dernier_evenement("poste_cree")


def test_creer_une_structure_refuse_un_parent_sans_poste_responsable(connecte):
    parent = Structure.objects.create(
        code="DOP",
        libelle="Direction orpheline",
        parent=Structure.objects.en_vigueur().get(code="DG"),
        niveau_hierarchique=NiveauHierarchique.objects.get(code="DIR"),
        nature="Direction",
        valide_du=date.today(),
    )

    reponse = connecte("admin").post(
        STRUCTURES,
        {
            "libelle": "Service sans rattachement possible",
            "sigle": "SSRP",
            "nature": "Service",
            "niveau": 4,
            "parentId": parent.pk,
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "poste_parent_absent"
    assert not Structure.objects.filter(code="SSRP", valide_au__isnull=True).exists()


def test_un_sigle_en_vigueur_ne_se_reprend_pas(connecte):
    """Un sigle se libere a la dissolution, pas avant : deux « DSI » en vigueur
    rendraient fausse toute lecture qui part du sigle."""
    reponse = connecte("admin").post(
        STRUCTURES,
        {"libelle": "Autre DSI", "sigle": "DSI", "nature": "Direction", "niveau": 1},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_une_nature_inconnue_est_refusee(connecte):
    reponse = connecte("admin").post(
        STRUCTURES,
        # « Cellule » etait le contre-exemple avant la migration 0017, qui l'a
        # fait entrer dans les douze natures du Port. Il en faut un vrai.
        {"libelle": "Escouade", "sigle": "ESC", "nature": "Escouade", "niveau": 3},
        content_type="application/json",
    )
    assert reponse.status_code == 409


# =====================================================================
#  Outils
# =====================================================================


def _poste_vacant() -> Poste:
    """
    Un poste que personne n'occupe, **cree pour l'occasion**.

    Le semis pose exactement un poste par compte et n'en laisse aucun libre.
    Chercher un vacant dans le jeu d'essai rendrait le test dependant du nombre
    de comptes semes, qui bouge a chaque profil ajoute.
    """
    modele = Poste.objects.en_vigueur().select_related("structure").first()
    assert modele is not None
    return Poste.objects.create(
        structure=modele.structure,
        libelle="Poste vacant de circonstance",
        niveau_hierarchique=modele.niveau_hierarchique,
        valide_du=date.today(),
    )


def _compter_evenements(type_evenement: str) -> int:
    from django.db import connection

    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT count(*) FROM evenement WHERE type_evenement = %s", [type_evenement]
        )
        return curseur.fetchone()[0]


def _dernier_evenement(type_evenement: str):
    from django.db import connection

    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT libelle FROM evenement WHERE type_evenement = %s "
            "ORDER BY survenu_le DESC LIMIT 1",
            [type_evenement],
        )
        ligne = curseur.fetchone()
        return ligne[0] if ligne else None

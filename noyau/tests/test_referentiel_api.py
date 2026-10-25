"""
Le referentiel de l'organigramme — `GET /api/referentiels/structures`.

Cette route est la seule du depot qui ne passe pas par `restreindre()`
(ADR 007). Les tests portent donc autant sur ce qu'elle **montre** que sur ce
qu'elle refuse : un agent de portee « propre » doit voir tout l'organigramme,
sans quoi il ne peut plus coter ; et aucun chiffre d'activite ne doit s'y
glisser, faute de source.
"""

from datetime import date

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur as contexte_acteur
from noyau.organisation.modeles import Structure

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
CHEMIN = "/api/referentiels/structures"


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


def par_sigle(reponse) -> dict[str, dict]:
    return {ligne["sigle"]: ligne for ligne in reponse.json()}


def _postes(connecte, structure_id: int | None) -> list[dict]:
    """Les postes, filtres ou non. `None` rend la liste complete."""
    chemin = "/api/referentiels/postes"
    if structure_id is not None:
        chemin = f"{chemin}?structureId={structure_id}"
    reponse = connecte("admin").get(chemin)
    assert reponse.status_code == 200
    return reponse.json()


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_le_referentiel_est_refuse(client, jeu):
    assert client.get(CHEMIN).status_code == 401


def test_une_session_sans_permission_suffit(connecte):
    """
    `agent.dsi` porte le profil COLLAB, portee « propre ». C'est le cas limite
    de l'ADR 007 : sans cette route, il ne pourrait coter vers aucune structure.
    """
    assert connecte("agent.dsi").get(CHEMIN).status_code == 200


def test_le_perimetre_ne_reduit_pas_la_liste(connecte):
    """Un agent de portee « propre » voit le meme organigramme que le DG."""
    etroit = par_sigle(connecte("agent.dsi").get(CHEMIN))
    large = par_sigle(connecte("dg").get(CHEMIN))
    assert (
        set(etroit)
        == set(large)
        == set(Structure.objects.en_vigueur().values_list("code", flat=True))
    )


# =====================================================================
#  Ce que la route renvoie
# =====================================================================


def test_une_structure_close_ne_sort_plus(connecte):
    """
    Une direction dissoute garde sa ligne pour l'histoire, mais elle ne doit
    plus pouvoir etre choisie dans un selecteur.
    """
    dissoute = Structure.objects.en_vigueur().get(code="DCG")
    # Le declencheur de tracabilite refuse une modification de structure sans
    # acteur identifie (RNF-TRACE-01) : meme dans un test, on cloture au nom
    # de quelqu'un.
    with contexte_acteur(Utilisateur.objects.get(identifiant_annuaire="dsr")):
        dissoute.valide_au = date.today()
        dissoute.save(update_fields=["valide_au"])

    assert "DCG" not in par_sigle(connecte("dg").get(CHEMIN))


def test_le_niveau_est_le_rang_pas_une_profondeur(connecte):
    """
    Meme nombre en lecture et en ecriture : `POST /organisation/structures`
    recoit un rang (`creer_structure`), la lecture en renvoie un.
    Rang 1 = Direction Generale.
    """
    lignes = par_sigle(connecte("dg").get(CHEMIN))
    assert lignes["DG"]["niveau"] == 1
    assert lignes["DSI"]["niveau"] == 2
    assert lignes["DSI-ET"]["niveau"] == 6  # service, descendu par la migration 0017


def test_le_responsable_est_deduit_du_poste(connecte):
    """
    Il n'existe pas de colonne « responsable » sur `structure` : le nom vient
    de l'agent en poste. Le jeu d'essai place Emmanuel Kingue a la DG.
    """
    assert par_sigle(connecte("dg").get(CHEMIN))["DG"]["responsable"] == "Emmanuel Kingue"


def test_une_structure_sans_agent_sort_sans_responsable(connecte):
    """`None` et non une chaine vide : l'ecran affiche « Non designe »."""
    Structure.objects.create(
        code="DTM",
        libelle="Direction Technique et Maritime",
        niveau_hierarchique=Structure.objects.en_vigueur().get(code="DSI").niveau_hierarchique,
        nature="Direction",
        valide_du=date.today(),
    )

    assert par_sigle(connecte("dg").get(CHEMIN))["DTM"]["responsable"] is None


def test_le_parent_fait_l_arbre_la_ou_le_rang_ne_fait_qu_indenter(connecte):
    """
    Sans `parentId`, deux services de rang egal rattaches a deux directions
    differentes s'affichaient au meme retrait, cote a cote, comme s'ils etaient
    freres. C'est ce champ, et lui seul, qui les separe.
    """
    lignes = par_sigle(connecte("dg").get(CHEMIN))

    assert lignes["DG"]["parentId"] is None
    assert lignes["DSI"]["parentId"] == lignes["DG"]["id"]
    assert lignes["DSI-ET"]["parentId"] == lignes["DSI"]["id"]

    # Le cas que le rang seul ne distinguait pas : meme niveau, peres opposes.
    assert lignes["DSI-ET"]["niveau"] == lignes["DAF-CP"]["niveau"]
    assert lignes["DSI-ET"]["parentId"] != lignes["DAF-CP"]["parentId"]


def test_un_seul_sommet_dans_le_jeu_d_essai(connecte):
    """
    Plusieurs racines ne sont pas interdites — une filiale peut n'etre
    rattachee a rien — mais l'organigramme d'essai n'en a qu'une. Ce test tombe
    le jour ou un semis casse un rattachement, ce que rien d'autre ne dirait.
    """
    lignes = connecte("dg").get(CHEMIN).json()
    assert [ligne["sigle"] for ligne in lignes if ligne["parentId"] is None] == ["DG"]


def test_aucune_structure_ne_pend_dans_le_vide(connecte):
    """
    Un `parentId` rendu brut peut designer une structure close (voir
    `lecture.referentiel_structures`). Le front l'affiche alors a la racine et
    le signale ; le jeu d'essai, lui, ne doit pas presenter ce defaut.
    """
    lignes = connecte("dg").get(CHEMIN).json()
    connus = {ligne["id"] for ligne in lignes}
    assert all(ligne["parentId"] in connus for ligne in lignes if ligne["parentId"] is not None)


def test_aucun_chiffre_d_activite_n_est_invente(connecte):
    """
    Borne 3 de l'ADR 007. Le pilier courrier n'existe pas : une moyenne
    fabriquee serait recopiee dans un rapport avant d'etre corrigee.
    """
    for ligne in connecte("dg").get(CHEMIN).json():
        assert ligne["delaiMoyenJours"] is None
        assert ligne["courriersEnCours"] == 0


def test_l_ordre_va_du_sommet_vers_la_base(connecte):
    """Les selecteurs du front n'ordonnent pas : ils affichent ce qu'on envoie."""
    niveaux = [ligne["niveau"] for ligne in connecte("dg").get(CHEMIN).json()]
    assert niveaux == sorted(niveaux)


# =====================================================================
#  Les postes — `GET /api/referentiels/postes`
# =====================================================================
#
#  Meme derogation que les structures (ADR 007) : affecter un agent ailleurs
#  suppose de voir les postes d'une structure hors de son propre perimetre.


def test_les_postes_exigent_une_session(client, jeu):
    assert client.get("/api/referentiels/postes").status_code == 401


def test_les_postes_se_filtrent_par_structure(connecte):
    """Sans filtre, un selecteur melerait des « Chef de service » homonymes de
    directions differentes."""
    dsi = Structure.objects.get(code="DSI", valide_au__isnull=True)
    reponse = connecte("agent.dsi").get(f"/api/referentiels/postes?structureId={dsi.pk}")
    assert reponse.status_code == 200
    assert reponse.json()
    assert {p["structure"] for p in reponse.json()} == {"DSI"}


def test_un_agent_de_portee_propre_voit_les_postes_d_une_autre_direction(connecte):
    """La derogation ADR 007 : sans elle, l'administrateur ne pourrait pas muter
    un agent vers une structure qu'il ne lit pas."""
    daf = Structure.objects.get(code="DAF", valide_au__isnull=True)
    reponse = connecte("agent.dsi").get(f"/api/referentiels/postes?structureId={daf.pk}")
    assert reponse.status_code == 200
    assert reponse.json()


def test_le_poste_remonte_a_son_sommet_local(connecte):
    """
    Principe 2 de `organisation/modeles.py` : c'est le poste qui porte la
    hierarchie. Le point focal de la DSI remonte a la directrice, pas a un
    agent nomme.
    """
    dsi = Structure.objects.get(code="DSI", valide_au__isnull=True)
    postes = {p["libelle"]: p for p in _postes(connecte, dsi.pk)}

    assert postes["Point focal"]["posteSuperieurId"] == postes["Directrice"]["id"]


def test_le_sommet_d_une_structure_remonte_a_la_structure_parente(connecte):
    """
    La regle qui franchit les structures : un directeur ne rend pas compte a un
    autre directeur, mais au Directeur general. C'est ce chainage que le filtre
    par structure ne peut pas montrer — d'ou la lecture sans filtre.
    """
    tous = {p["libelle"]: p for p in _postes(connecte, None)}

    assert tous["Directrice"]["posteSuperieurId"] == tous["Directeur General"]["id"]
    assert tous["Directeur General"]["posteSuperieurId"] is None


def test_le_superieur_peut_pointer_hors_de_la_liste_filtree(connecte):
    """
    Le piege documente : filtrer par structure tronque l'arbre. Le superieur de
    la directrice de la DSI est un poste de la DG, absent du lot rendu — un
    appelant qui construirait l'arbre sur une liste filtree croirait a une
    racine.
    """
    dsi = Structure.objects.get(code="DSI", valide_au__isnull=True)
    lot = _postes(connecte, dsi.pk)
    identifiants = {p["id"] for p in lot}
    directrice = next(p for p in lot if p["libelle"] == "Directrice")

    assert directrice["posteSuperieurId"] is not None
    assert directrice["posteSuperieurId"] not in identifiants


def test_un_poste_clos_ne_sort_plus(connecte):
    """Un poste supprime garde sa ligne pour l'histoire, mais ne doit plus etre
    proposable."""
    from noyau.organisation.modeles import Poste

    dsi = Structure.objects.get(code="DSI", valide_au__isnull=True)
    poste = Poste.objects.filter(structure=dsi, valide_au__isnull=True).first()
    poste.valide_au = date.today()
    poste.save(update_fields=["valide_au"])

    ids = {
        p["id"]
        for p in connecte("admin").get(f"/api/referentiels/postes?structureId={dsi.pk}").json()
    }
    assert poste.pk not in ids


# =====================================================================
#  L'annuaire des agents — /api/referentiels/agents (ADR 020)
# =====================================================================


def _agents(connecte, identifiant: str = "agent.dsi", structure_id: int | None = None):
    chemin = "/api/referentiels/agents"
    if structure_id is not None:
        chemin += f"?structureId={structure_id}"
    return connecte(identifiant).get(chemin).json()


def test_un_agent_de_portee_propre_voit_tout_l_annuaire(connecte):
    """
    Meme motif que l'organigramme (ADR 007) : on designe un responsable qu'on
    ne « voit » pas au sens du perimetre. Borner cette route au perimetre
    rendrait la designation impossible — c'est exactement le mur que la saisie
    libre cachait.
    """
    lot = _agents(connecte)
    noms = {a["nomComplet"] for a in lot}

    assert "Emmanuel Kingue" in noms
    assert len(noms) > 1


def test_l_annuaire_ne_porte_que_l_identite_de_travail(connecte):
    """
    Garde large ne veut pas dire lot large : la route rend de quoi choisir et
    afficher, rien de plus. Pas d'adresse, pas de portee, pas d'habilitation.
    """
    fiche = _agents(connecte)[0]

    assert set(fiche) == {"id", "nomComplet", "poste", "structure", "structureId"}


def test_le_filtre_par_structure_borne_l_annuaire(connecte):
    dsi = Structure.objects.get(code="DSI", valide_au__isnull=True)
    lot = _agents(connecte, structure_id=dsi.pk)

    assert lot
    assert {a["structure"] for a in lot} == {"DSI"}


def test_un_agent_desactive_ne_se_designe_plus(connecte):
    """
    La contrepartie de la garde large : l'annuaire est la seule barriere entre
    un compte clos et une designation. Il l'applique en lecture, et le service
    la reapplique a l'ecriture.
    """
    rita = Utilisateur.objects.get(identifiant_annuaire="dir.dsi")
    rita.actif = False
    rita.save(update_fields=["actif"])

    assert rita.pk not in {a["id"] for a in _agents(connecte)}


def test_l_annuaire_exige_une_session(client, jeu):
    assert client.get("/api/referentiels/agents").status_code == 401

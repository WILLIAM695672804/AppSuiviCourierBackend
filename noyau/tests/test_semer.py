"""
La commande `semer` est le seul moyen d'avoir des comptes en developpement.
Si elle casse, le backend devient intestable sans que rien ne le signale —
d'ou ces tests, qui la font tourner pour de vrai.

Ils verifient surtout ce qu'un coup d'oeil ne montre pas : que les perimetres
poses cloisonnent reellement.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from noyau.habilitation.resolution import comptes_du_portail, permissions_de
from noyau.identite.modeles import Utilisateur
from noyau.perimetre.portee import perimetre_en_vigueur, structures_visibles

# Django force DEBUG a False pendant les tests : la commande refuserait de
# s'executer, ce qui est precisement le comportement attendu ailleurs.
FORCER = {"force": True}


@pytest.fixture
def jeu_dessai(db):
    call_command("semer", **FORCER)


def _compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


def test_la_commande_refuse_de_semer_hors_developpement(db):
    """Le garde-fou est la raison d'etre du drapeau --force."""
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("semer")


def test_semer_deux_fois_ne_cree_pas_de_doublon(db):
    call_command("semer", **FORCER)
    premier = Utilisateur.objects.count()
    call_command("semer", **FORCER)
    assert Utilisateur.objects.count() == premier


def test_les_comptes_peuvent_se_connecter(jeu_dessai):
    assert _compte("focal.dsi").check_password("demonstration")


def test_le_mot_de_passe_est_configurable(db):
    call_command("semer", mot_de_passe="autre-chose", **FORCER)
    assert _compte("dg").check_password("autre-chose")


def test_chaque_agent_porte_un_perimetre(jeu_dessai):
    """Un agent sans perimetre ne voit rien. Un jeu d'essai qui l'oublierait
    produirait dix comptes muets, qu'on prendrait pour un bug ailleurs.

    Les comptes du portail sont exclus : ils n'ont pas de perimetre, et c'est
    voulu (ADR 013). Le test suivant impose l'inverse pour eux.
    """
    usagers = set(comptes_du_portail().values_list("pk", flat=True))
    for utilisateur in Utilisateur.objects.exclude(pk__in=usagers):
        assert perimetre_en_vigueur(utilisateur) is not None, utilisateur.identifiant_annuaire


def test_un_compte_du_portail_n_a_ni_perimetre_ni_rattachement(jeu_dessai):
    """
    L'inverse du test precedent, et il n'est pas cosmetique : donner une portee
    `structure` a un compte usager lui ouvrirait les demandes de tous les autres
    usagers de la meme direction. L'absence de perimetre est la protection
    (ADR 013).
    """
    usagers = list(comptes_du_portail())
    assert {u.identifiant_annuaire for u in usagers} == {"usager.sotrapal", "usager.camtrans"}
    for usager in usagers:
        assert perimetre_en_vigueur(usager) is None, usager.identifiant_annuaire
        assert usager.structure_id is None
        assert usager.poste_id is None


def test_un_point_focal_ne_voit_que_sa_structure(jeu_dessai):
    visibles = {s.code for s in structures_visibles(_compte("focal.dsi"))}
    assert visibles == {"DSI"}


def test_deux_points_focaux_ne_voient_pas_la_meme_chose(jeu_dessai):
    """Le cloisonnement entre structures : c'est la regle de visibilite, et
    c'est ce qu'aucun filtre d'affichage ne remplace."""
    dsi = {s.code for s in structures_visibles(_compte("focal.dsi"))}
    daf = {s.code for s in structures_visibles(_compte("focal.daf"))}
    assert dsi.isdisjoint(daf)


def test_un_directeur_voit_ses_services(jeu_dessai):
    """La portee sous_arbre descend par requete recursive : sans ces deux
    services, l'organigramme d'essai ne l'eprouverait pas."""
    visibles = {s.code for s in structures_visibles(_compte("dir.dsi"))}
    assert visibles == {"DSI", "DSI-ET", "DSI-IN"}


def test_la_portee_toutes_ne_borne_rien(jeu_dessai):
    """`None` signifie « aucune restriction », et non « aucune structure ».
    Confondre les deux fermerait l'acces aux seuls profils qui doivent tout voir."""
    assert structures_visibles(_compte("dsr")) is None


def test_les_permissions_activites_sont_reparties(jeu_dessai):
    """Qui declare, qui arbitre, qui relance, qui valide : quatre comptes
    distincts. Si l'un d'eux cumulait tout, les tests du pilier activites
    passeraient sans rien prouver."""
    assert "ACT_SAI" in permissions_de(_compte("focal.dsi"))
    assert "ACT_SAI" not in permissions_de(_compte("dcg"))
    assert "ACT_VAL" in permissions_de(_compte("dcg"))
    assert "ACT_VAL" not in permissions_de(_compte("focal.dsi"))
    assert "DEC" in permissions_de(_compte("dg"))
    assert "REL" in permissions_de(_compte("att.dsr"))

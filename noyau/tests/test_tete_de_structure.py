"""
La tete de structure — ce qui la designe, et qui elle rend responsable.

Le jeu d'essai (`manage.py semer`) convient a ces tests pour deux raisons
precises, et ce sont les seules qui comptent ici :

 * **la DSI porte deux services** (DSI-ET, DSI-IN). C'est le seul endroit de
   l'organigramme d'essai ou une tete se distingue d'une sous-structure : sans
   cet etage supplementaire, `tete_de` renverrait la structure elle-meme
   partout et un module qui ne remonterait jamais l'arbre passerait les tests ;

 * **le SCC est au rang « Service » et pend directement de la Direction
   generale.** Il eprouve que le rang ne decide pas de la tete — au Port, le
   Cabinet est au rang `SERV` et les representations au rang `DIR_ADJ`. Un
   module qui aurait devine la tete par `niveau_hierarchique.rang` classerait
   le Service du Courrier Central sous une direction qui ne le dirige pas.

La dissymetrie des comptes fait le reste : `dg` et `dsr` sont en portee
`toutes`, `dir.dsi` en `sous_arbre` sans permission de consolidation, et
`dir.daf` en `sous_arbre` **avec** `VUE_CODIR`. C'est ce dernier qui distingue
les deux chemins de `consolide()`.
"""

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur
from noyau.organisation.modeles import NiveauHierarchique, Structure
from noyau.organisation.tete import (
    champ_regroupement,
    consolide,
    responsable_a_relancer,
    responsable_de,
    tete_de,
)


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


def structure(code: str) -> Structure:
    return Structure.objects.get(code=code, valide_au__isnull=True)


def test_une_tete_est_sa_propre_tete(jeu):
    assert tete_de(structure("DSI")) == structure("DSI")


def test_une_sous_structure_remonte_a_sa_tete(jeu):
    assert tete_de(structure("DSI-ET")) == structure("DSI")


def test_le_rang_ne_decide_pas_de_la_tete(jeu):
    # Le Service du Courrier Central est au rang « Service » et pend
    # directement de la Direction generale : il est une tete.
    assert tete_de(structure("SCC")) == structure("SCC")


def test_la_racine_n_a_pas_de_tete(jeu):
    assert tete_de(structure("DG")) is None


def test_un_organe_au_dessus_de_la_dg_ne_deplace_pas_les_tetes(jeu):
    """
    Le Conseil d'administration coiffe la Direction generale sans rien
    consolider.

    Le jeu d'essai s'arrete a la Direction generale, alors que la planche du
    Port inscrit le Conseil d'administration au-dessus d'elle. La premiere
    version de `structure_tete_de` lisait « enfant direct de la racine » : sur
    l'organigramme reel, elle rendait la Direction generale pour tete de la
    Direction generale — les soixante-seize structures du Port sous une seule
    ligne. Ce test reproduit la planche, et non le jeu d'essai.
    """
    # `structure` est historisee : le socle refuse toute ecriture sans acteur
    # identifie. Une reorganisation passe par `acteur()` en production
    # (`organisation/services.py`) ; le test emprunte le meme chemin plutot
    # que de contourner la garde.
    with acteur(compte("dg")):
        conseil = Structure.objects.create(
            code="CA",
            libelle="Conseil d'administration",
            niveau_hierarchique=NiveauHierarchique.objects.get(code="DIR"),
            nature="Organe",
            valide_du="2026-01-01",
        )
        dg = structure("DG")
        dg.parent = conseil
        dg.save(update_fields=["parent"])

    assert tete_de(structure("DSI")) == structure("DSI")
    assert tete_de(structure("DSI-ET")) == structure("DSI")
    assert tete_de(structure("DG")) is None
    # Un organe deliberant n'est pas dans la ligne hierarchique : il n'a pas
    # de tete, et n'en est pas une.
    assert tete_de(structure("CA")) is None


def test_le_declencheur_recalcule_le_sous_arbre(jeu):
    """Deplacer DSI sous DAF fait passer DSI-ET sous la tete DAF."""
    with acteur(compte("dg")):
        dsi = structure("DSI")
        dsi.parent = structure("DAF")
        dsi.save(update_fields=["parent"])

    assert tete_de(structure("DSI")) == structure("DAF")
    assert tete_de(structure("DSI-ET")) == structure("DAF")


def test_le_responsable_est_l_occupant_du_poste_de_tete(jeu):
    assert responsable_de(structure("DSI")) == compte("dir.dsi")


def test_le_responsable_a_relancer_remonte_a_la_tete(jeu):
    # Une activite de DSI-ET se relance chez la directrice de la DSI.
    assert responsable_a_relancer(structure("DSI-ET")) == compte("dir.dsi")


def test_le_responsable_a_relancer_remonte_quand_le_poste_est_vacant(jeu):
    """DSI sans occupant : la relance monte au Directeur general."""
    dir_dsi = compte("dir.dsi")
    dir_dsi.poste = None
    dir_dsi.save(update_fields=["poste"])

    assert responsable_a_relancer(structure("DSI-ET")) == compte("dg")


def test_la_dsr_et_le_dg_consolident(jeu):
    assert consolide(compte("dsr")) is True
    assert consolide(compte("dg")) is True


def test_un_directeur_ne_consolide_pas(jeu):
    assert consolide(compte("dir.dsi")) is False


def test_un_membre_du_codir_consolide_par_sa_permission(jeu):
    """
    `dir.daf` est en portee `sous_arbre` sur la DAF — il reste directeur — mais
    le CODIR est le conseil des directeurs : il siege pour comparer les
    directions entre elles. C'est `VUE_CODIR` qui le dit, pas le perimetre.
    """
    assert consolide(compte("dir.daf")) is True


def test_le_champ_de_regroupement_suit(jeu):
    assert champ_regroupement(compte("dg")) == "structure__tete"
    assert champ_regroupement(compte("dir.dsi")) == "structure"
    assert champ_regroupement(compte("dg"), prefixe="plan__structure") == "plan__structure__tete"

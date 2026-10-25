"""
Le tableau de bord d'administration — `/api/administration/tableau-de-bord`.

Ce que ces tests protegent, dans l'ordre :

 1. **La garde, et le filtre derriere la garde.** La route accepte quatre
    permissions ; c'est le contenu qui distingue les postes. Un administrateur
    de l'organigramme qui recevrait les acces signales aurait franchi une
    frontiere sans qu'aucune erreur ne le signale.
 2. **Ce qui est compte.** Des evenements, pas des lignes en base. Un total qui
    grossirait avec un import SQL ne repondrait plus a la question posee.
 3. **Les anomalies menent quelque part.** Une anomalie sans chemin de
    correction fait perdre le temps qu'elle croit faire gagner.
"""

from datetime import date

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
BORD = "/api/administration/tableau-de-bord"


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
def faits(connecte):
    """
    Fait ecrire quelque chose a l'application.

    Le semis cree ses comptes par l'ORM, sans passer par les services : le
    journal est donc vide apres le semis, et un tableau de bord de la
    volumetrie n'a rien a montrer. Voir `docs/pieges.md`.
    """
    from noyau.habilitation.modeles import Profil

    cible = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    profil = Profil.objects.get(code="POINT_FOCAL")

    connecte("admin").post(
        f"/api/habilitations/utilisateurs/{cible.pk}/profils",
        {"profilId": profil.pk},
        content_type="application/json",
    )
    return cible


@pytest.fixture
def auditeur(connecte):
    """Le jeu d'essai ne porte pas de compte d'audit : `AUDIT` est ajoute au
    profil de l'administrateur pour la duree du test."""
    from noyau.habilitation.modeles import Permission, Profil, ProfilPermission

    ProfilPermission.objects.get_or_create(
        profil=Profil.objects.get(code="ADMIN"),
        permission=Permission.objects.get(code="AUDIT"),
    )
    return connecte("admin")


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_l_accueil_est_ferme(client, jeu):
    assert client.get(BORD).status_code == 401


def test_un_agent_sans_permission_d_administration_n_entre_pas(connecte):
    """401 et non 403 — c'est ce que rend `ExigePermission` sur tout le depot."""
    assert connecte("agent.dsi").get(BORD).status_code == 401


def test_le_directeur_general_n_est_pas_administrateur(connecte):
    """
    Il porte toutes les permissions metier et aucune permission
    d'administration. Ce test tombe le jour ou un profil ramasse
    l'administration par commodite.
    """
    assert connecte("dg").get(BORD).status_code == 401


def test_l_administrateur_fonctionnel_entre(connecte):
    assert connecte("admin").get(BORD).status_code == 200


# =====================================================================
#  Le filtre derriere la garde
# =====================================================================


def test_sans_AUDIT_les_journaux_ne_sortent_pas(connecte):
    """
    C'est le fond du module : la route est large, le contenu ne l'est pas.
    Le front cache ces blocs ; sans ce filtre, la reponse les porterait quand
    meme — l'oubli qui ne produit aucune erreur.
    """
    corps = connecte("admin").get(BORD).json()

    assert corps["activite"] == []
    assert corps["parType"] == []
    assert corps["operationsTotal"] == 0
    assert corps["operationsVariation"] == "—"
    assert corps["acces"]["dernieres"] == []


def test_avec_AUDIT_la_volumetrie_sort(auditeur, faits):
    corps = auditeur.get(BORD).json()

    assert corps["operationsTotal"] >= 1
    assert corps["activite"]
    assert corps["parType"]


def test_le_bloc_refuse_reste_vide_meme_avec_AUDIT(auditeur):
    """
    Un acces refuse ne laisse pas de trace : la garde rend 401 avant la vue, et
    `HorsPerimetre` rend 404 (D5) sans rien inscrire. Le compteur est cable et
    vaut zero ; ce test dit que c'est une decision, pas un oubli.
    """
    assert auditeur.get(BORD).json()["acces"]["refuses"] == 0


# =====================================================================
#  Ce qui est compte
# =====================================================================


def test_la_courbe_ne_saute_pas_les_periodes_creuses(auditeur, faits):
    """
    Une courbe qui omet les jours sans operation se lit comme une activite
    continue — l'inverse de ce que l'administrateur doit voir.
    """
    points = auditeur.get(BORD).json()["activite"]

    assert len(points) >= 30
    assert any(p["operations"] == 0 for p in points)


def test_le_pas_de_la_courbe_suit_la_periode(auditeur, faits):
    """Trois cent soixante-cinq barres ne se lisent pas ; douze si."""
    annee = auditeur.get(f"{BORD}?periode=annee").json()["activite"]
    trente = auditeur.get(f"{BORD}?periode=30j").json()["activite"]

    assert len(annee) <= 13
    assert len(trente) > len(annee)


def test_une_periode_inconnue_retombe_sur_trente_jours(auditeur, faits):
    """L'accueil ne refuse pas de s'afficher pour un parametre de confort."""
    reponse = auditeur.get(f"{BORD}?periode=fantaisie")

    assert reponse.status_code == 200
    assert len(reponse.json()["activite"]) == len(auditeur.get(BORD).json()["activite"])


def test_toutes_les_familles_sortent_meme_a_zero(auditeur, faits):
    """
    Une famille absente se lirait comme une famille qui n'existe pas, alors
    qu'elle n'a servi a personne sur la periode — ce qui est l'information.
    """
    familles = {ligne["libelle"] for ligne in auditeur.get(BORD).json()["parType"]}

    assert "Habilitation" in familles
    assert "Signature" in familles


def test_la_variation_ne_divise_pas_par_zero(auditeur, faits):
    """Un pourcentage calcule sur une periode precedente vide ne veut rien
    dire ; l'application est encore assez jeune pour que le cas soit le plus
    frequent."""
    assert (
        auditeur.get(BORD).json()["operationsVariation"] in {"Nouveau", "—"}
        or "%" in auditeur.get(BORD).json()["operationsVariation"]
    )


# =====================================================================
#  L'adoption
# =====================================================================


def test_l_adoption_se_compte_par_structure_de_premier_niveau(connecte):
    """
    Une ligne par service donnerait cinquante lignes ou personne ne verrait
    qu'une direction entiere est absente.
    """
    from noyau.organisation.modeles import Structure

    lignes = connecte("admin").get(BORD).json()["adoption"]
    racines = Structure.objects.en_vigueur().filter(parent__isnull=True).count()

    assert len(lignes) == racines


def test_une_structure_sans_operation_le_dit_explicitement(connecte):
    """`null` et non zero : l'ecran en fait « Aucune activité », en rouge."""
    lignes = connecte("admin").get(BORD).json()["adoption"]

    assert any(ligne["derniereActivite"] is None for ligne in lignes)
    assert connecte("admin").get(BORD).json()["structuresInactives"] > 0


def test_un_compte_actif_sans_profil_n_est_pas_compte_comme_habilite(connecte):
    """
    L'ecart entre « actifs » et « habilites » est ce que l'administrateur doit
    voir : un compte actif sans profil peut se connecter et ne peut rien faire.
    """
    lignes = connecte("admin").get(BORD).json()["adoption"]

    assert all(ligne["habilites"] <= ligne["actifs"] for ligne in lignes)


# =====================================================================
#  Les anomalies
# =====================================================================


def test_un_referentiel_sain_ne_signale_rien(connecte):
    """
    Le jeu d'essai est complet : chaque compte porte un profil, un perimetre et
    une structure. Une liste vide est donc l'etat attendu — un tableau de bord
    qui trouverait toujours quelque chose a signaler cesserait vite d'etre lu.
    """
    assert connecte("admin").get(BORD).json()["anomalies"] == []


def test_chaque_anomalie_mene_a_l_ecran_qui_la_corrige(connecte):
    """Une anomalie sans chemin de correction fait perdre le temps qu'elle
    croit faire gagner."""
    Utilisateur.objects.create(
        identifiant_annuaire="orphelin",
        nom="Sans",
        prenom="Profil",
        courriel="orphelin@pad.cm",
        actif=True,
    )

    anomalies = connecte("admin").get(BORD).json()["anomalies"]

    assert anomalies
    assert all(a["chemin"].startswith("/") for a in anomalies)
    assert all(a["ton"] in {"alerte", "danger"} for a in anomalies)


def test_une_structure_rattachee_a_une_structure_close_est_signalee(connecte):
    """
    Promis par la docstring de `organisation.lecture.referentiel_structures` :
    le referentiel rend `parentId` brut, sans verifier que le parent est en
    vigueur. C'est ici que l'incoherence est comptee.
    """
    from noyau.journal.contexte import acteur as contexte_acteur
    from noyau.organisation.modeles import Structure

    libelle = "Structures rattachées à une structure close"
    avant = {a["libelle"]: a["nombre"] for a in connecte("admin").get(BORD).json()["anomalies"]}
    assert libelle not in avant

    fille = Structure.objects.en_vigueur().filter(parent__isnull=False).first()
    assert fille is not None
    parent = fille.parent
    with contexte_acteur(Utilisateur.objects.get(identifiant_annuaire="dsr")):
        parent.valide_au = date.today()
        parent.save(update_fields=["valide_au"])

    apres = {a["libelle"]: a["nombre"] for a in connecte("admin").get(BORD).json()["anomalies"]}
    assert apres[libelle] >= 1


def test_un_compte_actif_sans_profil_est_une_anomalie_de_danger(connecte):
    """
    Il peut se connecter et ne peut rien faire — c'est un compte ouvert a
    moitie, pas un compte en attente.

    Le profil retire est celui d'un autre agent, jamais celui de l'appelant :
    lui retirer le sien le mettrait dehors, et le test mesurerait un 401.
    """
    from noyau.habilitation.modeles import UtilisateurProfil

    cible = Utilisateur.objects.get(identifiant_annuaire="agent.dsi")
    UtilisateurProfil.objects.filter(utilisateur=cible, retire_le__isnull=True).delete()

    anomalies = {a["libelle"]: a for a in connecte("admin").get(BORD).json()["anomalies"]}
    assert anomalies["Comptes actifs sans profil"]["nombre"] == 1
    assert anomalies["Comptes actifs sans profil"]["ton"] == "danger"


def test_les_anomalies_de_l_organigramme_ne_sortent_pas_sans_ADM_ORG(connecte):
    """
    `admin` porte les deux permissions dans le jeu d'essai ; le test verifie la
    reciproque en la retirant, faute de quoi le filtre par bloc ne serait
    jamais eprouve.
    """
    from noyau.habilitation.modeles import Permission, Profil, ProfilPermission

    ProfilPermission.objects.filter(
        profil=Profil.objects.get(code="ADMIN"),
        permission=Permission.objects.get(code="ADM_ORG"),
    ).delete()

    corps = connecte("admin").get(BORD).json()

    assert corps["adoption"] == []
    assert all(a["chemin"] != "/organisation" for a in corps["anomalies"])


# =====================================================================
#  Les indicateurs de tete
# =====================================================================


def test_les_indicateurs_absents_ne_sont_pas_affiches_a_zero(connecte):
    """Un indicateur rendu a « — » se lit comme une valeur nulle, ce qui est
    plus faux que son absence."""
    libelles = {i["libelle"] for i in connecte("admin").get(BORD).json()["indicateurs"]}

    assert "Accès à examiner" not in libelles
    assert "Comptes actifs" in libelles


def test_l_indicateur_d_acces_passe_au_vert_quand_il_n_y_a_rien(auditeur):
    indicateur = next(
        i for i in auditeur.get(BORD).json()["indicateurs"] if i["libelle"] == "Accès à examiner"
    )

    assert indicateur["valeur"] == "0"
    assert indicateur["ton"] == "succes"

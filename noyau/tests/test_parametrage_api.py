"""
Le parametrage metier — `/api/parametrage`.

Ce que ces tests protegent :

 1. **La garde.** `ADM_PAR`, et rien d'autre. Regler un delai d'escalade change
    le comportement de toute l'institution.
 2. **L'absence d'ecriture sur les huit referentiels de circuit.** L'ecran porte
    des boutons de creation qui ne sont branches sur rien. Ce test tombe le jour
    ou une route d'ecriture apparait sans que le contrat front ne suive. Le
    neuvieme onglet fait exception, et c'est l'objet du point suivant.
 3. **L'arbitrage d'une hypothese** — zone H. Une regle ne passe pas au rang
    d'acte sans citer sa source, et un acte ne redevient jamais une hypothese.
    C'est la consigne permanente du projet, et le seul endroit ou le code la
    fait respecter.
 4. **Les phrases construites.** `sappliqueA` et `condition` sont fabriquees au
    serveur depuis les colonnes. C'est la partie qui casse en silence : une
    condition mal formee reste une chaine de caracteres valide.
"""

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.parametrage.modeles import Circuit, CircuitEtape, CircuitVersion, Correspondant, Nature

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
PARAMETRAGE = "/api/parametrage"


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


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_le_parametrage_est_ferme(client, jeu):
    assert client.get(PARAMETRAGE).status_code == 401


def test_une_session_sans_ADM_PAR_ne_suffit_pas(connecte):
    assert connecte("agent.dsi").get(PARAMETRAGE).status_code == 401


def test_le_directeur_general_ne_regle_pas_les_circuits(connecte):
    """Il porte toutes les permissions metier et aucune d'administration."""
    assert connecte("dg").get(PARAMETRAGE).status_code == 401


def test_l_administrateur_fonctionnel_lit_le_parametrage(connecte):
    assert connecte("admin").get(PARAMETRAGE).status_code == 200


@pytest.mark.parametrize("verbe", ["post", "patch", "delete"])
def test_aucune_ecriture_sur_les_referentiels_de_circuit(connecte, verbe):
    """
    L'ecran porte des boutons de creation qui ne sont branches sur rien : les
    ecrire avant que le pilier courrier ne consomme ces referentiels aurait
    produit des circuits que rien n'emprunte.

    Les regles de gestion, elles, sont ecrivables — sur `/regles-metier/{cle}`,
    pas sur la racine.
    """
    reponse = getattr(connecte("admin"), verbe)(PARAMETRAGE, {}, content_type="application/json")
    assert reponse.status_code == 405


# =====================================================================
#  Les neuf onglets
# =====================================================================


def test_les_neuf_onglets_sont_servis_en_un_appel(connecte):
    """Neuf appels auraient fait clignoter l'ecran a chaque onglet pour
    economiser quelques kilo-octets."""
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert set(corps) == {
        "circuits",
        "etapes",
        "regles",
        "mentions",
        "correspondants",
        "engagements",
        "classement",
        "seuils",
        "reglesMetier",
    }


def test_le_socle_livre_deux_circuits_preconfigures(connecte):
    """« L'application fonctionne dès l'installation » — commentaire du socle."""
    circuits = {c["libelle"] for c in connecte("admin").get(PARAMETRAGE).json()["circuits"]}

    assert circuits == {"Circuit ordinaire", "Circuit confidentiel"}


def test_les_natures_du_socle_deviennent_les_engagements(connecte):
    """
    Il n'y a pas de referentiel d'engagement separe : le delai vit sur la
    nature, ou le socle l'a mis. En creer un second aurait garanti qu'un jour
    les deux se contredisent.
    """
    engagements = {
        e["libelle"]: e for e in connecte("admin").get(PARAMETRAGE).json()["engagements"]
    }

    assert engagements["Rapport"]["delaiCible"] == 30
    assert engagements["Invitation"]["delaiCible"] == 5


def test_un_delai_sans_prealerte_sort_a_zero_et_non_a_null(connecte):
    """Le front affiche le nombre tel quel ; `null` y produirait « null jours »."""
    engagements = connecte("admin").get(PARAMETRAGE).json()["engagements"]

    assert all(isinstance(e["premiereAlerte"], int) for e in engagements)


# =====================================================================
#  Les phrases construites
# =====================================================================


def test_la_regle_de_repli_se_nomme_comme_telle(connecte):
    """
    Une regle sans aucun critere s'applique a ce que rien d'autre n'a pris. Un
    tableau ou la derniere ligne aurait une condition vide se lirait comme une
    regle inachevee, alors que c'est le filet.
    """
    from noyau.parametrage.modeles import CircuitRegle

    CircuitRegle.objects.create(
        circuit=Circuit.objects.get(code="ORDINAIRE"), priorite=999, actif=True
    )

    regles = connecte("admin").get(PARAMETRAGE).json()["regles"]
    repli = [r for r in regles if r["repli"]]

    assert len(repli) == 1
    assert repli[0]["condition"] == "Tout courrier (règle de repli)"


def test_les_regles_sortent_dans_l_ordre_ou_elles_sont_evaluees(connecte):
    """
    La premiere qui correspond gagne. Trier autrement — par circuit, par nom —
    donnerait une lecture fausse de ce qui va se passer.
    """
    regles = connecte("admin").get(PARAMETRAGE).json()["regles"]

    assert [r["ordre"] for r in regles] == list(range(1, len(regles) + 1))
    # Le socle donne la priorite 10 au confidentiel et 100 a l'ordinaire.
    assert regles[0]["circuit"] == "Circuit confidentiel"


def test_la_condition_se_lit_en_francais(connecte):
    """`escalade_vers_poste_id` et quatre colonnes nulles ne se lisent pas."""
    conditions = {r["condition"] for r in connecte("admin").get(PARAMETRAGE).json()["regles"]}

    assert "Tout confidentiel" in conditions
    assert "Tout non confidentiel" in conditions


def test_le_circuit_dit_a_quoi_il_s_applique(connecte):
    """
    La phrase est construite depuis les regles, jamais saisie : un libelle a la
    main aurait cesse d'etre juste des la premiere regle ajoutee.
    """
    circuits = {c["libelle"]: c for c in connecte("admin").get(PARAMETRAGE).json()["circuits"]}

    assert circuits["Circuit confidentiel"]["sappliqueA"] == "Tout confidentiel"


# =====================================================================
#  Les etapes
# =====================================================================


def test_le_circuit_du_socle_n_a_pas_encore_d_etapes(connecte):
    """
    Le socle cree deux circuits et aucune etape : le trajet reel du courrier
    n'a pas ete communique. Un trajet invente aurait ete applique tel quel.
    Voir A24.
    """
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert corps["etapes"] == []
    assert all(c["nombreEtapes"] == 0 for c in corps["circuits"])


def test_une_etape_sans_escalade_ni_delai_ne_declenche_rien(connecte):
    version = CircuitVersion.objects.get(circuit__code="ORDINAIRE")
    CircuitEtape.objects.create(circuit_version=version, rang=1, libelle="Enregistrement")

    etape = connecte("admin").get(PARAMETRAGE).json()["etapes"][0]

    assert etape["escalade"] == "Aucune"
    assert etape["acteur"] == "Non défini"


def test_un_delai_sans_poste_d_escalade_produit_une_relance(connecte):
    """Quelqu'un est prevenu, personne n'est dessaisi."""
    version = CircuitVersion.objects.get(circuit__code="ORDINAIRE")
    CircuitEtape.objects.create(circuit_version=version, rang=1, libelle="Cotation", delai_jours=2)

    assert (
        connecte("admin").get(PARAMETRAGE).json()["etapes"][0]["escalade"] == "Relance automatique"
    )


def test_le_poste_d_escalade_l_emporte_sur_le_delai(connecte):
    """C'est le cas le plus fort : l'affaire change de main."""
    from noyau.organisation.modeles import Poste

    version = CircuitVersion.objects.get(circuit__code="ORDINAIRE")
    poste = Poste.objects.en_vigueur().first()
    CircuitEtape.objects.create(
        circuit_version=version,
        rang=1,
        libelle="Traitement",
        delai_jours=5,
        escalade_vers_poste=poste,
        poste=poste,
    )

    etape = connecte("admin").get(PARAMETRAGE).json()["etapes"][0]

    assert etape["escalade"] == "Escalade au supérieur"
    assert etape["acteur"] == poste.libelle


def test_l_etape_est_rattachee_au_circuit_et_non_a_sa_version(connecte):
    """
    Le front regroupe par `circuitId`. Lui rendre l'identifiant de version
    aurait casse le regroupement au premier circuit republie.
    """
    version = CircuitVersion.objects.get(circuit__code="ORDINAIRE")
    CircuitEtape.objects.create(circuit_version=version, rang=1, libelle="Enregistrement")

    etape = connecte("admin").get(PARAMETRAGE).json()["etapes"][0]

    assert etape["circuitId"] == version.circuit_id
    assert etape["circuitId"] != version.pk or version.circuit_id == version.pk


# =====================================================================
#  Les correspondants
# =====================================================================


def test_deux_correspondants_de_meme_nom_normalise_sont_signales(connecte):
    """
    « Direction Générale des Impôts » et « DIRECTION GENERALE DES IMPOTS » sont
    le meme correspondant saisi deux fois. Sans normalisation, aucun doublon ne
    serait jamais detecte.
    """
    Correspondant.objects.create(
        type="administration", raison_sociale="Direction Générale des Impôts"
    )
    Correspondant.objects.create(
        type="administration", raison_sociale="DIRECTION GENERALE DES IMPOTS"
    )

    correspondants = connecte("admin").get(PARAMETRAGE).json()["correspondants"]

    assert len(correspondants) == 2
    assert all(c["doublonPresume"] for c in correspondants)


def test_un_correspondant_unique_n_est_pas_signale(connecte):
    """Le signalement est un soupcon, jamais une fusion."""
    Correspondant.objects.create(type="externe", nom="Mbarga", prenom="Paul")

    correspondant = connecte("admin").get(PARAMETRAGE).json()["correspondants"][0]

    assert correspondant["doublonPresume"] is False
    assert correspondant["libelle"] == "Mbarga Paul"
    assert correspondant["ville"] == "—"


# =====================================================================
#  Ce qui compte des courriers
# =====================================================================


def test_les_compteurs_de_courrier_valent_zero(connecte):
    """
    Le pilier courrier n'existe pas. Zero est exact ; une valeur plausible
    serait la seule facon de rendre l'ecran faux.
    """
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert all(c["usage"] == 0 for c in corps["circuits"])
    assert all(r["declenchements"] == 0 for r in corps["regles"])
    assert all(e["respect90j"] == 0 for e in corps["engagements"])


def test_le_plan_de_classement_et_les_seuils_sont_vides(connecte):
    """
    Ni l'un ni l'autre ne figurait au socle, et aucun document de cadrage ne
    les fournit. Un plan de classement invente serait recopie tel quel par la
    premiere direction qui l'ouvrirait. Voir A24.
    """
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert corps["classement"] == []
    assert corps["seuils"] == []


def test_une_nature_close_ne_figure_plus_aux_engagements(connecte):
    """Rien n'est supprime : une nature retiree du formulaire reste lisible sur
    les courriers de l'an dernier, mais ne s'offre plus au parametrage."""
    from django.utils import timezone

    nature = Nature.objects.get(code="AUTRE")
    nature.invalide_le = timezone.now()
    nature.save(update_fields=["invalide_le"])

    libelles = {e["libelle"] for e in connecte("admin").get(PARAMETRAGE).json()["engagements"]}
    assert "Autre" not in libelles


# =====================================================================
#  Le neuvieme onglet — les regles de gestion (zone H)
# =====================================================================

#: Une hypothese entiere, semee par la migration `0008`. Trente jours annonces
#: a l'usager, que personne n'a arbitres.
HYPOTHESE = "portail.delai_reponse_jours"

#: Un acte entier, seme par la meme migration. Quatre heures de reprise,
#: RNF-DISP-02. Il sert a verifier qu'un arbitrage rendu ne se refait pas.
ACTE = "supervision.reprise_cible_minutes"


def _regle(corps: dict, cle: str) -> dict:
    return next(r for r in corps["reglesMetier"] if r["cle"] == cle)


def test_les_regles_de_gestion_sont_servies_avec_les_referentiels(connecte):
    """
    Neuvieme onglet, meme appel. Un appel separe aurait fait clignoter l'ecran
    au changement d'onglet — c'est la raison qui vaut pour les huit autres.
    """
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert corps["reglesMetier"], "la table `parametre` est semee par les migrations"
    assert _regle(corps, HYPOTHESE)["valeur"] == "30"


def test_les_hypotheses_sont_servies_en_tete(connecte):
    """
    Une hypothese est une question sans reponse. Noyee au milieu de trente
    regles actees, elle cesse d'etre visible, et l'arbitrage n'arrive jamais.
    """
    statuts = [r["statut"] for r in connecte("admin").get(PARAMETRAGE).json()["reglesMetier"]]

    # `acte` precede `hypothese` dans l'alphabet, donc le tri croissant les
    # aurait mises en queue. L'ordre attendu est l'inverse.
    assert statuts.index("hypothese") < statuts.index("acte")


def test_une_hypothese_se_signale_autrement_que_par_une_chaine(connecte):
    """`estHypothese` double `statut` : un test sur la valeur d'une chaine se
    trompe en silence, un booleen non."""
    corps = connecte("admin").get(PARAMETRAGE).json()

    assert _regle(corps, HYPOTHESE)["estHypothese"] is True
    assert _regle(corps, ACTE)["estHypothese"] is False


def test_une_hypothese_porte_le_nom_de_qui_doit_trancher(connecte):
    """Sans ce nom, la question ouverte n'a pas de destinataire et reste
    ouverte."""
    regle = _regle(connecte("admin").get(PARAMETRAGE).json(), HYPOTHESE)

    assert regle["aTrancherPar"]
    assert regle["source"] is None


# ---------------------------------------------------------------------
#  La garde
# ---------------------------------------------------------------------


def test_sans_session_une_regle_ne_se_modifie_pas(client, jeu):
    reponse = client.patch(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}",
        {"valeur": "45"},
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_un_agent_sans_ADM_PAR_ne_tranche_pas_une_regle(connecte):
    """Trancher une hypothese change le comportement de toute l'institution."""
    reponse = connecte("dg").post(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}/arbitrage",
        {"source": "Note DG"},
        content_type="application/json",
    )
    assert reponse.status_code == 401


def test_une_regle_inconnue_repond_404(connecte):
    reponse = connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/portail.regle.inventee",
        {"valeur": "1"},
        content_type="application/json",
    )
    assert reponse.status_code == 404


# ---------------------------------------------------------------------
#  Modifier une valeur
# ---------------------------------------------------------------------


def test_une_hypothese_se_corrige_sans_source(connecte):
    """C'est une invention de la conception : l'ajuster ne fait que remplacer
    une invention par une autre, ce que le statut annonce deja."""
    reponse = connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}",
        {"valeur": "45"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["valeur"] == "45"
    # Corriger n'est pas trancher : le statut n'a pas bouge.
    assert corps["statut"] == "hypothese"


def test_modifier_un_acte_sans_source_est_refuse(connecte):
    """
    Changer un seuil arbitre sans dire d'ou vient le nouveau chiffre le ramene
    au rang d'invention, en gardant l'etiquette qui dit le contraire.
    """
    reponse = connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{ACTE}",
        {"valeur": "120"},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "source_exigee"


def test_modifier_un_acte_en_citant_la_decision_est_accepte(connecte):
    reponse = connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{ACTE}",
        {"valeur": "120", "source": "Avenant n°2 au contrat d'infogerance, 14 août 2026"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["valeur"] == "120"
    assert "Avenant" in corps["source"]


@pytest.mark.parametrize("saisie", ["quarante", "4O", "", "  "])
def test_une_valeur_qui_ne_se_relit_pas_est_refusee(connecte, saisie):
    """
    Sans ce controle, la faute de frappe passe a l'ecriture et **casse a la
    lecture** : `int('4O')` leve dans le calcul d'un delai, a des kilometres de
    la saisie qui l'a causee.
    """
    reponse = connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}",
        {"valeur": saisie},
        content_type="application/json",
    )

    assert reponse.status_code == 409


def test_la_modification_est_inscrite_au_journal(connecte):
    from noyau.journal.modeles import Evenement

    connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}",
        {"valeur": "45"},
        content_type="application/json",
    )

    evenement = Evenement.objects.filter(type_evenement="regle_modifiee").latest("id")
    assert evenement.donnees["avant"] == "30"
    assert evenement.donnees["apres"] == "45"


# ---------------------------------------------------------------------
#  Trancher
# ---------------------------------------------------------------------


def test_trancher_une_hypothese_la_fait_passer_au_rang_d_acte(connecte):
    """C'est la sortie de docs/questions-ouvertes.md : chaque appel retire une
    question de la liste."""
    reponse = connecte("admin").post(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}/arbitrage",
        {"source": "Note DG n°412 du 3 septembre 2026", "valeur": "21"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "acte"
    assert corps["estHypothese"] is False
    assert corps["valeur"] == "21"
    # Plus personne n'a a trancher : garder le nom ferait reclamer a l'ecran un
    # arbitrage deja rendu.
    assert corps["aTrancherPar"] is None


def test_trancher_sans_changer_la_valeur_est_permis(connecte):
    """Le metier confirme souvent l'hypothese telle quelle ; l'obliger a
    retaper le chiffre est le meilleur moyen d'en obtenir un faux."""
    reponse = connecte("admin").post(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}/arbitrage",
        {"source": "Reunion DSR du 12 août 2026"},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    assert reponse.json()["valeur"] == "30"
    assert reponse.json()["statut"] == "acte"


@pytest.mark.parametrize("source", ["", "   "])
def test_trancher_sans_source_est_refuse(connecte, source):
    """
    **La regle centrale du projet.** Sans reference documentaire, l'arbitrage
    remplace une invention par une autre en lui donnant l'etiquette d'une
    decision — ce qui est pire que l'invention assumee.
    """
    reponse = connecte("admin").post(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}/arbitrage",
        {"source": source},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "source_exigee"

    # Et rien n'a bouge en base : un refus qui laisserait la valeur ecrite
    # serait pire qu'un refus muet.
    corps = connecte("admin").get(PARAMETRAGE).json()
    assert _regle(corps, HYPOTHESE)["statut"] == "hypothese"


def test_une_regle_deja_actee_ne_se_tranche_pas_deux_fois(connecte):
    """Ce serait reecrire une decision passee en silence, et l'ecran ne
    montrerait plus qu'un arbitrage a eu lieu deux fois."""
    reponse = connecte("admin").post(
        f"{PARAMETRAGE}/regles-metier/{ACTE}/arbitrage",
        {"source": "Note quelconque"},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "regle_deja_actee"


def test_l_arbitrage_est_inscrit_au_journal_avec_sa_source(connecte):
    """
    Le journal est ce qui reste quand la note papier se perd. Sans la source
    inscrite, on saurait qu'une regle a change sans savoir sur quoi.
    """
    from noyau.journal.modeles import Evenement

    connecte("admin").post(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}/arbitrage",
        {"source": "Note DG n°412 du 3 septembre 2026", "valeur": "21"},
        content_type="application/json",
    )

    evenement = Evenement.objects.filter(type_evenement="regle_tranchee").latest("id")
    assert evenement.donnees["source"] == "Note DG n°412 du 3 septembre 2026"
    assert evenement.donnees["avant"] == "30"
    assert evenement.donnees["apres"] == "21"


def test_la_valeur_lue_par_le_code_change_immediatement(connecte):
    """
    **Le piege de la zone H.** `parametres.service.valeur()` met en cache par
    processus. Une ecriture qui ne viderait pas ce cache laisserait le serveur
    appliquer l'ancien seuil jusqu'au redemarrage — et deux serveurs derriere un
    repartiteur appliqueraient deux regles differentes sans que rien ne le dise.
    """
    from noyau.parametres import service

    service.vider_cache()
    assert service.valeur(HYPOTHESE) == 30

    connecte("admin").patch(
        f"{PARAMETRAGE}/regles-metier/{HYPOTHESE}",
        {"valeur": "45"},
        content_type="application/json",
    )

    assert service.valeur(HYPOTHESE) == 45


def test_le_cache_des_parametres_est_borne(connecte):
    """Un appelant inventif ne doit pas faire grossir le cache sans limite."""
    from noyau.parametres import service
    from noyau.parametres.modeles import Parametre

    service.vider_cache()
    for index in range(service.TAILLE_CACHE + 10):
        Parametre.objects.create(
            cle=f"test.cache.{index}",
            libelle=f"Parametre de cache {index}",
            valeur=str(index),
            type_valeur="entier",
            domaine="test",
            statut="hypothese",
            a_trancher_par="tests",
        )
        assert service.valeur(f"test.cache.{index}") == index

    assert len(service._cache) <= service.TAILLE_CACHE

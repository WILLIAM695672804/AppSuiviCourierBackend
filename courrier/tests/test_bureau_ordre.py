"""
Le bureau d'ordre de structure, le cloisonnement et le routage direct.

Ce que ces tests protegent, dans l'ordre d'importance :

 1. **Le cloisonnement.** Comme la visibilite, son echec ne provoque aucun
    plantage : une structure qui lit les instructions internes de sa voisine ne
    casse rien et ne se remarque pas. Chaque regle est eprouvee **dans les deux
    sens** — ce qu'elle ferme, et ce qu'elle laisse ouvert a la DSR, faute de
    quoi un cloisonnement trop zele passerait pour une reussite.
 2. **L'entree est posee par le moteur.** Le declencheur
    `cotation_structure_passage` inscrit le passage a la cotation. Si Python
    s'en melait, une seconde voie d'ecriture — une reprise, un import — laisserait
    des courriers hors de tout registre de bureau d'ordre.
 3. **L'accuse ne se pose qu'une fois.** L'ecart entre l'entree et le tampon est
    la seule mesure du temps mort ; un second accuse la remettrait a zero.
 4. **Le routage direct cote pour de vrai.** La facture doit arriver a la direction financiere par
    une vraie cotation, donc avec son passage et son journal — une voie parallele
    aurait produit des courriers routes qu'aucun registre ne montre.
"""

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from courrier.modeles import PassageStructure
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, MentionType, Nature, RegleRoutage
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
COURRIERS = "/api/courriers"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    vider_cache()
    yield
    vider_cache()


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(compte(identifiant), backend=BACKEND)
        return client

    return _connecter


@pytest.fixture
def sotrapal(jeu) -> Correspondant:
    return Correspondant.objects.create(type="externe", raison_sociale="Sotrapal", ville="Douala")


def _saisie(sotrapal: Correspondant, **remplace) -> dict:
    saisie = {
        "typeSession": "ARRIVE",
        "natureId": Nature.objects.get(code="DEMANDE").pk,
        "correspondantId": sotrapal.pk,
        "objet": "Demande de raccordement électrique du quai 12",
        "nombrePages": 3,
        "delaiJours": 5,
    }
    saisie.update(remplace)
    return saisie


@pytest.fixture
def enregistre(connecte, sotrapal) -> int:
    client = connecte("agent.scc")
    return client.post(COURRIERS, _saisie(sotrapal), content_type="application/json").json()["id"]


def _coter(connecte, courrier_id: int, *sigles: str) -> None:
    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}/{courrier_id}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code=sigle).pk for sigle in sigles],
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content


# =====================================================================
#  L'entree, posee par le moteur
# =====================================================================


def test_la_cotation_fait_entrer_le_courrier_dans_la_structure(connecte, enregistre):
    """
    Le declencheur `cotation_structure_passage` pose le passage, et personne ne
    le saisit.

    C'est ce qui garantit que la duree de detention se mesure a partir de
    l'arrivee reelle. Datee de l'accuse de reception, elle aurait toujours ete
    flatteuse : une structure lente a ouvrir son courrier serait apparue rapide a
    le traiter.
    """
    _coter(connecte, enregistre, "DSI", "DAF")

    passages = PassageStructure.objects.filter(courrier_id=enregistre)
    assert passages.count() == 2
    assert set(passages.values_list("structure__code", flat=True)) == {"DSI", "DAF"}
    # Aucun n'est accuse ni sorti : le registre s'ouvre sur la pile du matin.
    assert all(passage.entre_le is not None for passage in passages)
    assert not any(passage.accuse for passage in passages)
    assert all(passage.ouvert for passage in passages)


def test_une_seconde_cotation_fait_un_second_passage(connecte, enregistre):
    """
    Un courrier renvoye a la meme structure y entre **a nouveau**.

    L'unicite porte sur la ligne de cotation, jamais sur le couple
    (courrier, structure) : la seconde entree est un fait du registre, et
    l'ecraser aurait fait disparaitre un aller-retour entier.
    """
    _coter(connecte, enregistre, "DSI")
    _coter(connecte, enregistre, "DSI")

    assert (
        PassageStructure.objects.filter(courrier_id=enregistre, structure__code="DSI").count() == 2
    )


# =====================================================================
#  L'accuse et la sortie
# =====================================================================


def test_l_accuse_ne_se_pose_qu_une_fois(connecte, enregistre):
    """
    Un second accuse ecraserait l'heure du premier, et le temps mort du bureau
    d'ordre se remettrait a zero a chaque clic.
    """
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)

    focal = connecte("focal.dsi")
    premier = focal.post(f"{COURRIERS}/passages/{passage.pk}/accuse")
    assert premier.status_code == 201, premier.content
    assert premier.json()["accusePar"] == "Yves Manga"
    assert premier.json()["heuresAvantAccuse"] == 0

    second = focal.post(f"{COURRIERS}/passages/{passage.pk}/accuse")
    assert second.status_code == 409, second.content


def test_une_sortie_dit_toujours_par_ou(connecte, enregistre):
    """
    Une sortie sans motif se lirait « le courrier a disparu de nos écrans ».
    Le registre d'un bureau d'ordre existe pour dire par ou les choses partent.
    """
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)
    focal = connecte("focal.dsi")

    refus = focal.post(
        f"{COURRIERS}/passages/{passage.pk}/sortie",
        {"motif": "", "note": None},
        content_type="application/json",
    )
    assert refus.status_code == 409, refus.content

    accepte = focal.post(
        f"{COURRIERS}/passages/{passage.pk}/sortie",
        {"motif": "reponse", "note": "Réponse signée et transmise au central"},
        content_type="application/json",
    )
    assert accepte.status_code == 201, accepte.content
    assert accepte.json()["motifSortie"] == "reponse"
    assert accepte.json()["sortiPar"] == "Yves Manga"


def test_un_motif_de_sortie_invente_ne_passe_pas(connecte, enregistre):
    """
    Le code vient du front ; un code inconnu doit echouer en 409 nomme plutot
    qu'en violation de CHECK, qui remonterait en 500.
    """
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)

    reponse = connecte("focal.dsi").post(
        f"{COURRIERS}/passages/{passage.pk}/sortie",
        {"motif": "egare"},
        content_type="application/json",
    )
    assert reponse.status_code == 409, reponse.content


def test_le_bureau_d_ordre_du_voisin_reste_ferme(connecte, enregistre):
    """
    Le bureau d'ordre d'une direction n'est pas le registre du Port.

    Et l'echec sort en **404**, jamais en 403 : repondre « interdit »
    confirmerait qu'un courrier est bien coté a telle structure, ce qui est deja
    l'information (decision D5).
    """
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)

    etranger = connecte("focal.daf")
    assert etranger.post(f"{COURRIERS}/passages/{passage.pk}/accuse").status_code == 404

    registre = etranger.get(f"{COURRIERS}/bureau-ordre").json()
    assert all(ligne["courrierId"] != enregistre for ligne in registre)


def test_le_registre_range_en_trois_piles(connecte, enregistre):
    """`a_accuser`, `en_cours`, `sortis` — les trois piles d'un bureau d'ordre reel."""
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)
    focal = connecte("focal.dsi")

    a_accuser = focal.get(f"{COURRIERS}/bureau-ordre?etat=a_accuser").json()
    assert [ligne["courrierId"] for ligne in a_accuser] == [enregistre]

    focal.post(f"{COURRIERS}/passages/{passage.pk}/accuse")
    assert focal.get(f"{COURRIERS}/bureau-ordre?etat=a_accuser").json() == []
    en_cours = focal.get(f"{COURRIERS}/bureau-ordre?etat=en_cours").json()
    assert [ligne["courrierId"] for ligne in en_cours] == [enregistre]

    focal.post(
        f"{COURRIERS}/passages/{passage.pk}/sortie",
        {"motif": "retour"},
        content_type="application/json",
    )
    assert focal.get(f"{COURRIERS}/bureau-ordre?etat=en_cours").json() == []
    sortis = focal.get(f"{COURRIERS}/bureau-ordre?etat=sortis").json()
    assert [ligne["courrierId"] for ligne in sortis] == [enregistre]


def test_tenir_un_bureau_d_ordre_exige_la_permission(connecte, enregistre):
    """
    `BO_STR`. Un collaborateur traite le courrier, il ne tient pas le registre.

    **401 et non 403** : `exige()` refuse en rendant `None`, et Ninja traduit
    une authentification refusee en 401 — c'est l'ADR 004, pour que le garde du
    front redirige au lieu d'afficher un ecran vide.
    """
    _coter(connecte, enregistre, "DSI-ET")
    assert connecte("agent.dsi").get(f"{COURRIERS}/bureau-ordre").status_code == 401


# =====================================================================
#  Le cloisonnement des instructions internes
# =====================================================================


def _affecter(connecte, courrier_id: int, identifiant: str, consigne: str) -> None:
    reponse = connecte("dir.dsi").post(
        f"{COURRIERS}/{courrier_id}/affectations",
        {"utilisateurId": compte(identifiant).pk, "consigne": consigne},
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content


def test_une_structure_cotee_ne_lit_pas_l_interieur_de_sa_voisine(connecte, enregistre):
    """
    Le defaut que ce module corrige : deux structures cotees sur le meme courrier
    lisaient chacune le journal complet de l'autre — qui a ete mis sur l'affaire,
    et avec quelle consigne.

    Ce qui reste ouvert est le **jalon** : la DAF continue de voir que le
    courrier a ete coté a la DSI. C'est le trajet, et le trajet regarde tout le
    monde.
    """
    _coter(connecte, enregistre, "DSI-ET", "DAF")
    _affecter(connecte, enregistre, "agent.dsi", "Ne pas répondre avant l'avis du juridique")

    voisin = connecte("focal.daf").get(f"{COURRIERS}/{enregistre}").json()
    libelles = [etape["libelle"] for etape in voisin["chronologie"]]
    assert any("Coté" in libelle for libelle in libelles)
    assert not any("Affecté" in libelle for libelle in libelles)
    instructions = [etape["instruction"] or "" for etape in voisin["chronologie"]]
    assert all("avis du juridique" not in instruction for instruction in instructions)

    interne = connecte("dir.dsi").get(f"{COURRIERS}/{enregistre}").json()
    assert any("Affecté" in etape["libelle"] for etape in interne["chronologie"])


def test_la_dsr_conserve_le_mapping_complet(connecte, enregistre):
    """
    L'exigence est explicite : « le profil DSR doit conserver l'acces au mapping
    complet — date, heure, responsable exact ou est bloque le courrier ».

    Le cloisonnement protege une structure de sa voisine, pas de son autorite de
    suivi. Sans ce test, un cloisonnement trop zele aurait passe pour une
    reussite.
    """
    _coter(connecte, enregistre, "DSI-ET", "DAF")
    _affecter(connecte, enregistre, "agent.dsi", "Ne pas répondre avant l'avis du juridique")

    fiche = connecte("dsr").get(f"{COURRIERS}/{enregistre}").json()
    assert any("Affecté" in etape["libelle"] for etape in fiche["chronologie"])

    vie = connecte("dsr").get(f"{COURRIERS}/{enregistre}/fiche-de-vie").json()
    assert any(etape["titre"].startswith("Affecté") for etape in vie["etapes"])
    assert [detenteur["nom"] for detenteur in vie["detenteurs"]] == ["Joseph Ateba"]


def test_le_voisin_voit_la_duree_de_detention_sans_le_nom(connecte, enregistre):
    """
    Le cloisonnement des detenteurs n'est pas celui du journal, et la nuance
    compte : la ligne **reste**, avec sa duree — le courrier a bien passe onze
    jours a la DSI, et le taire aurait fausse la lecture du trajet. C'est le
    **nom** de l'agent qui s'efface.
    """
    _coter(connecte, enregistre, "DSI-ET", "DAF")
    _affecter(connecte, enregistre, "agent.dsi", "Étude technique")

    vie = connecte("focal.daf").get(f"{COURRIERS}/{enregistre}/fiche-de-vie").json()
    assert len(vie["detenteurs"]) == 1
    assert vie["detenteurs"][0]["nom"] != "Joseph Ateba"
    assert vie["detenteurs"][0]["structure"] == "DSI-ET"


def test_l_instruction_en_cascade_ne_sort_pas_de_la_direction(connecte, enregistre):
    """
    Une cotation de **niveau 1** est la decision du Directeur general : elle
    regarde toutes les structures visees, instruction comprise.

    Une cotation de niveau superieur est la cascade interne d'une direction vers
    ses services, et « voyez cela avec le juridique » n'est pas destine a la
    direction voisine, cotee au meme rang.
    """
    _coter(connecte, enregistre, "DSI", "DAF")
    cascade = connecte("dir.dsi").post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dir.dsi").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI-ET").pk],
            "annotation": "Voyez cela avec le juridique avant de répondre",
        },
        content_type="application/json",
    )
    assert cascade.status_code == 201, cascade.content

    voisin = connecte("focal.daf").get(f"{COURRIERS}/{enregistre}").json()
    annotations = [cotation["annotation"] for cotation in voisin["cotations"]]
    assert "Voyez cela avec le juridique avant de répondre" not in annotations
    # La cotation elle-meme reste au dossier : c'est le trajet du courrier.
    assert len(voisin["cotations"]) == 2

    interne = connecte("dir.dsi").get(f"{COURRIERS}/{enregistre}").json()
    assert "Voyez cela avec le juridique avant de répondre" in [
        cotation["annotation"] for cotation in interne["cotations"]
    ]


def test_l_entree_et_la_sortie_sont_des_jalons_publics(connecte, enregistre):
    """
    L'exigence veut que le suivi d'une structure soit « gere par son bureau
    d'ordre — entree et sortie ». Ces deux faits sont donc du trajet, pas de
    l'interieur : les cloisonner aurait rendu le suivi impossible a la DSR comme
    aux co-traitantes.
    """
    _coter(connecte, enregistre, "DSI", "DAF")
    passage = PassageStructure.objects.get(courrier_id=enregistre, structure__code="DSI")
    connecte("focal.dsi").post(f"{COURRIERS}/passages/{passage.pk}/accuse")

    voisin = connecte("focal.daf").get(f"{COURRIERS}/{enregistre}").json()
    assert any("bureau d'ordre" in etape["libelle"] for etape in voisin["chronologie"])


# =====================================================================
#  La supervision des delais — le mapping transversal
# =====================================================================


def test_la_supervision_nomme_le_responsable_exact(connecte, enregistre):
    """
    « Date, heure, responsable exact ou est bloque le courrier. » Quand un agent
    est affecte, c'est lui — dire « la DSI » a sa place serait exactement
    l'imprecision que l'exigence reproche.
    """
    _coter(connecte, enregistre, "DSI-ET")
    _affecter(connecte, enregistre, "agent.dsi", "Étude technique")

    carte = connecte("dsr").get(f"{COURRIERS}/supervision").json()
    ligne = next(ligne for ligne in carte["lignes"] if ligne["courrierId"] == enregistre)
    assert ligne["detenteur"] == "Joseph Ateba"
    assert ligne["structure"] == "DSI-ET"
    assert ligne["depuis"] is not None


def test_la_supervision_voit_le_courrier_que_personne_n_a_ouvert(connecte, enregistre):
    """
    Le blocage le plus difficile a voir autrement : le courrier est arrive chez
    une structure et personne ne l'a ouvert. Aucun acteur ne s'y attache, donc
    aucune fiche de vie ne le signale.
    """
    _coter(connecte, enregistre, "DSI")

    carte = connecte("dsr").get(f"{COURRIERS}/supervision").json()
    ligne = next(ligne for ligne in carte["lignes"] if ligne["courrierId"] == enregistre)
    assert ligne["detenteur"] is None
    assert ligne["structure"] == "DSI"
    assert "non accusé" in ligne["motif"]


def test_un_courrier_non_cote_attend_le_bureau_d_ordre_central(connecte, enregistre):
    """Ni affecte ni recu quelque part : il attend l'autorite. C'est un fait, pas un trou."""
    carte = connecte("dsr").get(f"{COURRIERS}/supervision").json()
    ligne = next(ligne for ligne in carte["lignes"] if ligne["courrierId"] == enregistre)
    assert ligne["motif"] == "Enregistré, en attente de cotation"


def test_la_supervision_exige_le_droit_de_relancer(connecte, enregistre):
    """
    Sous `REL` et non sous `STAT` : ce n'est pas une statistique mais la liste de
    travail de celui qui relance. La meme permission ouvre le dossier interne
    dans `cloisonnement.py` — un ecran qui nommerait un detenteur que la fiche
    masque serait une fuite par la bande.

    401 et non 403 : voir `test_tenir_un_bureau_d_ordre_exige_la_permission`
    et l'ADR 004.
    """
    assert connecte("dir.dsi").get(f"{COURRIERS}/supervision").status_code == 401


# =====================================================================
#  Le routage direct
# =====================================================================


def test_une_facture_part_a_la_finance_sans_passer_par_le_dg(connecte, sotrapal):
    """
    L'exigence, mot pour mot : « les factures allant directement chez le DFC sans
    passer par le DG ».

    La cotation produite est une **vraie** cotation : elle porte son rang, elle
    declenche le passage en structure, elle s'inscrit au journal.
    """
    client = connecte("agent.scc")
    reponse = client.post(
        COURRIERS,
        _saisie(sotrapal, natureId=Nature.objects.get(code="FACTURE").pk, objet="Facture 4412"),
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content
    identifiant = reponse.json()["id"]

    fiche = client.get(f"{COURRIERS}/{identifiant}").json()
    assert fiche["structuresCotees"] == ["DAF"]
    assert any("Routage direct" in etape["libelle"] for etape in fiche["chronologie"])

    passage = PassageStructure.objects.get(courrier_id=identifiant)
    assert passage.structure.code == "DAF"


def test_le_routage_direct_ne_touche_pas_le_courrier_ordinaire(connecte, enregistre):
    """
    L'absence de regle veut dire « ce courrier suit la voie normale ». Il n'y a
    **pas** de regle de repli, a la difference de `circuit_regle` : un repli
    aurait coté d'office tout le courrier du Port a une structure unique.
    """
    assert PassageStructure.objects.filter(courrier_id=enregistre).count() == 0


def test_la_regle_la_plus_specifique_l_emporte(connecte, sotrapal):
    """
    « Facture de tel fournisseur » l'emporte sur « toute facture arrivee », sans
    qu'aucune priorite n'ait a etre tenue a la main.
    """
    RegleRoutage.objects.create(
        code="FACTURE_SOTRAPAL_DSI",
        libelle="Factures Sotrapal — à la DSI",
        nature=Nature.objects.get(code="FACTURE"),
        sens="arrive",
        correspondant=sotrapal,
        structure=Structure.objects.get(code="DSI"),
        mention_type=MentionType.objects.filter(code="SUITE").first(),
        # Priorite volontairement **plus haute** (donc moins prioritaire) que la
        # regle generale : c'est la specificite qui doit trancher, pas elle.
        priorite=900,
    )

    client = connecte("agent.scc")
    identifiant = client.post(
        COURRIERS,
        _saisie(sotrapal, natureId=Nature.objects.get(code="FACTURE").pk, objet="Facture 4413"),
        content_type="application/json",
    ).json()["id"]

    assert client.get(f"{COURRIERS}/{identifiant}").json()["structuresCotees"] == ["DSI"]


def test_le_routage_direct_s_eteint_sans_redeploiement(connecte, sotrapal):
    """
    Le parametre est une **hypothese** : personne n'a confirme que le bureau
    d'ordre central cote d'office plutot que de soumettre au Directeur general
    (A69). Il doit donc s'eteindre par l'administration, pas par une livraison.
    """
    from noyau.parametres.modeles import Parametre

    Parametre.objects.filter(cle="courrier.routage_direct_actif").update(valeur="false")
    vider_cache()

    client = connecte("agent.scc")
    identifiant = client.post(
        COURRIERS,
        _saisie(sotrapal, natureId=Nature.objects.get(code="FACTURE").pk, objet="Facture 4414"),
        content_type="application/json",
    ).json()["id"]

    assert client.get(f"{COURRIERS}/{identifiant}").json()["structuresCotees"] == []


# =====================================================================
#  Le schema tient ce que le code promet
# =====================================================================


def test_une_sortie_sans_motif_est_refusee_par_le_moteur(connecte, enregistre):
    """
    `passage_sortie_motivee`. La garde du service ne suffit pas : une reprise de
    donnees ou une commande de gestion ne passerait pas par lui.
    """
    _coter(connecte, enregistre, "DSI")
    passage = PassageStructure.objects.get(courrier_id=enregistre)

    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as curseur:
            curseur.execute(
                "UPDATE passage_structure SET sorti_le = now(), sorti_par = %s WHERE id = %s",
                [compte("focal.dsi").pk, passage.pk],
            )


def test_une_regle_de_routage_sans_critere_est_refusee(jeu):
    """
    `regle_routage_a_un_critere`. Une regle sans critere coterait tout le
    courrier du Port a une seule structure — c'est le repli qu'on ne veut pas.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        RegleRoutage.objects.create(
            code="TOUT_A_LA_DSI",
            libelle="Tout à la DSI",
            structure=Structure.objects.get(code="DSI"),
        )


def test_le_point_focal_tient_le_bureau_d_ordre_de_sa_structure(jeu):
    """
    Au Port, le bureau d'ordre d'une structure **est** son point focal. Le profil
    existait et ne portait aucune permission du domaine courrier : il alimentait
    les activites et la disponibilite, rien d'autre.
    """
    from noyau.habilitation.dependances import PERM
    from noyau.habilitation.resolution import possede

    focal = compte("focal.dsi")
    assert possede(focal, PERM.BO_STR)
    assert possede(focal, PERM.AFF)
    # Pas de CONF : le secret ne s'ouvre pas par la fonction.
    assert not possede(focal, PERM.CONF)

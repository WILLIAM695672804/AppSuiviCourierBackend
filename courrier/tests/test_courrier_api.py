"""
Le pilier courrier — `/api/courriers/*`.

Ce que ces tests protegent, dans l'ordre d'importance :

 1. **La visibilite.** C'est la seule chose ici dont l'echec ne provoque aucun
    plantage : un courrier montre a qui n'a pas a le lire ne casse rien et ne se
    remarque pas. Quatre portes et une serrure (ADR 022), et chacune est eprouvee
    dans les deux sens — ce qu'elle ouvre **et** ce qu'elle laisse ferme.
 2. **Le numero vient du moteur.** Le declencheur `courrier_numero` le compose
    sous verrou ; si Python s'en melait, deux agents enregistrant en meme temps
    obtiendraient le meme numero, et un registre a doublons n'est plus un
    registre.
 3. **`decide_par` n'est pas `saisi_par`.** Le DG cote, l'agent tape. La
    confusion viderait le journal de sa valeur probante, et elle ne se voit qu'en
    relisant la ligne.
 4. **Les vocabulaires traduits.** La base dit `arrive`, le front dit `ARRIVEE` ;
    un `str` en face d'un `str` passe toutes les revues de schemas. Le seul moyen
    de s'en apercevoir est de comparer les deux valeurs dans un test.
 5. **Le rang 1 est chef de file**, et le declencheur le recopie sur le courrier.

Ce qui n'est **pas** teste ici parce que rien ne le porte : la validation, la
transmission, les relances automatiques et les escalades. Toutes sont ancrees sur
`circuit_etape`, qui est vide (A24).
"""

import pytest
from django.core.management import call_command
from django.db import connection

from courrier.modeles import Cotation, CotationStructure, Courrier
from noyau.identite.modeles import SessionCourrier, Utilisateur, UtilisateurSession
from noyau.organisation.modeles import Structure
from noyau.parametrage.modeles import Correspondant, Nature
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
    """
    Un correspondant. **Le socle n'en seme aucun** : le carnet d'adresses d'une
    institution ne s'invente pas, et une entree fictive y resterait.
    """
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


# =====================================================================
#  Enregistrement — A-01
# =====================================================================


def test_le_numero_vient_du_moteur(connecte, sotrapal):
    """
    Le service insere `numero=""` et relit la ligne.

    Le format `0001/2026` est celui du declencheur. Si Python composait le numero,
    ce test passerait aussi — c'est pourquoi le suivant compte la sequence.
    """
    client = connecte("agent.scc")
    reponse = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")

    assert reponse.status_code == 201, reponse.content
    corps = reponse.json()
    assert corps["numero"].endswith(f"/{corps['dateReception'][:4]}")
    assert corps["numero"].split("/")[0].isdigit()
    assert len(corps["numero"].split("/")[0]) == 4


def test_deux_enregistrements_ne_partagent_pas_de_numero(connecte, sotrapal):
    """
    Le compteur avance d'exactement un par courrier.

    Le trou et le doublon sont les deux facons de ruiner un registre, et une seule
    des deux se voit a l'oeil : ce test attrape les deux.
    """
    client = connecte("agent.scc")
    numeros = []
    for _ in range(3):
        reponse = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")
        assert reponse.status_code == 201, reponse.content
        numeros.append(reponse.json()["numero"])

    rangs = sorted(int(numero.split("/")[0]) for numero in numeros)
    assert len(set(numeros)) == 3
    assert rangs == list(range(rangs[0], rangs[0] + 3))


def test_le_contexte_predit_sans_consommer(connecte, sotrapal):
    """
    `GET /courriers/contexte` **lit** la sequence, il ne l'incremente pas.

    Reserver un numero a l'ouverture d'un formulaire aurait troue la sequence des
    le premier abandon de saisie.
    """
    client = connecte("agent.scc")
    premier = client.get(f"{COURRIERS}/contexte").json()["numeroPrevu"]
    second = client.get(f"{COURRIERS}/contexte").json()["numeroPrevu"]

    assert premier == second

    client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")
    troisieme = client.get(f"{COURRIERS}/contexte").json()["numeroPrevu"]
    assert troisieme != premier


def test_on_n_ecrit_pas_dans_le_registre_d_un_autre(connecte, sotrapal):
    """
    L'agent est rattache au registre « Arrivée » : il n'inscrit pas au confidentiel.

    Consommer un numero du cahier d'autrui est irreversible — le trou reste.
    """
    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}",
        _saisie(sotrapal, typeSession="CONFIDENTIEL"),
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert "Arriv" in reponse.json()["message"]


def test_l_enregistrement_inscrit_un_evenement(connecte, sotrapal):
    """
    RNF-TRACE-01. Une ecriture sans evenement est une ecriture qui n'a pas eu
    lieu, pour l'agent qui relit la fiche de vie.
    """
    client = connecte("agent.scc")
    identifiant = client.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT type_evenement, acteur_id FROM evenement "
            "WHERE objet_type = 'courrier' AND objet_id = %s",
            [identifiant],
        )
        lignes = curseur.fetchall()

    assert lignes == [("courrier.enregistre", compte("agent.scc").pk)]


def test_l_echeance_saute_le_week_end(connecte, sotrapal):
    """
    Le delai se compte en **jours ouvres** — §15.

    Un delai calendaire aurait fait echoir le mercredi un courrier arrive le
    vendredi avec cinq jours, alors que l'agent n'a eu que trois jours de travail.
    """
    client = connecte("agent.scc")
    corps = client.post(
        f"{COURRIERS}", _saisie(sotrapal, delaiJours=5), content_type="application/json"
    ).json()

    courrier = Courrier.objects.get(pk=corps["id"])
    ecart = (courrier.date_limite - courrier.date_reception).days
    # Cinq jours ouvres font au moins cinq jours calendaires, et sept des que la
    # periode enjambe un week-end.
    assert 5 <= ecart <= 7
    assert courrier.date_limite.weekday() < 5


# =====================================================================
#  Traduction des vocabulaires
# =====================================================================


def test_le_sens_sort_en_vocabulaire_du_front(connecte, sotrapal):
    """La base ecrit `arrive`, le front lit `ARRIVEE`. Deux mots, une chose."""
    client = connecte("agent.scc")
    corps = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json").json()

    assert corps["sens"] == "ARRIVEE"
    assert Courrier.objects.get(pk=corps["id"]).sens == "arrive"


def test_urgent_se_relit_urgent(connecte, sotrapal):
    """
    La case « Urgent » ecrit `URGENT` et se relit `URGENTE`, jamais `TRES_URGENTE`.

    Le sens des mots est preserve dans les deux traversees : un agent qui coche
    « Urgent » et relit « Très urgent » cesserait de faire confiance a l'ecran.
    """
    client = connecte("agent.scc")
    urgent = client.post(
        f"{COURRIERS}", _saisie(sotrapal, urgent=True), content_type="application/json"
    ).json()
    ordinaire = client.post(
        f"{COURRIERS}", _saisie(sotrapal, urgent=False), content_type="application/json"
    ).json()

    assert urgent["priorite"] == "URGENTE"
    assert ordinaire["priorite"] == "NORMALE"
    assert Courrier.objects.get(pk=urgent["id"]).priorite.code == "URGENT"


def test_le_mode_de_cotation_n_est_pas_invente(connecte, sotrapal):
    """
    `modeCotation` est `None` : aucun circuit ne se deroule (A24).

    Et les deux vocabulaires ne parlent pas de la meme chose — la base oppose
    `directe` a `cascade` (une question de hauteur), le front `CASCADE` a
    `PARALLELE` (une question de simultaneite). Traduire aurait invente la regle.
    """
    client = connecte("agent.scc")
    corps = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json").json()

    assert client.get(f"{COURRIERS}/{corps['id']}").json()["modeCotation"] is None


# =====================================================================
#  Visibilite — ADR 022
# =====================================================================


def test_l_agent_voit_ce_qu_il_vient_d_enregistrer(connecte, sotrapal):
    """
    **La porte de la session.** Sans elle, l'agent recevrait un 404 sur la fiche
    vers laquelle son propre ecran le redirige : le courrier n'est encore cote a
    personne, et aucune des trois portes du client ne s'ouvre.
    """
    client = connecte("agent.scc")
    identifiant = client.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    assert client.get(f"{COURRIERS}/{identifiant}").status_code == 200
    numeros = [ligne["id"] for ligne in client.get(f"{COURRIERS}?vue=nonCotes").json()["lignes"]]
    assert identifiant in numeros


def test_un_courrier_non_cote_reste_ferme_aux_autres(connecte, sotrapal):
    """
    La porte de la session est **etroite** : elle n'ouvre que la session de l'agent.

    La directrice de la DSI n'est rattachee a aucun registre et le courrier n'est
    cote a personne : elle ne le voit pas. C'est la periode ou l'objet est en
    clair et ou rien n'est decide — la plus fermee, pas la plus ouverte.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    directrice = connecte("dir.dsi")
    assert directrice.get(f"{COURRIERS}/{identifiant}").status_code == 404


def test_hors_perimetre_repond_404_et_non_403(connecte, sotrapal):
    """
    Decision de cadrage D5.

    Repondre « interdit » confirmerait l'existence du courrier et celle de son
    expediteur a qui n'a pas a les connaitre. Le 403 est plus bavard que le 404,
    et c'est tout le sujet.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    autre = connecte("agent.dsi")
    reponse = autre.get(f"{COURRIERS}/{identifiant}")
    assert reponse.status_code == 404
    # Le message ne dit pas non plus lequel des deux cas s'applique.
    assert "n'existe pas" in reponse.json()["message"]


def test_la_cotation_ouvre_le_courrier_a_la_structure(connecte, sotrapal):
    """
    **La porte de la cotation.** Le courrier coté a la DSI devient visible de sa
    directrice, qui n'a ni session ni rattachement au registre.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    directrice = connecte("dir.dsi")
    assert directrice.get(f"{COURRIERS}/{identifiant}").status_code == 404

    session = connecte("agent.scc")
    reponse = session.post(
        f"{COURRIERS}/{identifiant}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content

    directrice = connecte("dir.dsi")
    assert directrice.get(f"{COURRIERS}/{identifiant}").status_code == 200


def test_le_suivi_ouvre_hors_de_sa_structure(connecte, sotrapal):
    """
    **La porte de la designation** — la raison d'etre de la quatrieme porte.

    La personne de la cotation pour suivi coordonne au-dessus du chef de file et
    rend compte au Directeur general ; elle vient souvent d'une autre direction, et
    aucune autre porte ne l'ouvrirait. Ici : coté a la DSI, suivi par la DAF.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    suiveuse = compte("focal.daf")
    session = connecte("agent.scc")
    reponse = session.post(
        f"{COURRIERS}/{identifiant}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
            "suiviParId": suiveuse.pk,
            "motifSuivi": "Dossier sensible, suivi rapproché demandé par le DG.",
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content

    daf = connecte("focal.daf")
    assert daf.get(f"{COURRIERS}/{identifiant}").status_code == 200


def test_le_confidentiel_est_une_serrure_que_la_consolidation_n_ouvre_pas(connecte, sotrapal):
    """
    La serrure est posee **avant** les portes.

    La portee `toutes` consolide sans lever le secret : l'attachee de suivi de la
    DSR voit tout le port et ne porte pas `CONF`. Le Directeur general, qui la
    porte, voit le courrier. C'est la difference entre consolider et deverrouiller.
    """
    # Le registre confidentiel, tenu par un agent qui y est rattache. Le
    # rattachement est **exclusif** — contrainte d'exclusion du moteur — donc on
    # deplace la ligne existante au lieu d'en ajouter une seconde.
    UtilisateurSession.objects.filter(
        utilisateur=compte("agent.scc"), retire_le__isnull=True
    ).update(session=SessionCourrier.objects.get(code="confidentiel"))

    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}",
        _saisie(sotrapal, typeSession="CONFIDENTIEL"),
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content
    identifiant = reponse.json()["id"]

    assert Courrier.objects.get(pk=identifiant).confidentiel is True

    consolidante = connecte("att.dsr")
    assert consolidante.get(f"{COURRIERS}/{identifiant}").status_code == 404

    dg = connecte("dg")
    assert dg.get(f"{COURRIERS}/{identifiant}").status_code == 200


def test_le_registre_ne_compte_pas_deux_fois(connecte, sotrapal):
    """
    `distinct()` n'est pas cosmetique.

    Les portes traversent `cotation_structure` : un courrier cote a trois
    structures visibles sortirait trois fois, et compterait trois fois dans le
    total affiche a cote du titre de l'ecran.
    """
    session = connecte("agent.scc")
    identifiant = session.post(
        f"{COURRIERS}", _saisie(sotrapal), content_type="application/json"
    ).json()["id"]

    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{identifiant}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [
                Structure.objects.get(code="DSI").pk,
                Structure.objects.get(code="DAF").pk,
            ],
        },
        content_type="application/json",
    )

    dg = connecte("dg")
    page = dg.get(f"{COURRIERS}").json()
    assert [ligne["id"] for ligne in page["lignes"]].count(identifiant) == 1
    assert page["total"] == len(page["lignes"])


# =====================================================================
#  Cotation — A-04
# =====================================================================


@pytest.fixture
def enregistre(connecte, sotrapal) -> int:
    client = connecte("agent.scc")
    return client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json").json()[
        "id"
    ]


def test_le_rang_un_est_chef_de_file(connecte, enregistre):
    """
    L'ordre de `structureIds` est ecrit en base, et le declencheur du socle recopie
    le rang 1 sur `courrier.structure_chef_file_id`.

    Le front lit `structuresCotees[0]` comme chef de file : un tri par nom ou par
    identifiant aurait designe le mauvais coordinateur.
    """
    dsi = Structure.objects.get(code="DSI")
    daf = Structure.objects.get(code="DAF")

    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            # La DAF d'abord : si le service triait par identifiant, la DSI
            # passerait devant, et ce test le verrait.
            "structureIds": [daf.pk, dsi.pk],
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content

    cotation = Cotation.objects.get(courrier_id=enregistre)
    rangs = {
        visee.structure.code: visee.rang
        for visee in CotationStructure.objects.filter(cotation=cotation).select_related("structure")
    }
    assert rangs == {"DAF": 1, "DSI": 2}

    courrier = Courrier.objects.get(pk=enregistre)
    assert courrier.structure_chef_file_id == daf.pk
    assert reponse.json()["structuresCotees"][0] == "DAF"


def test_l_autorite_qui_decide_n_est_pas_l_agent_qui_saisit(connecte, enregistre):
    """
    §3.4 et invariant 3 du socle. Une seule colonne aurait attribue a l'agent une
    decision qu'il n'a pas prise, ce qui vide le journal de sa valeur probante.
    """
    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content

    cotation = Cotation.objects.get(courrier_id=enregistre)
    assert cotation.decide_par_id == compte("dg").pk
    assert cotation.saisi_par_id == compte("agent.scc").pk

    lue = reponse.json()["cotations"][0]
    assert lue["decidePar"]["nomComplet"] == "Emmanuel Kingue"
    assert lue["saisiPar"]["nomComplet"] == "Marthe Fouda"


def test_une_structure_ne_se_cote_pas_deux_fois(connecte, enregistre):
    """Deux rangs pour la meme structure designeraient deux coordinateurs."""
    dsi = Structure.objects.get(code="DSI").pk
    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {"decideParId": compte("dg").pk, "decideLe": "", "structureIds": [dsi, dsi]},
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_une_decision_ne_se_date_pas_dans_le_futur(connecte, enregistre):
    """Une cotation signee demain n'existe pas, et son delai courrait a l'envers."""
    client = connecte("agent.scc")
    reponse = client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "2099-01-01T09:00:00+01:00",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )
    assert reponse.status_code == 409


def test_l_etape_suit_la_cotation(connecte, enregistre):
    """
    L'etape est **deduite**, jamais stockee.

    Aucune colonne n'a ete ecrite entre les deux lectures : c'est l'existence de la
    cotation qui fait passer `ENREGISTRE` a `COTE`.
    """
    client = connecte("agent.scc")
    assert client.get(f"{COURRIERS}/{enregistre}").json()["etape"] == "ENREGISTRE"

    client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )
    assert client.get(f"{COURRIERS}/{enregistre}").json()["etape"] == "COTE"


# =====================================================================
#  Affectation — A-05
# =====================================================================


def test_on_n_affecte_pas_hors_cotation(connecte, enregistre):
    """
    La cotation va vers une structure, l'affectation vers une personne.

    Affecter un agent dont la structure n'est pas cotee reviendrait a contourner la
    decision de l'autorite : c'est la seule chose que cette route ait a empecher.
    """
    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )

    directrice = connecte("dir.dsi")
    hors = directrice.post(
        f"{COURRIERS}/{enregistre}/affectations",
        {"utilisateurId": compte("focal.daf").pk, "consigne": "À traiter"},
        content_type="application/json",
    )
    assert hors.status_code == 409
    assert "pas cotée" in hors.json()["message"]

    dans = directrice.post(
        f"{COURRIERS}/{enregistre}/affectations",
        {"utilisateurId": compte("focal.dsi").pk, "consigne": "À traiter sous huitaine"},
        content_type="application/json",
    )
    assert dans.status_code == 201, dans.content
    assert dans.json()["etape"] == "AFFECTE"


def test_l_affectation_ouvre_le_courrier_a_l_agent(connecte, enregistre):
    """
    La porte de la designation vaut aussi pour l'agent affecte : c'est lui qui
    traite, et un agent de **portee `propre`** ne verrait rien sans elle — ni la
    porte du rattachement ni celle de la cotation ne s'ouvrent a cette portee.

    Les deux etats sont verifies : la cotation seule ne suffit pas, l'affectation
    ouvre. Sans le premier assert, le test passerait aussi si la porte de la
    cotation s'ouvrait a tort.
    """
    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI-ET").pk],
        },
        content_type="application/json",
    )

    charge = connecte("agent.dsi")
    assert charge.get(f"{COURRIERS}/{enregistre}").status_code == 404

    directrice = connecte("dir.dsi")
    reponse = directrice.post(
        f"{COURRIERS}/{enregistre}/affectations",
        {"utilisateurId": compte("agent.dsi").pk, "consigne": "Étude technique"},
        content_type="application/json",
    )
    assert reponse.status_code == 201, reponse.content

    charge = connecte("agent.dsi")
    assert charge.get(f"{COURRIERS}/{enregistre}").status_code == 200


def _numeros(reponse) -> list[str]:
    return [ligne["numero"] for ligne in reponse.json()["lignes"]]


def test_la_file_a_affecter_montre_ce_qui_est_cote_a_ma_structure(connecte, enregistre):
    """
    Le geste manquant du trajet : coter vise une structure, affecter vise une
    personne. Entre les deux, le courrier doit se lire quelque part comme un
    travail a faire — c'est cet onglet. ADR 040.
    """
    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI-ET").pk],
        },
        content_type="application/json",
    )

    numero = Courrier.objects.get(pk=enregistre).numero
    directrice = connecte("dir.dsi")
    assert numero in _numeros(directrice.get(f"{COURRIERS}?vue=aAffecter"))


def test_la_file_a_affecter_se_vide_par_l_affectation(connecte, enregistre):
    """
    L'anti-jointure est la partie fragile : ecrite avec un `__isnull=True` porte
    par la relation, Django produirait une jointure externe ou « aucune
    affectation » satisfait « aucune affectation retiree ». La file compterait
    alors tout le registre, et ne se viderait jamais.
    """
    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI-ET").pk],
        },
        content_type="application/json",
    )

    numero = Courrier.objects.get(pk=enregistre).numero
    directrice = connecte("dir.dsi")
    directrice.post(
        f"{COURRIERS}/{enregistre}/affectations",
        {"utilisateurId": compte("agent.dsi").pk, "consigne": "Étude technique"},
        content_type="application/json",
    )

    assert numero not in _numeros(directrice.get(f"{COURRIERS}?vue=aAffecter"))


def test_un_courrier_non_cote_n_est_pas_a_affecter(connecte, enregistre):
    """
    Il est « Non cote », et c'est un autre onglet : on n'affecte pas ce qui n'a
    ete confie a aucune structure. Sans cet assert, une file qui listerait tout
    le registre passerait le test precedent.
    """
    numero = Courrier.objects.get(pk=enregistre).numero
    directrice = connecte("dir.dsi")
    assert numero not in _numeros(directrice.get(f"{COURRIERS}?vue=aAffecter"))


def test_la_file_a_affecter_ne_deborde_pas_sur_les_autres_structures(connecte, enregistre):
    """
    Un courrier cote a la DSI n'est pas la file d'attente de la DSR. La regle de
    visibilite le protege deja (404 sur la fiche), mais un compteur trop large
    est une fuite discrete : le nombre dit quelque chose meme quand la liste est
    fermee.
    """
    session = connecte("agent.scc")
    session.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI-ET").pk],
        },
        content_type="application/json",
    )

    numero = Courrier.objects.get(pk=enregistre).numero
    autre = connecte("dir.daf")
    assert numero not in _numeros(autre.get(f"{COURRIERS}?vue=aAffecter"))


# =====================================================================
#  Fiche de vie et compteurs
# =====================================================================


def test_la_fiche_de_vie_dit_ou_le_courrier_a_attendu(connecte, enregistre):
    """
    `marge` est la piece maitresse : une liste d'horodatages laisse ce calcul a
    l'oeil du lecteur, et trois jours de silence entre deux lignes ne se
    remarquent pas.

    La premiere etape porte « — » et non « 0 min » : zero se lirait « traite
    instantanement », alors qu'il n'y a rien avant a quoi se comparer.
    """
    client = connecte("agent.scc")
    client.post(
        f"{COURRIERS}/{enregistre}/cotations",
        {
            "decideParId": compte("dg").pk,
            "decideLe": "",
            "structureIds": [Structure.objects.get(code="DSI").pk],
        },
        content_type="application/json",
    )

    vie = client.get(f"{COURRIERS}/{enregistre}/fiche-de-vie").json()
    assert [etape["titre"].split(" ")[0] for etape in vie["etapes"]] == ["Courrier", "Coté"]
    assert vie["etapes"][0]["marge"] == "—"
    assert all(etape["jalon"] for etape in vie["etapes"])
    assert all(etape["conforme"] for etape in vie["etapes"])


def test_les_compteurs_sont_muets_sans_droit_de_lecture(connecte, enregistre):
    """
    La route est ouverte a toute session — la barre laterale se monte pour tout
    compte connecte — et la garde est donc portee par la lecture.

    Un compteur juste rendu a qui ne peut pas ouvrir la liste apprend quelque
    chose du registre : c'est une fuite discrete. L'usager du portail ne porte que
    `EXT`.
    """
    usager = connecte("usager.sotrapal")
    assert usager.get("/api/compteurs").json() == {
        "courriers": 0,
        "cotations": 0,
        "relances": 0,
    }

    session = connecte("agent.scc")
    compteurs = session.get("/api/compteurs").json()
    assert compteurs["courriers"] == 1
    assert compteurs["cotations"] == 1


def test_les_indicateurs_nomment_ce_qu_ils_ne_mesurent_pas(connecte, enregistre):
    """
    ADR 011. La variation suppose une periode de reference, la serie un historique
    que rien n'archive. Une courbe montante sous un chiffre de trois se lirait
    comme une mesure.
    """
    client = connecte("agent.scc")
    indicateurs = client.get(f"{COURRIERS}/indicateurs").json()

    assert indicateurs["arrivesAujourdHui"]["valeur"] == 1
    assert indicateurs["enAttenteCotation"]["valeur"] == 1
    # Aucun courrier cote : le delai moyen de cotation n'est pas « 0 h », qui se
    # lirait « cotation instantanee » — la meilleure valeur possible la ou il n'y
    # a aucune valeur.
    assert indicateurs["delaiMoyenCotation"]["valeur"] == "Non mesuré"
    assert all(mesure["variation"] == "Non mesuré" for mesure in indicateurs.values())
    assert all(mesure["serie"] == [] for mesure in indicateurs.values())


def test_le_fil_d_observations_est_vide_et_pas_par_oubli(connecte, enregistre):
    """
    Aucune table ne porte d'observation datee et signee.

    `courrier.observations` est un texte libre saisi a l'enregistrement, sans
    auteur ni horodatage : le rendre comme une observation lui aurait attribue
    l'agent et l'heure du dernier enregistrement, ce qui est faux.
    """
    client = connecte("agent.scc")
    assert client.get(f"{COURRIERS}/{enregistre}").json()["observations"] == []


# =====================================================================
#  Registre
# =====================================================================


def test_la_recherche_ignore_les_accents(connecte, sotrapal):
    """
    Le vecteur plein texte est construit avec la configuration `fr_unaccent` :
    « delegation » trouve « délégation ».

    Un `icontains` aurait echoue sur un accent, et l'agent aurait conclu que le
    courrier n'existait pas.
    """
    client = connecte("agent.scc")
    client.post(
        f"{COURRIERS}",
        _saisie(sotrapal, objet="Délégation de signature pour la période de congés"),
        content_type="application/json",
    )

    trouves = client.get(f"{COURRIERS}?q=delegation").json()
    assert trouves["total"] == 1


def test_la_recherche_par_numero_ne_passe_pas_par_le_vecteur(connecte, sotrapal):
    """
    `to_tsvector` decoupe `0042/2026` en jetons, et une recherche plein texte sur
    « 0042 » ne le retrouve pas de facon fiable. Or c'est la premiere chose qu'un
    agent tape.
    """
    client = connecte("agent.scc")
    numero = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json").json()[
        "numero"
    ]

    trouves = client.get(f"{COURRIERS}?q={numero.split('/')[0]}").json()
    assert [ligne["numero"] for ligne in trouves["lignes"]] == [numero]


def test_le_total_du_registre_ne_suit_pas_le_filtre(connecte, sotrapal):
    """
    `total` compte ce que le filtre retient, `totalRegistre` compte le registre.

    Les confondre ferait dire « 12 courriers » a un registre qui en contient huit
    cents — c'est le nombre affiche a cote du titre de l'ecran.
    """
    client = connecte("agent.scc")
    for _ in range(2):
        client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")

    page = client.get(f"{COURRIERS}?vue=clotures").json()
    assert page["total"] == 0
    assert page["totalRegistre"] == 2


def test_une_vue_inconnue_ne_vide_pas_l_ecran(connecte, enregistre):
    """
    Un filtre mal orthographie qui vide l'ecran se lit comme une panne. C'est la
    convention du pilier dossiers, reprise ici.
    """
    client = connecte("agent.scc")
    assert client.get(f"{COURRIERS}?vue=nimportequoi").json()["total"] == 1


def test_le_registre_interne_ne_montre_pas_les_arrivees(connecte, sotrapal):
    """
    L'ecran « Courriers internes » filtrait sur rien et affichait les arrivees : le
    defaut d'un parametre facultatif ne se voit pas a la lecture.
    """
    client = connecte("agent.scc")
    client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")

    assert client.get(f"{COURRIERS}?sens=ARRIVEE").json()["total"] == 1
    assert client.get(f"{COURRIERS}?sens=INTERNE").json()["total"] == 0


# =====================================================================
#  Gardes de permission
# =====================================================================


def test_enregistrer_exige_la_permission(connecte, sotrapal):
    """
    `ENR`. Le charge d'etudes porte `LEC` et `TRA` : il lit, il ne tient pas le
    registre.

    **401 et non 403** : la garde est portee par `ExigePermission`, qui herite de
    `SessionAuth` et rend `None` — Ninja en fait une erreur d'authentification. Le
    garde du front y renvoie a l'ecran de connexion en retenant la destination, et
    un 403 le ferait echouer sans le dire. C'est la convention de tout le socle.
    """
    client = connecte("agent.dsi")
    reponse = client.post(f"{COURRIERS}", _saisie(sotrapal), content_type="application/json")
    assert reponse.status_code == 401


def test_le_registre_est_ferme_a_qui_n_a_pas_lec(connecte):
    """`LEC`. L'usager du portail ne porte que `EXT`."""
    client = connecte("usager.sotrapal")
    assert client.get(f"{COURRIERS}").status_code == 401

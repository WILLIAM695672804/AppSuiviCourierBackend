"""
Le portail usagers — `/api/portail/*`.

Ce que ces tests protegent, dans l'ordre de ce qui fait mal :

 1. **Le cloisonnement.** Un usager ne voit ni la demande d'un autre, ni celle
    d'un agent, et une demande qui n'est pas la sienne repond 404 — pas 403,
    qui confirmerait son existence (D5). C'est la seule fuite du depot qui
    serait atteignable depuis l'exterieur de l'institution.
 2. **Les deux notifications qui ne se coupent pas.** L'ecran les grise ; un
    appel direct a la route les couperait si le serveur ne les rallumait pas.
    Un usager qui n'est pas prevenu d'une demande de piece est forclos.
 3. **Le delai annonce avant le depot est celui qui est tenu.** Le front
    l'affichait en dur ; il vient desormais de la base, et la date promise est
    figee sur la demande.
 4. **Ce qu'on attend de l'usager passe en tete.** Une piece a fournir avant
    vendredi ne doit pas etre enterree sous trois dossiers termines.
 5. **Une piece satisfait un complement, un message seul ne le satisfait pas.**
    « Je vous l'envoie demain » n'est pas la piece.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametres.service import vider_cache
from portail.modeles import (
    ComplementDemande,
    DemandeUsager,
    EchangeDematerialise,
    EvenementNotifiable,
    PieceEchange,
    PreferenceEvenement,
    PreferenceNotification,
)

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
DEMANDES = "/api/portail/demandes"
PREFERENCES = "/api/portail/preferences"
ECHANGES = "/api/portail/echanges"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    # Le delai de reponse vit en base (A43) et `parametres.valeur()` le met en
    # cache : sans ce vidage, un test heriterait de la valeur lue par le
    # precedent, dans une base qui n'existe plus.
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


def _usager(identifiant: str = "usager.sotrapal") -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


def _demande(
    *,
    reference: str = "DEM-2026-0001",
    deposant: str = "usager.sotrapal",
    objet: str = "Autorisation d'occupation du quai 4",
    service: str | None = None,
    depose_il_y_a: int = 5,
    decision: str | None = None,
    close: bool = False,
) -> DemandeUsager:
    jour = date.today() - timedelta(days=depose_il_y_a)
    return DemandeUsager.objects.create(
        reference=reference,
        type="Demande",
        objet=objet,
        contexte="Occupation temporaire pour des travaux de maintenance.",
        deposant=_usager(deposant),
        deposee_le=jour,
        reponse_attendue_le=jour + timedelta(days=30),
        service_instructeur=(Structure.objects.en_vigueur().get(code=service) if service else None),
        decision_le=date.today() if decision else None,
        decision=decision,
        clos_le=date.today() if close else None,
    )


# =====================================================================
#  Le cloisonnement — ce qui fait le plus mal
# =====================================================================


def test_un_usager_ne_voit_que_ses_propres_demandes(connecte):
    _demande(reference="DEM-2026-0001", deposant="usager.sotrapal")
    _demande(reference="DEM-2026-0002", deposant="usager.camtrans")

    reponse = connecte("usager.sotrapal").get(DEMANDES)

    assert reponse.status_code == 200
    references = [ligne["reference"] for ligne in reponse.json()["demandes"]]
    assert references == ["DEM-2026-0001"]


def test_la_demande_d_un_autre_usager_repond_404_et_non_403(connecte):
    autre = _demande(reference="DEM-2026-0002", deposant="usager.camtrans")

    reponse = connecte("usager.sotrapal").get(f"{DEMANDES}/{autre.pk}")

    # 403 confirmerait l'existence de la demande : sur un portail ouvert au
    # public, cela permettrait de les enumerer une reference a la fois.
    assert reponse.status_code == 404


def test_un_agent_du_port_n_ouvre_pas_le_portail(connecte):
    """Le Directeur general porte beaucoup de permissions. Pas `EXT`."""
    assert connecte("dg").get(DEMANDES).status_code == 401


def test_l_usager_n_a_aucun_perimetre_et_voit_pourtant_ses_demandes(connecte):
    """
    La preuve que le portail ne passe pas par `restreindre()` (ADR 013).

    Le semis ne pose aucun perimetre sur un compte externe. Si la lecture
    passait par le perimetre du socle, la liste serait vide — c'est la regle 3
    de `noyau/perimetre/portee.py` : un agent sans perimetre ne voit rien.
    """
    from noyau.perimetre.modeles import Perimetre

    assert not Perimetre.objects.filter(utilisateur=_usager()).exists()

    _demande()
    reponse = connecte("usager.sotrapal").get(DEMANDES)

    assert len(reponse.json()["demandes"]) == 1


def test_on_ne_repond_pas_sur_la_demande_d_un_autre(connecte):
    autre = _demande(reference="DEM-2026-0002", deposant="usager.camtrans")

    reponse = connecte("usager.sotrapal").post(
        f"{DEMANDES}/{autre.pk}/messages",
        {"demandeId": autre.pk, "texte": "Bonjour, où en est mon dossier ?", "pieces": []},
        content_type="application/json",
    )

    assert reponse.status_code == 404


def test_le_chemin_fait_foi_et_non_le_corps(connecte):
    """
    Le corps porte `demandeId` parce que le front le construit ainsi. Si le
    serveur s'y fiait, on ecrirait sur une demande en en nommant une autre.
    """
    mienne = _demande(reference="DEM-2026-0001")
    autre = _demande(reference="DEM-2026-0002", deposant="usager.camtrans")

    reponse = connecte("usager.sotrapal").post(
        f"{DEMANDES}/{mienne.pk}/messages",
        {"demandeId": autre.pk, "texte": "Message pour ma propre demande.", "pieces": []},
        content_type="application/json",
    )

    assert reponse.status_code == 201
    assert mienne.messages.count() == 1
    assert autre.messages.count() == 0


# =====================================================================
#  Le depot
# =====================================================================


def test_le_depot_annonce_le_delai_avant_de_deposer(connecte):
    """
    Le formulaire annonce le delai ; il vient de la base et non du front. Les
    deux doivent etre le meme nombre, sinon la promesse affichee et la date
    calculee divergent.
    """
    reponse = connecte("usager.sotrapal").get(DEMANDES)

    assert reponse.json()["delaiReponseJours"] == 30


def test_le_depot_fige_la_date_promise(connecte):
    client = connecte("usager.sotrapal")

    reponse = client.post(
        DEMANDES,
        {
            "type": "Autorisation",
            "objet": "Occupation temporaire du terre-plein sud",
            "contexte": "Stockage de conteneurs pendant la durée des travaux du quai 4.",
            "pieces": [{"nom": "plan-implantation.pdf", "taille": "1,2 Mo"}],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    demande = DemandeUsager.objects.get(pk=reponse.json()["id"])
    assert demande.reference == "DEM-2026-0001"
    assert demande.reponse_attendue_le == date.today() + timedelta(days=30)
    assert demande.pieces.count() == 1
    # Le service n'est pas devine : aucune regle d'affectation n'existe pour
    # les demandes du portail (A44).
    assert demande.service_instructeur_id is None


def test_un_objet_trop_court_est_refuse(connecte):
    reponse = connecte("usager.sotrapal").post(
        DEMANDES,
        {"type": "Demande", "objet": "Quai 4", "contexte": "x" * 40, "pieces": []},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert "dix caractères" in reponse.json()["message"]


def test_un_type_de_demande_invente_est_refuse(connecte):
    reponse = connecte("usager.sotrapal").post(
        DEMANDES,
        {
            "type": "Doléance",
            "objet": "Une demande dont le type n'existe pas",
            "contexte": "x" * 40,
            "pieces": [],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409


def test_les_references_se_suivent_dans_l_exercice(connecte):
    client = connecte("usager.sotrapal")
    corps = {
        "type": "Demande",
        "objet": "Demande d'information sur les tarifs",
        "contexte": "Nous préparons une réponse à un appel d'offres et cherchons la grille.",
        "pieces": [],
    }

    premiere = client.post(DEMANDES, corps, content_type="application/json").json()["id"]
    seconde = client.post(DEMANDES, corps, content_type="application/json").json()["id"]

    assert DemandeUsager.objects.get(pk=premiere).reference == f"DEM-{date.today().year}-0001"
    assert DemandeUsager.objects.get(pk=seconde).reference == f"DEM-{date.today().year}-0002"


# =====================================================================
#  Mes demandes — l'ordre de l'ecran
# =====================================================================


def test_ce_qu_on_attend_de_l_usager_passe_en_tete(connecte):
    _demande(reference="DEM-2026-0001", depose_il_y_a=2)
    attend = _demande(reference="DEM-2026-0002", depose_il_y_a=20)
    ComplementDemande.objects.create(
        demande=attend,
        objet="Attestation de régularité fiscale",
        demande_le=date.today() - timedelta(days=3),
        avant_le=date.today() + timedelta(days=7),
    )

    lignes = connecte("usager.sotrapal").get(DEMANDES).json()["demandes"]

    assert lignes[0]["reference"] == "DEM-2026-0002"
    assert lignes[0]["actionAttendue"] is True
    assert lignes[0]["etat"] == "Complément attendu"


def test_une_demande_close_n_attend_plus_de_piece(connecte):
    """
    L'ordre de `etat_demande()` compte : close l'emporte sur complement. On ne
    reclame pas une piece pour un dossier termine.
    """
    demande = _demande(close=True, decision="Autorisation accordée pour six mois.")
    ComplementDemande.objects.create(
        demande=demande,
        objet="Une pièce jamais fournie",
        demande_le=date.today() - timedelta(days=10),
        avant_le=date.today() - timedelta(days=3),
    )

    ligne = connecte("usager.sotrapal").get(DEMANDES).json()["demandes"][0]

    assert ligne["etat"] == "Close"


def test_une_demande_sans_service_dit_qu_elle_est_en_orientation(connecte):
    _demande()

    ligne = connecte("usager.sotrapal").get(DEMANDES).json()["demandes"][0]

    # Pas un service choisi par defaut : l'usager irait telephoner au mauvais
    # guichet, et le guichet decouvrirait un dossier qu'il n'a pas.
    assert ligne["serviceInstructeur"] == "En cours d'orientation"
    assert ligne["etat"] == "Déposée"


# =====================================================================
#  Le suivi — la frise expliquee
# =====================================================================


def test_la_frise_explique_chaque_etape_sans_jargon(connecte):
    demande = _demande(service="DAF")

    corps = connecte("usager.sotrapal").get(f"{DEMANDES}/{demande.pk}").json()

    libelles = [etape["libelle"] for etape in corps["etapes"]]
    assert libelles == ["Demande reçue", "Prise en charge", "Réponse", "Dossier clos"]
    # Aucun mot de l'institution dans ce que lit l'usager.
    texte = " ".join(etape["explication"] for etape in corps["etapes"]).lower()
    assert "cotation" not in texte
    assert "structure pilote" not in texte
    assert all(etape["explication"] for etape in corps["etapes"])


def test_la_piece_attendue_s_intercale_la_ou_elle_bloque(connecte):
    demande = _demande(service="DAF")
    ComplementDemande.objects.create(
        demande=demande,
        objet="Attestation de régularité fiscale",
        demande_le=date.today(),
        avant_le=date.today() + timedelta(days=10),
    )

    corps = connecte("usager.sotrapal").get(f"{DEMANDES}/{demande.pk}").json()

    libelles = [etape["libelle"] for etape in corps["etapes"]]
    assert libelles[2] == "Pièce attendue de votre part"
    assert corps["complementAttendu"]["objet"] == "Attestation de régularité fiscale"


def test_la_reponse_promise_est_ecrite_tant_qu_aucune_decision_n_est_rendue(connecte):
    demande = _demande()

    corps = connecte("usager.sotrapal").get(f"{DEMANDES}/{demande.pk}").json()

    reponse = next(e for e in corps["etapes"] if e["libelle"] == "Réponse")
    assert reponse["franchie"] is False
    assert demande.reponse_attendue_le.isoformat() in reponse["explication"]


def test_la_decision_rendue_est_le_texte_de_l_etape(connecte):
    demande = _demande(decision="Autorisation accordée pour six mois, renouvelable.")

    corps = connecte("usager.sotrapal").get(f"{DEMANDES}/{demande.pk}").json()

    reponse = next(e for e in corps["etapes"] if e["libelle"] == "Réponse")
    assert reponse["franchie"] is True
    assert reponse["explication"] == "Autorisation accordée pour six mois, renouvelable."
    assert corps["etat"] == "Décision rendue"


# =====================================================================
#  Repondre
# =====================================================================


def test_une_piece_satisfait_le_complement_attendu(connecte):
    demande = _demande(service="DAF")
    complement = ComplementDemande.objects.create(
        demande=demande,
        objet="Attestation de régularité fiscale",
        demande_le=date.today(),
        avant_le=date.today() + timedelta(days=10),
    )

    reponse = connecte("usager.sotrapal").post(
        f"{DEMANDES}/{demande.pk}/messages",
        {
            "demandeId": demande.pk,
            "texte": "Voici l'attestation demandée.",
            "pieces": [{"nom": "attestation.pdf", "taille": "240 Ko"}],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    complement.refresh_from_db()
    assert complement.satisfait_le == date.today()


def test_un_message_sans_piece_ne_satisfait_pas_le_complement(connecte):
    """
    « Je vous l'envoie demain » n'est pas la piece. Fermer l'attente sur cette
    phrase aurait fait passer le dossier pour complet aupres du service.
    """
    demande = _demande(service="DAF")
    complement = ComplementDemande.objects.create(
        demande=demande,
        objet="Attestation de régularité fiscale",
        demande_le=date.today(),
        avant_le=date.today() + timedelta(days=10),
    )

    connecte("usager.sotrapal").post(
        f"{DEMANDES}/{demande.pk}/messages",
        {"demandeId": demande.pk, "texte": "Je vous l'envoie demain.", "pieces": []},
        content_type="application/json",
    )

    complement.refresh_from_db()
    assert complement.satisfait_le is None


def test_on_ne_repond_pas_a_une_demande_close(connecte):
    demande = _demande(close=True, decision="Dossier traité.")

    reponse = connecte("usager.sotrapal").post(
        f"{DEMANDES}/{demande.pk}/messages",
        {"demandeId": demande.pk, "texte": "Une question de plus.", "pieces": []},
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert demande.reference in reponse.json()["message"]


def test_le_message_porte_le_bon_auteur_du_point_de_vue_du_lecteur(connecte):
    demande = _demande(service="DAF")
    connecte("usager.sotrapal").post(
        f"{DEMANDES}/{demande.pk}/messages",
        {"demandeId": demande.pk, "texte": "Bonjour, une précision sur mon dossier.", "pieces": []},
        content_type="application/json",
    )

    corps = connecte("usager.sotrapal").get(f"{DEMANDES}/{demande.pk}").json()

    assert corps["messages"][0]["auteur"] == "Vous"
    assert corps["pieces"] == []


# =====================================================================
#  Preferences de notification
# =====================================================================


def test_sans_reglage_les_valeurs_par_defaut_sont_rendues_sans_rien_ecrire(connecte):
    corps = connecte("usager.sotrapal").get(PREFERENCES).json()

    assert corps["canal"] == "Courriel"
    assert all(evenement["actif"] for evenement in corps["evenements"])
    # Une consultation n'ecrit rien.
    assert not PreferenceNotification.objects.filter(utilisateur=_usager()).exists()


def test_le_serveur_rallume_les_notifications_obligatoires(connecte):
    """
    L'ecran grise les deux cases. Un appel direct a la route les couperait si
    le serveur ne les rallumait pas — et l'usager serait forclos sans le savoir.
    """
    reponse = connecte("usager.sotrapal").post(
        PREFERENCES,
        {
            "courriel": "contact@sotrapal.cm",
            "telephone": None,
            "canal": "Courriel",
            # Ni « complement » ni « decision » : l'usager tente de les couper.
            "evenements": ["depot"],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 201
    reglage = PreferenceNotification.objects.get(utilisateur=_usager())
    coupes = {
        ligne.evenement.cle: ligne.actif
        for ligne in PreferenceEvenement.objects.filter(preference=reglage).select_related(
            "evenement"
        )
    }
    assert coupes["complement"] is True
    assert coupes["decision"] is True
    assert coupes["echeance"] is False


def test_la_lecture_dit_lesquelles_sont_obligatoires(connecte):
    corps = connecte("usager.sotrapal").get(PREFERENCES).json()

    obligatoires = {e["cle"] for e in corps["evenements"] if e["obligatoire"]}
    assert obligatoires == {"complement", "decision"}


def test_le_canal_sms_sans_numero_est_refuse(connecte):
    """
    Basculer silencieusement sur le courriel aurait laisse l'usager croire
    qu'il est prevenu par SMS. Il vaut mieux un refus qu'un faux confort.
    """
    reponse = connecte("usager.sotrapal").post(
        PREFERENCES,
        {
            "courriel": "contact@sotrapal.cm",
            "telephone": "  ",
            "canal": "SMS",
            "evenements": ["depot"],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409
    assert "numéro" in reponse.json()["message"]


def test_un_courriel_sans_arobase_est_refuse(connecte):
    reponse = connecte("usager.sotrapal").post(
        PREFERENCES,
        {
            "courriel": "contact.sotrapal.cm",
            "telephone": None,
            "canal": "Courriel",
            "evenements": [],
        },
        content_type="application/json",
    )

    assert reponse.status_code == 409


def test_une_ligne_qui_aurait_coupe_un_obligatoire_est_ignoree_a_la_lecture(connecte):
    """
    Defense en profondeur : une ligne arrivee par une importation ou une
    migration ne doit pas priver l'usager de la demande de complement.
    """
    reglage = PreferenceNotification.objects.create(
        utilisateur=_usager(), courriel="contact@sotrapal.cm", canal="Courriel"
    )
    PreferenceEvenement.objects.create(
        preference=reglage,
        evenement=EvenementNotifiable.objects.get(cle="complement"),
        actif=False,
    )

    corps = connecte("usager.sotrapal").get(PREFERENCES).json()

    complement = next(e for e in corps["evenements"] if e["cle"] == "complement")
    assert complement["actif"] is True


# =====================================================================
#  Echanges dematerialises
# =====================================================================


def _echange(
    reference: str,
    *,
    nature: str = "Marché public",
    partenaire: str = "usager.sotrapal",
    attendus: int = 3,
    deposes: int = 0,
    clos: bool = False,
) -> EchangeDematerialise:
    echange = EchangeDematerialise.objects.create(
        reference=reference,
        intitule=f"Objet de {reference}",
        nature=nature,
        partenaire=_usager(partenaire),
        ouvert_le=date.today() - timedelta(days=15),
        echeance=date.today() + timedelta(days=15),
        attendus=attendus,
        clos_le=date.today() if clos else None,
    )
    for rang in range(deposes):
        PieceEchange.objects.create(
            echange=echange,
            nom=f"piece-{rang}.pdf",
            taille="500 Ko",
            deposee_le=date.today(),
            depose_par=_usager(partenaire),
        )
    return echange


def test_les_trois_natures_d_echange_sont_servies(connecte):
    _echange("MP-2026-001", nature="Marché public")
    _echange("CV-2026-002", nature="Convention", deposes=3)
    _echange("RP-2026-003", nature="Reporting réglementaire", attendus=1, deposes=1, clos=True)

    lignes = connecte("usager.sotrapal").get(ECHANGES).json()["echanges"]

    assert {ligne["nature"] for ligne in lignes} == {
        "Marché public",
        "Convention",
        "Reporting réglementaire",
    }


def test_l_echange_en_attente_de_depot_passe_en_tete(connecte):
    _echange("CV-2026-002", attendus=2, deposes=2)
    _echange("MP-2026-001", attendus=3, deposes=1)

    lignes = connecte("usager.sotrapal").get(ECHANGES).json()["echanges"]

    assert lignes[0]["reference"] == "MP-2026-001"
    assert lignes[0]["etat"] == "En attente de votre dépôt"
    assert lignes[0]["deposes"] == 1


def test_un_echange_complet_mais_non_clos_reste_ouvert(connecte):
    """
    L'usager n'a plus rien a faire, mais l'affaire n'est pas reglee : c'est a
    l'institution de fermer. Les deux informations sont differentes.
    """
    _echange("CV-2026-002", attendus=2, deposes=2)

    ligne = connecte("usager.sotrapal").get(ECHANGES).json()["echanges"][0]

    assert ligne["etat"] == "Ouvert"


def test_un_usager_ne_voit_pas_l_echange_d_un_autre(connecte):
    _echange("MP-2026-001", partenaire="usager.camtrans")

    lignes = connecte("usager.sotrapal").get(ECHANGES).json()["echanges"]

    assert lignes == []


def test_les_echanges_exigent_la_permission_du_portail(connecte):
    assert connecte("dir.dsi").get(ECHANGES).status_code == 401

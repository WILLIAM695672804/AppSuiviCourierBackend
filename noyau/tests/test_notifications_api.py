"""
Les notifications — `/api/notifications/*`.

Ce que ces tests protegent, dans l'ordre d'importance :

 1. **Une notification est adressee a une personne, et a elle seule.** Les
    routes sont en `session_seule` : il n'y a pas de permission a oublier, donc
    pas de decorateur qui protege. Le filtre par destinataire est *toute* la
    garde, et un manquement se lirait chez un autre agent.
 2. **La notification interne existe toujours**, meme quand aucun canal
    sortant n'est branche. C'est ce qui fait qu'une panne de messagerie n'est
    pas une perte d'information.
 3. **`sans_transport` n'est pas `echoue`.** Un envoi qui n'a nulle part ou
    aller ne doit pas etre rejoue indefiniment, et l'ecran d'exploitation doit
    montrer ce qui manque plutot qu'un incident imaginaire.
 4. **Un evenement obligatoire passe outre le refus de l'usager.** Le
    complement ouvre un delai de forclusion : le laisser couper reviendrait a
    laisser l'usager organiser sa propre forclusion.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command

from noyau.identite.modeles import Utilisateur
from noyau.notifications import services
from noyau.notifications.modeles import (
    CANAL_COURRIEL,
    CANAL_SMS,
    ETAT_ECHOUE,
    ETAT_EN_ATTENTE,
    ETAT_ENVOYE,
    ETAT_SANS_TRANSPORT,
    EnvoiNotification,
    Notification,
)
from noyau.parametres.modeles import Parametre
from noyau.parametres.service import vider_cache

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
NOTIFICATIONS = "/api/notifications"


@pytest.fixture
def jeu(db):
    call_command("semer", force=True)
    vider_cache()
    yield
    vider_cache()


@pytest.fixture
def connecte(client, jeu):
    def _connecter(identifiant: str):
        client.force_login(compte(identifiant), backend=BACKEND)
        return client

    return _connecter


def compte(identifiant: str) -> Utilisateur:
    return Utilisateur.objects.get(identifiant_annuaire=identifiant)


def _notifier(destinataire: str = "focal.dsi", **surcharges) -> Notification:
    # `dict[str, Any]` : `notifier` accepte des chaines, des entiers et des
    # booleens, et un dictionnaire infere comme `dict[str, str]` refuserait le
    # premier appel qui passe une importance et un identifiant d'objet.
    corps: dict = {
        "type_notification": "relance_activite",
        "libelle": "Relance sur « Refonte du réseau »",
        "detail": "Deux semaines de retard sur l'échéance.",
    }
    corps.update(surcharges)
    return services.notifier(compte(destinataire), **corps)


# =====================================================================
#  Ce qui est adresse a une personne
# =====================================================================


def test_un_agent_ne_voit_que_ses_propres_notifications(connecte):
    """
    Le test qui compte le plus : il n'y a pas de permission sur ces routes, donc
    pas de décorateur à relire. Le filtre par destinataire est toute la garde.
    """
    _notifier("focal.dsi", libelle="Pour la DSI")
    _notifier("focal.daf", libelle="Pour la DAF")

    corps = connecte("focal.dsi").get(NOTIFICATIONS).json()

    assert [n["libelle"] for n in corps["notifications"]] == ["Pour la DSI"]


def test_marquer_lue_la_notification_d_autrui_repond_404(connecte):
    """404 et non 403 (D5) : le libellé d'une notification en dit déjà long sur
    ce qui se passe dans une autre direction."""
    notification = _notifier("focal.daf")

    reponse = connecte("focal.dsi").post(f"{NOTIFICATIONS}/{notification.pk}/lecture")

    assert reponse.status_code == 404
    notification.refresh_from_db()
    assert notification.lu_le is None


def test_sans_session_rien_ne_se_lit(client, jeu):
    assert client.get(NOTIFICATIONS).status_code == 401


def test_l_etat_de_la_file_exige_une_permission(connecte):
    """La file n'est pas une lecture personnelle : c'est de l'exploitation."""
    # 401 et non 403 : c'est ce que renvoie `ExigePermission` dans tout le
    # dépôt — la réponse ne distingue pas « pas connecté » de « pas habilité ».
    assert connecte("focal.dsi").get(f"{NOTIFICATIONS}/file").status_code == 401
    assert connecte("admin").get(f"{NOTIFICATIONS}/file").status_code == 200


# =====================================================================
#  La lecture
# =====================================================================


def test_les_non_lues_sont_servies_en_tete(connecte):
    """Une alerte d'hier non lue compte plus qu'une information de ce matin."""
    ancienne = _notifier("focal.dsi", libelle="Non lue, ancienne")
    services.marquer_lue(compte("focal.dsi"), _notifier("focal.dsi", libelle="Lue").pk)

    corps = connecte("focal.dsi").get(NOTIFICATIONS).json()

    assert corps["notifications"][0]["libelle"] == ancienne.libelle
    assert corps["nonLues"] == 1


def test_la_premiere_lecture_est_la_seule_qui_date(connecte):
    """C'est elle qui répond à « l'a-t-elle vue à temps ? »."""
    notification = _notifier("focal.dsi")
    client = connecte("focal.dsi")

    client.post(f"{NOTIFICATIONS}/{notification.pk}/lecture")
    notification.refresh_from_db()
    premiere = notification.lu_le

    client.post(f"{NOTIFICATIONS}/{notification.pk}/lecture")
    notification.refresh_from_db()

    assert notification.lu_le == premiere


def test_tout_marquer_lu_rend_le_compte(connecte):
    _notifier("focal.dsi")
    _notifier("focal.dsi")
    _notifier("focal.daf")

    reponse = connecte("focal.dsi").post(f"{NOTIFICATIONS}/lecture")

    assert reponse.json() == {"marquees": 2}
    assert Notification.objects.filter(lu_le__isnull=True).count() == 1


def test_une_notification_lue_reste_lisible(connecte):
    """Une notification qui disparaît après lecture est une information qu'on ne
    peut plus retrouver."""
    notification = _notifier("focal.dsi")
    client = connecte("focal.dsi")
    client.post(f"{NOTIFICATIONS}/{notification.pk}/lecture")

    corps = client.get(NOTIFICATIONS).json()

    assert len(corps["notifications"]) == 1
    assert corps["notifications"][0]["lue"] is True


# =====================================================================
#  La mise en file
# =====================================================================


def test_la_notification_interne_existe_sans_aucun_canal_sortant(jeu):
    """
    Un agent n'a pas de préférence de notification — il n'en a pas le choix, ce
    sont des alertes de service. La notification interne suffit, et elle est
    créée quoi qu'il arrive.
    """
    notification = _notifier("focal.dsi")

    assert Notification.objects.filter(pk=notification.pk).exists()
    assert notification.envois.count() == 0


def test_on_ne_se_notifie_pas_de_son_propre_acte(jeu):
    """L'agent qui vient de coter un courrier sait qu'il l'a coté."""
    from noyau.erreurs import ErreurMetier

    with pytest.raises(ErreurMetier) as echec:
        services.notifier(
            compte("focal.dsi"),
            type_notification="relance_activite",
            libelle="À moi-même",
            acteur=compte("focal.dsi"),
        )

    assert echec.value.code == "notification_a_soi_meme"


def test_l_accuse_de_reception_est_la_seule_exception(jeu):
    """Il n'apprend pas à l'usager ce qu'il vient de faire : il lui confirme que
    l'institution l'a reçu."""
    usager = compte("usager.sotrapal")

    notification = services.notifier(
        usager,
        type_notification="depot",
        libelle="Demande enregistrée",
        acteur=usager,
        accuse_de_reception=True,
    )

    assert notification.destinataire_id == usager.pk


def test_le_canal_choisi_par_l_usager_produit_un_envoi(jeu):
    """Un agent n'a pas de préférence ; un usager du portail, oui."""
    _preference("usager.sotrapal", canal="Courriel", courriel="contact@sotrapal.cm")

    notification = services.notifier(
        compte("usager.sotrapal"),
        type_notification="depot",
        libelle="Demande enregistrée",
    )

    envoi = notification.envois.get()
    assert envoi.canal == CANAL_COURRIEL
    assert envoi.adresse == "contact@sotrapal.cm"
    assert envoi.etat == ETAT_EN_ATTENTE


def test_le_canal_sms_sans_numero_ne_produit_aucun_envoi(jeu):
    """Mieux vaut ne rien envoyer que d'écrire à une coordonnée devinée."""
    _preference("usager.sotrapal", canal="SMS", courriel="contact@sotrapal.cm", telephone=None)

    notification = services.notifier(
        compte("usager.sotrapal"),
        type_notification="depot",
        libelle="Demande enregistrée",
    )

    assert notification.envois.count() == 0


def test_un_evenement_coupe_ne_sort_pas(jeu):
    """« Portail seulement » n'est pas l'absence de notification : l'usager est
    prévenu, mais il doit venir lire."""
    preference = _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    _couper(preference, "depot")

    notification = services.notifier(
        compte("usager.sotrapal"),
        type_notification="depot",
        libelle="Demande enregistrée",
    )

    assert notification.envois.count() == 0
    # La notification interne, elle, existe : c'est ce qui distingue « ne pas
    # recevoir de courriel » de « ne pas être prévenu ».
    assert Notification.objects.filter(pk=notification.pk).exists()


def test_un_evenement_obligatoire_passe_outre_le_refus(jeu):
    """
    Le complément ouvre un délai de forclusion. Laisser l'usager le couper
    reviendrait à le laisser organiser sa propre forclusion — la règle vit dans
    `EvenementNotifiable.obligatoire`, et elle se vérifie ici aussi.
    """
    preference = _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    _couper(preference, "complement")

    notification = services.notifier(
        compte("usager.sotrapal"),
        type_notification="complement",
        libelle="Pièce complémentaire demandée",
    )

    assert notification.envois.count() == 1


# =====================================================================
#  Le depilement
# =====================================================================


def test_le_sms_n_a_pas_de_transport_et_le_dit(jeu):
    """
    `sans_transport` n'est pas `echoue`. Rien n'a échoué : rien n'a été tenté,
    faute de passerelle (A48).
    """
    _preference("usager.sotrapal", canal="SMS", courriel="c@x.cm", telephone="690000000")
    services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )

    compte_rendu = services.depiler()

    envoi = EnvoiNotification.objects.get(canal=CANAL_SMS)
    assert envoi.etat == ETAT_SANS_TRANSPORT
    assert "passerelle" in envoi.erreur.lower()
    assert compte_rendu["sans_transport"] == 1
    assert compte_rendu["echoues"] == 0


def test_le_courriel_coupe_ne_part_pas(jeu):
    """La règle `notifications.courriel_actif` est une hypothèse, et elle est
    fausse par défaut : un environnement de recette qui écrit à de vraies
    adresses est un incident, pas un essai."""
    _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )

    services.depiler()

    envoi = EnvoiNotification.objects.get(canal=CANAL_COURRIEL)
    assert envoi.etat == ETAT_SANS_TRANSPORT
    assert "courriel_actif" in envoi.erreur


def test_le_courriel_part_quand_la_regle_est_ouverte(jeu, mailoutbox):
    """Le code d'envoi existe et fonctionne : seule la règle le coupe."""
    _regle("notifications.courriel_actif", "true")
    _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    services.notifier(
        compte("usager.sotrapal"),
        type_notification="depot",
        libelle="Demande enregistrée",
        detail="Réponse promise pour le 30/09/2026.",
    )

    compte_rendu = services.depiler()

    assert compte_rendu["envoyes"] == 1
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["c@sotrapal.cm"]
    envoi = EnvoiNotification.objects.get()
    assert envoi.etat == ETAT_ENVOYE
    assert envoi.envoye_le is not None


def test_un_envoi_sans_transport_n_est_jamais_rejoue(jeu):
    """Réessayer ne changerait rien tant qu'une décision d'infrastructure n'a
    pas été prise. Le compteur de tentatives ne le concerne pas."""
    _preference("usager.sotrapal", canal="SMS", courriel="c@x.cm", telephone="690000000")
    services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )
    services.depiler()

    second = services.depiler()

    assert second["traites"] == 0


def test_le_depilement_ne_repasse_pas_au_dela_des_tentatives(jeu):
    """Une adresse invalide ne doit pas faire battre la file contre un mur."""
    _regle("notifications.tentatives_max", "1")
    _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    notification = services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )
    # Un envoi déjà en échec, une tentative au compteur.
    notification.envois.update(etat=ETAT_ECHOUE, tentatives=1)

    assert services.depiler()["traites"] == 0


def test_l_etat_de_la_file_distingue_les_deux_causes(connecte):
    """`sansTransport` se lit avant les échecs : ce n'est pas une panne, c'est ce
    que l'institution n'a pas branché."""
    _preference("usager.sotrapal", canal="SMS", courriel="c@x.cm", telephone="690000000")
    services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )
    services.depiler()

    corps = connecte("admin").get(f"{NOTIFICATIONS}/file").json()

    ligne = next(c for c in corps["canaux"] if c["canal"] == CANAL_SMS)
    assert ligne["sansTransport"] == 1
    assert ligne["echoues"] == 0
    assert corps["bloques"][0]["canal"] == CANAL_SMS
    assert corps["bloques"][0]["raison"]


def test_un_envoi_ne_part_pas_deux_fois(jeu):
    """Une contrainte d'unicité par canal : c'est ainsi qu'une institution
    apprend à ignorer ses propres messages."""
    from django.db.utils import IntegrityError

    _preference("usager.sotrapal", canal="Courriel", courriel="c@sotrapal.cm")
    notification = services.notifier(
        compte("usager.sotrapal"), type_notification="depot", libelle="Demande enregistrée"
    )

    with pytest.raises(IntegrityError):
        EnvoiNotification.objects.create(
            notification=notification, canal=CANAL_COURRIEL, adresse="c@sotrapal.cm"
        )


# =====================================================================
#  Ce que les piliers en font
# =====================================================================


def test_le_depot_d_une_demande_accuse_reception(jeu):
    """Sans l'accusé, le dépôt n'a pour trace qu'un écran que l'usager a fermé."""
    from portail.services import deposer_demande

    demande = deposer_demande(
        compte("usager.sotrapal"),
        type_demande="Demande",
        objet="Autorisation d'occupation du quai 4",
        contexte="Occupation temporaire pour des travaux de maintenance du poste.",
    )

    notification = Notification.objects.get(destinataire=compte("usager.sotrapal"))
    assert notification.type_notification == "depot"
    assert demande.reference in notification.libelle
    assert notification.lien == f"/portail/demandes/{demande.pk}"


def test_la_reclamation_de_complement_previent_l_usager(jeu):
    """Ce délai est un délai de forclusion : le silence coûte le dossier."""
    from portail.services import deposer_demande, reclamer_complement

    demande = deposer_demande(
        compte("usager.sotrapal"),
        type_demande="Demande",
        objet="Autorisation d'occupation du quai 4",
        contexte="Occupation temporaire pour des travaux de maintenance du poste.",
    )

    reclamer_complement(
        compte("agent.scc"),
        demande_id=demande.pk,
        objet="Attestation d'assurance en cours de validité",
        avant_le=date.today() + timedelta(days=10),
    )

    notification = Notification.objects.get(type_notification="complement")
    assert notification.destinataire_id == compte("usager.sotrapal").pk
    assert notification.importance == "alerte"


# =====================================================================
#  Outils
# =====================================================================


def _preference(identifiant: str, *, canal: str, courriel: str, telephone: str | None = None):
    from portail.modeles import PreferenceNotification

    return PreferenceNotification.objects.create(
        utilisateur=compte(identifiant),
        canal=canal,
        courriel=courriel,
        telephone=telephone,
    )


def _couper(preference, cle: str) -> None:
    from portail.modeles import EvenementNotifiable, PreferenceEvenement

    PreferenceEvenement.objects.create(
        preference=preference,
        evenement=EvenementNotifiable.objects.get(cle=cle),
        actif=False,
    )


def _regle(cle: str, valeur: str) -> None:
    Parametre.objects.filter(cle=cle).update(valeur=valeur)
    vider_cache()

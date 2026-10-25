"""
Les pieces jointes — `/api/pieces/*`.

Ce que ces tests protegent, dans l'ordre d'importance :

 1. **La garde, qui n'est pas dans le decorateur.** La permission depend de
    l'objet auquel on rattache, et `exige()` ne sait pas poser une question qui
    depend du corps de la requete. Toute la protection est portee par
    `services._cible_accessible` (ADR 017) : si elle cede, une piece se depose
    sur un dossier qu'on ne voit pas, et devient lisible par ceux qui le voient.
 2. **L'empreinte est calculee, jamais annoncee.** RF-GED-09. Une empreinte
    fournie par le client ne prouve que sa bonne foi.
 3. **Une version n'ecrase jamais la precedente**, et rien ne se supprime.
    RF-GED-04. Le test le verifie sur le binaire, pas seulement sur la ligne.
 4. **Le plafond porte sur la taille reellement lue.** Un plafond controle sur
    un nombre envoye par celui qu'on veut limiter ne limite personne.
"""

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from activite.modeles import Activite, AxeStrategique, Exercice, PlanActions
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.parametres.service import vider_cache
from noyau.pieces import stockage
from noyau.pieces.modeles import PieceJointe

BACKEND = "noyau.identite.authentification.BackendAnnuaire"
PIECES = "/api/pieces"


@pytest.fixture
def jeu(db, tmp_path, settings):
    """
    Le volume des pieces est deporte dans un repertoire temporaire.

    Sans cela, la suite ecrirait dans `MEDIA_ROOT` et laisserait des fichiers
    derriere elle. `tmp_path` est propre a chaque test : deux tests qui
    deposent le meme contenu ne partagent donc pas le fichier deduplique, ce
    qui est ici une bonne chose — ils sont independants.
    """
    settings.MEDIA_ROOT = str(tmp_path)
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
def activite(jeu) -> Activite:
    """Une activite de la DSI, dont `focal.dsi` est responsable."""
    structure = Structure.objects.get(code="DSI")
    exercice = Exercice.objects.get(ouvert=True)
    plan, _ = PlanActions.objects.get_or_create(structure=structure, exercice=exercice)
    return Activite.objects.create(
        plan=plan,
        axe_strategique=AxeStrategique.objects.get(code="A1"),
        intitule="Refonte du réseau du terminal",
        responsable=compte("focal.dsi"),
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
    )


def _fichier(nom: str = "rapport.pdf", contenu: bytes = b"%PDF-1.7 contenu de test"):
    return SimpleUploadedFile(nom, contenu, content_type="application/pdf")


def _deposer(client, activite, **surcharges):
    corps = {
        "fichier": _fichier(),
        "objetType": "activite",
        "objetId": str(activite.pk),
    }
    corps.update(surcharges)
    return client.post(PIECES, corps)


# =====================================================================
#  La garde
# =====================================================================


def test_sans_session_aucun_depot(client, jeu, activite):
    assert _deposer(client, activite).status_code == 401


def test_sans_la_permission_du_pilier_le_depot_est_refuse(connecte, activite):
    """
    `archiviste` porte `ARCH`, pas `ACT_SAI`. Joindre une pièce à une activité
    est un acte de saisie d'activité, pas d'archivage.

    **404 et non 403** : répondre « interdit » confirmerait que l'activité
    existe, et cette confirmation est déjà une fuite (D5).
    """
    assert _deposer(connecte("archiviste"), activite).status_code == 404


def test_hors_perimetre_le_depot_est_refuse(connecte, activite):
    """
    L'activité est à la DSI ; l'agent du service courrier n'y a pas accès.

    C'est le test qui compte le plus de ce fichier : sans lui, une pièce se
    déposerait sur un objet invisible et deviendrait lisible par ceux qui le
    voient.
    """
    reponse = _deposer(connecte("agent.scc"), activite)

    assert reponse.status_code in (401, 404)
    assert not PieceJointe.objects.filter(objet_type="activite").exists()


def test_un_type_hors_registre_est_refuse(connecte, activite):
    """
    Accepter un `objetType` inconnu reviendrait à accepter n'importe quelle
    chaîne, donc à déposer des fichiers rattachés à rien — que nul écran ne
    montre et que nulle règle de conservation n'atteint.
    """
    reponse = _deposer(connecte("focal.dsi"), activite, objetType="table_inventee")

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "type_non_rattachable"


def test_une_piece_ne_se_lit_pas_hors_du_perimetre_de_son_objet(connecte, activite):
    """Une pièce n'a pas de droits propres : ce sont ceux de son objet."""
    uid = _deposer(connecte("focal.dsi"), activite).json()["uid"]

    assert connecte("agent.scc").get(f"{PIECES}/{uid}/contenu").status_code in (401, 404)


def test_qui_lit_l_activite_lit_ses_pieces_sans_droit_d_y_ecrire(connecte, activite):
    """
    `dcg` porte `ACT_LEC` et `ACT_VAL`, **pas** `ACT_SAI`, en portée `toutes` :
    le contrôle de gestion lit et valide le plan de la DSI sans y saisir.

    C'est le test du correctif. Le registre de rattachement ne déclarait qu'une
    permission — celle d'écriture — et la lecture s'en servait faute de mieux :
    `dcg` recevait 404 sur les pièces d'une activité dont il lisait tout le
    reste. Une pièce a les droits de son objet, et cela vaut dans les deux
    sens : qui voit l'objet voit ce qui y est joint.
    """
    depose = _deposer(connecte("focal.dsi"), activite).json()["uid"]
    lecteur = connecte("dcg")

    liste = lecteur.get(PIECES, {"objetType": "activite", "objetId": activite.pk})
    assert liste.status_code == 200
    assert [p["uid"] for p in liste.json()] == [depose]

    assert lecteur.get(f"{PIECES}/{depose}/contenu").status_code == 200


def test_lire_les_pieces_n_autorise_pas_a_en_deposer_ni_a_en_retirer(connecte, activite):
    """
    L'envers du correctif, et ce qui empêche de l'avoir élargi trop loin.

    `dcg` lit les pièces de l'activité (test précédent) mais n'y écrit rien :
    verser une pièce ou en retirer une reste un acte de saisie. Si ce test
    cède, la séparation entre les deux permissions du registre n'existe plus.
    """
    uid = _deposer(connecte("focal.dsi"), activite).json()["uid"]
    lecteur = connecte("dcg")

    assert _deposer(lecteur, activite).status_code == 404
    assert (
        lecteur.post(
            f"{PIECES}/{uid}/retrait",
            {"motif": "Tentative de retrait par le contrôle de gestion."},
            content_type="application/json",
        ).status_code
        == 404
    )
    assert PieceJointe.objects.get(uid=uid).invalide_le is None


# =====================================================================
#  Le depot
# =====================================================================


def test_le_depot_ecrit_le_binaire_et_la_ligne(connecte, activite):
    reponse = _deposer(connecte("focal.dsi"), activite)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nom"] == "rapport.pdf"
    assert corps["extension"] == "pdf"
    assert corps["version"] == 1

    piece = PieceJointe.objects.get(uid=corps["uid"])
    assert (stockage.racine() / piece.chemin_stockage).exists()


def test_l_empreinte_est_celle_du_contenu_reel(connecte, activite):
    """
    RF-GED-09. Elle est calculée en lisant le fichier ; une empreinte annoncée
    par le client ne prouverait que sa bonne foi.
    """
    import hashlib

    contenu = b"%PDF-1.7 un contenu bien precis"
    reponse = _deposer(connecte("focal.dsi"), activite, fichier=_fichier(contenu=contenu))

    assert reponse.json()["empreinte"] == hashlib.sha256(contenu).hexdigest()


def test_le_chemin_ne_porte_jamais_le_nom_d_origine(connecte, activite):
    """
    « ../../etc/passwd » ne doit jamais atteindre le système de fichiers. Le
    chemin est dérivé de l'empreinte, le nom d'origine reste une donnée.
    """
    reponse = _deposer(
        connecte("focal.dsi"), activite, fichier=_fichier(nom="../../rapport secret.pdf")
    )

    piece = PieceJointe.objects.get(uid=reponse.json()["uid"])
    assert ".." not in piece.chemin_stockage
    assert piece.chemin_stockage.endswith(piece.empreinte_sha256)


def test_deux_depots_du_meme_contenu_ne_font_qu_un_fichier(connecte, activite):
    """Un rapport envoyé à quatre directions est un objet sur le disque et
    quatre lignes en base."""
    client = connecte("focal.dsi")
    premier = _deposer(client, activite).json()
    second = _deposer(client, activite).json()

    assert premier["uid"] != second["uid"]
    assert premier["empreinte"] == second["empreinte"]
    assert len(list((stockage.racine()).rglob("*"))) == 3  # ab/ + ab/cd/ + le fichier


def test_le_nom_peut_etre_donne_a_part(connecte, activite):
    """Un scan s'appelle `SCAN_0042.pdf` ; on le dépose sous un nom lisible."""
    reponse = _deposer(
        connecte("focal.dsi"),
        activite,
        fichier=_fichier(nom="SCAN_0042.pdf"),
        nom="Rapport de mission — août 2026.pdf",
    )

    assert reponse.json()["nom"] == "Rapport de mission — août 2026.pdf"


# =====================================================================
#  Ce qui est refuse
# =====================================================================


def test_une_extension_hors_liste_est_refusee(connecte, activite):
    reponse = _deposer(
        connecte("focal.dsi"), activite, fichier=_fichier(nom="script.sh", contenu=b"rm -rf /")
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "extension_refusee"


def test_un_fichier_deguise_est_refuse(connecte, activite):
    reponse = _deposer(
        connecte("focal.dsi"),
        activite,
        fichier=_fichier(nom="rapport.pdf", contenu=b"#!/bin/sh\necho attaque"),
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "signature_fichier_refusee"
    assert not PieceJointe.objects.filter(objet_type="activite").exists()


def test_un_fichier_sans_extension_est_refuse(connecte, activite):
    """Sans extension, l'agent qui télécharge ne sait pas ouvrir le fichier."""
    reponse = _deposer(connecte("focal.dsi"), activite, fichier=_fichier(nom="rapport"))

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "extension_manquante"


def test_un_fichier_vide_est_refuse(connecte, activite):
    reponse = _deposer(connecte("focal.dsi"), activite, fichier=_fichier(contenu=b""))

    assert reponse.status_code == 409


def test_le_plafond_porte_sur_la_taille_lue(connecte, activite):
    """
    **Le plafond est vérifié sur ce que le serveur lit**, pas sur ce que le
    client annonce. Un plafond contrôlé sur un nombre envoyé par celui qu'on
    veut limiter ne limite personne.

    Le paramètre est abaissé plutôt que d'envoyer 25 Mo : le test doit vérifier
    la règle, pas la bande passante.
    """
    from noyau.parametres.modeles import Parametre

    Parametre.objects.filter(cle="pieces.taille_maximale_mo").update(valeur="1")
    vider_cache()

    lourd = _fichier(contenu=b"x" * (2 * 1024 * 1024))
    reponse = _deposer(connecte("focal.dsi"), activite, fichier=lourd)

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "fichier_trop_lourd"


# =====================================================================
#  Versions — RF-GED-04
# =====================================================================


def test_une_nouvelle_version_n_ecrase_pas_la_precedente(connecte, activite):
    client = connecte("focal.dsi")
    premiere = _deposer(client, activite, fichier=_fichier(contenu=b"%PDF version un")).json()

    seconde = _deposer(
        client,
        activite,
        fichier=_fichier(contenu=b"%PDF version deux"),
        remplaceUid=premiere["uid"],
    ).json()

    assert seconde["version"] == 2
    # La ligne précédente est intacte, et son binaire aussi.
    ancienne = PieceJointe.objects.get(uid=premiere["uid"])
    assert ancienne.invalide_le is None
    assert (stockage.racine() / ancienne.chemin_stockage).exists()
    assert ancienne.empreinte_sha256 != seconde["empreinte"]


def test_seule_la_version_courante_est_listee(connecte, activite):
    """Lister cinq versions à plat ferait chercher longtemps laquelle est la
    bonne."""
    client = connecte("focal.dsi")
    premiere = _deposer(client, activite, fichier=_fichier(contenu=b"%PDF un")).json()
    _deposer(client, activite, fichier=_fichier(contenu=b"%PDF deux"), remplaceUid=premiere["uid"])

    lignes = client.get(f"{PIECES}?objetType=activite&objetId={activite.pk}").json()

    assert len(lignes) == 1
    assert lignes[0]["version"] == 2
    assert [v["version"] for v in lignes[0]["versions"]] == [1]


def test_une_version_d_un_autre_objet_est_refusee(connecte, activite, jeu):
    """Sans ce contrôle, la chaîne des versions traverserait deux objets."""
    structure = Structure.objects.get(code="DSI")
    exercice = Exercice.objects.get(ouvert=True)
    plan, _ = PlanActions.objects.get_or_create(structure=structure, exercice=exercice)
    autre = Activite.objects.create(
        plan=plan,
        axe_strategique=AxeStrategique.objects.get(code="A1"),
        intitule="Autre activité",
        responsable=compte("focal.dsi"),
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
    )

    client = connecte("focal.dsi")
    premiere = _deposer(client, activite).json()
    reponse = _deposer(
        client, autre, fichier=_fichier(contenu=b"%PDF autre"), remplaceUid=premiere["uid"]
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "version_d_un_autre_objet"


# =====================================================================
#  Telechargement et retrait
# =====================================================================


def test_le_telechargement_rend_le_contenu_depose(connecte, activite):
    contenu = b"%PDF-1.7 le contenu exact"
    uid = _deposer(connecte("focal.dsi"), activite, fichier=_fichier(contenu=contenu)).json()["uid"]

    reponse = connecte("focal.dsi").get(f"{PIECES}/{uid}/contenu")

    assert reponse.status_code == 200
    assert b"".join(reponse.streaming_content) == contenu
    # En pièce attachée, sans exception : servir en affichage direct un fichier
    # déposé par un tiers l'exécuterait dans le domaine de l'application.
    assert "attachment" in reponse["Content-Disposition"]


def test_le_telechargement_est_trace(connecte, activite):
    """RF-ADM-03. Sortir un document est le geste après lequel l'institution
    n'en a plus le contrôle."""
    from noyau.journal.modeles import JournalAcces

    uid = _deposer(connecte("focal.dsi"), activite).json()["uid"]
    connecte("focal.dsi").get(f"{PIECES}/{uid}/contenu")

    assert JournalAcces.objects.filter(objet_type="piece_jointe", action="telechargement").exists()


def test_une_piece_versee_apparait_dans_la_fiche_de_vie(connecte, activite):
    """
    La chronologie rattache une pièce au geste qui l'a versée par
    `donnees["pieceUid"]`. Ce dépôt-ci inscrivait `uid` : les pièces téléversées
    par `POST /pieces` figuraient dans l'onglet des pièces jointes et **jamais**
    dans la fiche de vie, où l'événement « Pièce versée » restait nu.

    Le test traverse volontairement les deux piliers : c'est un accord entre le
    socle qui écrit le journal et l'activité qui le relit, et un accord ne se
    vérifie pas d'un seul côté.
    """
    client = connecte("focal.dsi")
    nom = _deposer(client, activite).json()["nom"]

    detail = client.get(f"/api/activites/{activite.pk}").json()
    versements = [e for e in detail["vie"] if e["pieces"]]

    assert [p["nom"] for e in versements for p in e["pieces"]] == [nom]


def test_une_mention_sans_binaire_ne_se_telecharge_pas_et_le_dit(connecte, activite):
    """
    Le pilier activité a inscrit, jusqu'au 17 août 2026, des pièces sans
    fichier : un nom et un poids, `chemin_stockage` et `empreinte_sha256` vides.
    Les lignes restent en base — rien ne se supprime — et ce test fixe ce
    qu'elles doivent produire.

    **Deux exigences, et la seconde est celle qui a été signalée.** La liste ne
    doit pas les donner pour téléchargeables, et le téléchargement ne doit pas
    répondre « enregistré mais introuvable sur le volume » : ce message envoie
    ouvrir un ticket à l'exploitation pour un binaire qui n'a jamais existé.
    """
    piece = PieceJointe.objects.create(
        objet_type="activite",
        objet_id=activite.pk,
        nom_fichier="rapport de mars.pdf",
        nom_original="rapport de mars.pdf",
        taille_octets=1_258_291,
        empreinte_sha256="",
        chemin_stockage="",
        categorie="justificatif",
        cree_par=compte("focal.dsi").pk,
    )
    client = connecte("focal.dsi")

    liste = client.get(PIECES, {"objetType": "activite", "objetId": activite.pk}).json()
    assert [p["telechargeable"] for p in liste] == [False]

    reponse = client.get(f"{PIECES}/{piece.uid}/contenu")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "piece_sans_binaire"


def test_une_piece_versee_est_telechargeable(connecte, activite):
    """L'envers du test précédent : le drapeau doit distinguer, pas refuser."""
    _deposer(connecte("focal.dsi"), activite)

    liste = (
        connecte("focal.dsi").get(PIECES, {"objetType": "activite", "objetId": activite.pk}).json()
    )

    assert [p["telechargeable"] for p in liste] == [True]


def test_le_retrait_n_efface_rien(connecte, activite):
    """Un binaire effacé ferait échouer la vérification d'intégrité d'un dossier
    déjà archivé."""
    client = connecte("focal.dsi")
    uid = _deposer(client, activite).json()["uid"]

    reponse = client.post(
        f"{PIECES}/{uid}/retrait",
        {"motif": "Versée par erreur sur la mauvaise activité."},
        content_type="application/json",
    )

    assert reponse.status_code == 200
    piece = PieceJointe.objects.get(uid=uid)
    assert piece.invalide_le is not None
    assert (stockage.racine() / piece.chemin_stockage).exists()
    # Et elle reste téléchargeable : l'auditeur qui remonte un dossier a besoin
    # de voir ce qui y figurait.
    assert client.get(f"{PIECES}/{uid}/contenu").status_code == 200


def test_un_retrait_sans_motif_est_refuse(connecte, activite):
    client = connecte("focal.dsi")
    uid = _deposer(client, activite).json()["uid"]

    reponse = client.post(
        f"{PIECES}/{uid}/retrait", {"motif": "   "}, content_type="application/json"
    )

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "motif_exige"


def test_il_n_existe_aucune_suppression(connecte, activite):
    """Le filet : une route `DELETE` ajoutée un jour par commodité ne se verrait
    dans aucun autre test."""
    client = connecte("focal.dsi")
    uid = _deposer(client, activite).json()["uid"]

    # 404 et non 405 : aucune route n'est déclarée sur `/pieces/{uid}`, donc
    # django-ninja ne résout pas le chemin du tout — il ne peut pas répondre
    # « méthode non autorisée » pour une ressource qu'il ne connaît pas. Ce qui
    # compte n'est pas le code mais la ligne, qui doit être encore là.
    assert client.delete(f"{PIECES}/{uid}").status_code in (404, 405)
    assert PieceJointe.objects.get(uid=uid).invalide_le is None


# =====================================================================
#  Le journal
# =====================================================================


def test_le_depot_inscrit_l_empreinte_au_journal(connecte, activite):
    """
    C'est elle qui permet, des années plus tard, de dire que le fichier
    téléchargé est bien celui qui a été déposé ce jour-là.
    """
    from noyau.journal.modeles import Evenement

    reponse = _deposer(connecte("focal.dsi"), activite).json()

    evenement = Evenement.objects.filter(type_evenement="piece_versee").latest("id")
    assert evenement.donnees["empreinte"] == reponse["empreinte"]
    # `pieceUid` et non `uid` : c'est la clé que les fiches de vie interrogent
    # pour rattacher une pièce au geste qui l'a versée. Le dépôt générique
    # inscrivait `uid`, et la chronologie ne montrait donc jamais les pièces
    # téléversées par cette route.
    assert evenement.donnees["pieceUid"] == reponse["uid"]


def test_le_retrait_inscrit_son_motif(connecte, activite):
    from noyau.journal.modeles import Evenement

    client = connecte("focal.dsi")
    uid = _deposer(client, activite).json()["uid"]
    client.post(
        f"{PIECES}/{uid}/retrait",
        {"motif": "Document remplacé par la version signée."},
        content_type="application/json",
    )

    evenement = Evenement.objects.filter(type_evenement="piece_retiree").latest("id")
    assert "version signée" in evenement.detail


# =====================================================================
#  Le stockage, isole
# =====================================================================


def test_l_empreinte_ne_consomme_pas_le_flux():
    """
    Le curseur est remis à zéro. Sans cela, l'appelant écrit un fichier déjà
    consommé — donc vide — et aucune erreur ne se produit.
    """
    flux = io.BytesIO(b"contenu")
    empreinte, taille = stockage.empreinte_et_taille(flux)

    assert taille == 7
    assert flux.read() == b"contenu"
    assert len(empreinte) == 64


def test_le_chemin_repartit_sur_deux_niveaux():
    """Un répertoire unique à cent mille fichiers est lent à lister."""
    assert stockage.chemin_de("abcdef0123") == "ab/cd/abcdef0123"


def test_le_stockage_refuse_un_contenu_deguise():
    from noyau.erreurs import ErreurMetier

    flux = io.BytesIO(b"#!/bin/sh\necho attaque")

    with pytest.raises(ErreurMetier) as erreur:
        stockage.verifier_signature(flux, "pdf", "rapport.pdf")

    assert erreur.value.code == "signature_fichier_refusee"
    assert flux.read().startswith(b"#!/bin/sh")


def test_les_types_rattachables_sont_annonces(connecte, activite):
    """Le front les lit plutôt que de les deviner. Un type absent d'ici est
    refusé au dépôt."""
    corps = connecte("focal.dsi").get(f"{PIECES}/types").json()

    # Le courrier est rattachable depuis l'ADR 017 : qui voit le courrier voit
    # ce qui y est joint.
    assert {t["cle"] for t in corps} == {"activite", "courrier", "dossier", "demande"}

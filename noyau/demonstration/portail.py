"""
Le portail des usagers — §3.13.

Trois comptes externes, **sans structure, sans poste, sans perimetre** : la
restriction du portail est « deposant = moi » et rien d'autre (ADR 013). Le
semis s'en sert tel quel ; deposer les demandes avec un compte interne aurait
prouve le contraire de ce que le cloisonnement affirme.

Ce que le jeu montre :

  * des demandes **dans le delai** et des demandes **en retard**, la promesse
    etant figee au depot — un delai raccourci ensuite ne met personne en retard
    retroactivement ;
  * des **complements reclames**, satisfaits ou non : le delai de forclusion du
    §3.13 ne se voit que si quelqu'un ne repond pas ;
  * des **echanges dematerialises** avec les partenaires : marches, conventions,
    reporting reglementaire.

Le service instructeur n'est jamais renseigne : aucune regle d'affectation
n'existe pour les demandes du portail, et en inventer une serait trancher A44.
L'usager lit « en cours d'orientation », ce qui est la verite.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.db import connection

from noyau.identite.modeles import Utilisateur
from portail import services
from portail.modeles import DemandeUsager, EchangeDematerialise, PieceEchange

GRAINE = 20260819

#: Les demandes : (usager, type — le libelle du referentiel ferme, pas un
#: code —, objet, contexte, age en jours, pieces,
#: etat vise).
#:
#: `etat` : `close` — une decision a ete rendue —, `complement` — une piece est
#: reclamee et attendue —, `satisfait` — la piece reclamee est arrivee —,
#: `ouverte` — en instruction ordinaire.
DEMANDES = [
    (
        "usager.sotrapal",
        "Réclamation",
        "Contestation de la facture de stationnement du mois de mai",
        "La facture porte quinze jours de stationnement alors que les conteneurs "
        "ont été enlevés le huitième jour. Les bons de sortie sont joints.",
        86,
        ["bons-de-sortie-mai.pdf"],
        "close",
    ),
    (
        "usager.camtrans",
        "Demande",
        "Demande de communication du barème des redevances domaniales",
        "Nous préparons un dossier d'investissement et avons besoin du barème "
        "applicable aux terre-pleins concédés pour l'exercice en cours.",
        79,
        [],
        "close",
    ),
    (
        "usager.maersk",
        "Autorisation",
        "Autorisation d'accès permanent pour trois agents d'escale",
        "Nos trois agents d'escale interviennent quotidiennement sur les postes "
        "à quai 15 à 18 ; les copies des pièces d'identité sont jointes.",
        71,
        ["pieces-identite-agents.pdf", "attestation-employeur.pdf"],
        "close",
    ),
    (
        "usager.sotrapal",
        "Requête",
        "Requête en révision de la pénalité de retard appliquée en avril",
        "Le retard invoqué résulte d'une immobilisation du navire décidée par "
        "l'autorité portuaire elle-même ; nous demandons la révision.",
        64,
        ["courrier-immobilisation.pdf"],
        "satisfait",
    ),
    (
        "usager.camtrans",
        "Demande",
        "Demande d'ouverture d'un compte de facturation mensuelle",
        "Nous souhaitons passer de la facturation à l'escale à une facturation "
        "mensuelle groupée, comme le permet le règlement d'exploitation.",
        52,
        ["statuts-societe.pdf"],
        "satisfait",
    ),
    (
        "usager.maersk",
        "Réclamation",
        "Réclamation pour avarie constatée sur deux conteneurs frigorifiques",
        "Deux conteneurs frigorifiques ont subi une rupture d'alimentation "
        "électrique sur le terminal ; le constat contradictoire est joint.",
        43,
        ["constat-avarie.pdf"],
        "complement",
    ),
    (
        "usager.sotrapal",
        "Autorisation",
        "Autorisation de travaux de réfection d'un hangar concédé",
        "Les travaux portent sur la toiture et la reprise du dallage ; le plan "
        "et le calendrier prévisionnel sont joints à la présente.",
        37,
        ["plan-hangar.pdf"],
        "complement",
    ),
    (
        "usager.camtrans",
        "Demande",
        "Demande d'agrément comme prestataire de transport intérieur",
        "Notre société souhaite obtenir l'agrément lui permettant d'assurer le "
        "transport des marchandises entre le port et les entrepôts sous douane.",
        29,
        ["dossier-agrement.pdf", "attestation-fiscale.pdf"],
        "complement",
    ),
    (
        "usager.maersk",
        "Demande",
        "Demande de communication des statistiques de temps de séjour",
        "Nous préparons notre plan d'escale pour le prochain trimestre et "
        "souhaitons disposer des statistiques de séjour des six derniers mois.",
        21,
        [],
        "ouverte",
    ),
    (
        "usager.sotrapal",
        "Requête",
        "Requête en restitution du dépôt de garantie du hangar 7",
        "Le hangar a été restitué le mois dernier après état des lieux "
        "contradictoire ; nous sollicitons la restitution du dépôt de garantie.",
        14,
        ["etat-des-lieux.pdf"],
        "ouverte",
    ),
    (
        "usager.camtrans",
        "Réclamation",
        "Réclamation sur le refus d'accès au terminal du 12 août",
        "Nos camions se sont vu refuser l'accès malgré des badges valides ; "
        "l'immobilisation a duré près de six heures.",
        7,
        [],
        "ouverte",
    ),
    (
        "usager.maersk",
        "Autorisation",
        "Autorisation de soutage à quai pour le mois prochain",
        "Nous prévoyons quatre opérations de soutage à quai et sollicitons "
        "l'autorisation correspondante, avec le plan de prévention joint.",
        3,
        ["plan-prevention.pdf"],
        "ouverte",
    ),
    (
        "usager.sotrapal",
        "Demande",
        "Demande de rendez-vous avec la Direction de l'exploitation",
        "Nous souhaitons présenter notre projet d'extension des capacités de "
        "stockage et en discuter les implications d'exploitation.",
        1,
        [],
        "ouverte",
    ),
]

#: Ce que l'institution reclame, pour les demandes en attente de complement :
#: (rang de la demande, objet, jours restants avant forclusion).
COMPLEMENTS = [
    (3, "Copie du courrier d'immobilisation signé de l'autorité portuaire", 12),
    (4, "Attestation bancaire de domiciliation du compte", 20),
    (5, "Rapport d'expertise contradictoire sur les deux conteneurs", 9),
    (6, "Attestation d'assurance décennale de l'entreprise de travaux", 15),
    (7, "Attestation de conformité fiscale de moins de trois mois", 5),
]

#: Ce que l'usager repond, quand il repond : (rang, texte, piece deposee).
#:
#: Une piece est **exigee** pour satisfaire un complement : « je vous l'envoie
#: demain » ne le satisfait pas, et le semis reproduit les deux cas.
REPONSES = [
    (3, "Vous trouverez ci-joint le courrier d'immobilisation signé.", "immobilisation.pdf"),
    (4, "L'attestation bancaire demandée est jointe à ce message.", "attestation-bancaire.pdf"),
    (5, "L'expertise est en cours, le rapport vous parviendra sous huitaine.", None),
    (8, "Nous restons à votre disposition pour tout élément complémentaire.", None),
]

#: Les decisions rendues, pour les demandes closes : (rang, decision).
DECISIONS = [
    (
        0,
        "Facture rectifiée : sept jours de stationnement retenus au lieu de quinze. "
        "Un avoir a été émis.",
    ),
    (1, "Barème communiqué par courrier électronique le jour de l'instruction."),
    (
        2,
        "Autorisation d'accès permanent délivrée pour trois agents, valable "
        "jusqu'au 31 décembre de l'exercice en cours.",
    ),
]

#: Les echanges dematerialises avec les partenaires — §3.13 :
#: (reference, intitule, nature, **compte** du partenaire, age d'ouverture,
#: delai, pieces attendues, pieces deposees, clos).
#:
#: Le partenaire est un compte du portail et non une ligne du referentiel des
#: correspondants : c'est lui qui se connecte pour deposer. Les trois comptes
#: externes suffisent — un quatrieme partenaire supposerait un quatrieme compte,
#: et le semis n'en cree pas a la volee.
ECHANGES = [
    (
        "MP-2026-014",
        "Marché de fourniture de deux remorqueurs portuaires",
        "marche",
        "usager.sotrapal",
        75,
        90,
        6,
        6,
        True,
    ),
    (
        "CV-2026-007",
        "Convention d'occupation du terre-plein nord",
        "convention",
        "usager.maersk",
        58,
        60,
        4,
        4,
        True,
    ),
    (
        "MP-2026-021",
        "Marché de dragage d'entretien du chenal d'accès",
        "marche",
        "usager.sotrapal",
        42,
        75,
        8,
        5,
        False,
    ),
    (
        "RR-2026-003",
        "Reporting réglementaire trimestriel — statistiques de trafic",
        "reporting",
        "usager.camtrans",
        30,
        45,
        3,
        3,
        False,
    ),
    (
        "CV-2026-011",
        "Convention de partenariat pour la formation des dockers",
        "convention",
        "usager.camtrans",
        18,
        60,
        5,
        2,
        False,
    ),
    (
        "MP-2026-029",
        "Marché de fourniture d'équipements de protection individuelle",
        "marche",
        "usager.maersk",
        6,
        30,
        4,
        0,
        False,
    ),
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose les demandes des usagers, puis les echanges dematerialises."""
    if DemandeUsager.objects.exists():
        ecrire(f"  {DemandeUsager.objects.count()} demandes deja en base — passe")
        return 0

    tirage = random.Random(GRAINE)
    posees = _demandes(annuaire, tirage, ecrire)
    _echanges(annuaire, ecrire)
    return posees


def _demandes(annuaire: dict, tirage: random.Random, ecrire) -> int:
    att = annuaire["att.dsr"]
    demandes: list[DemandeUsager] = []

    for usager, type_demande, objet, contexte, age, pieces, _etat in DEMANDES:
        demande = services.deposer_demande(
            annuaire[usager],
            type_demande=type_demande,
            objet=objet,
            contexte=contexte,
            pieces=[{"nom": nom, "taille": f"{tirage.randrange(2, 40) / 10} Mo"} for nom in pieces],
        )
        _retrodater(demande, age)
        demandes.append(demande)

    for rang, objet, jours in COMPLEMENTS:
        if rang < len(demandes):
            services.reclamer_complement(
                att,
                demande_id=demandes[rang].pk,
                objet=objet,
                avant_le=date.today() + timedelta(days=jours),
            )

    for rang, texte, piece in REPONSES:
        if rang >= len(demandes):
            continue
        services.repondre(
            annuaire[DEMANDES[rang][0]],
            demande_id=demandes[rang].pk,
            texte=texte,
            pieces=[{"nom": piece, "taille": "1.1 Mo"}] if piece else None,
        )

    _clore(demandes, annuaire, ecrire)
    ecrire(f"  {len(demandes)} demandes d'usagers, {len(COMPLEMENTS)} complements reclames")
    return len(demandes)


def _retrodater(demande: DemandeUsager, age: int) -> None:
    """
    Recule le depot **et la promesse avec lui**.

    La date de reponse promise est figee au depot : la recalculer a partir de la
    date reculee aurait donne une seconde promesse, differente de celle que
    l'usager a lue sur son accuse de reception.
    """
    if age <= 0:
        return
    from noyau.demonstration.courriers import _horodatage

    horodatage = _horodatage(date.today() - timedelta(days=age))
    with connection.cursor() as curseur:
        curseur.execute(
            """
            UPDATE demande_usager
               SET deposee_le          = deposee_le          - %s * INTERVAL '1 day',
                   reponse_attendue_le = reponse_attendue_le - %s * INTERVAL '1 day',
                   cree_le             = %s
             WHERE id = %s
            """,
            [age, age, horodatage, demande.pk],
        )
        curseur.execute(
            """
            UPDATE evenement SET survenu_le = %s
             WHERE objet_type = 'demande_usager' AND objet_id = %s
            """,
            [horodatage, demande.pk],
        )
        curseur.execute(
            "UPDATE piece_demande SET deposee_le = deposee_le - %s * INTERVAL '1 day' "
            "WHERE demande_id = %s",
            [age, demande.pk],
        )


def _clore(demandes: list[DemandeUsager], annuaire: dict, ecrire) -> None:
    """
    Rend la decision et clot la demande — **en SQL, faute de service**.

    Le portail sait deposer, repondre et reclamer ; **rien n'y clot une
    demande**. Une demande jamais close reste en attente indefiniment, et
    l'ecran de suivi de l'usager n'aurait jamais montre ce que vaut une
    reponse. Voir A66 : c'est la meme lacune que pour l'activite realisee, le
    dossier qui avance et la decision executee.
    """
    for rang, decision in DECISIONS:
        if rang >= len(demandes):
            continue
        demande = demandes[rang]
        jour = date.today() - timedelta(days=max(1, DEMANDES[rang][4] // 4))
        with connection.cursor() as curseur:
            curseur.execute(
                """
                UPDATE demande_usager
                   SET decision = %s, decision_le = %s, clos_le = %s, modifie_par = %s
                 WHERE id = %s
                """,
                [decision, jour, jour, annuaire["att.dsr"].pk, demande.pk],
            )
    ecrire(f"  {len(DECISIONS)} demandes closes par une decision")


def _echanges(annuaire: dict, ecrire) -> None:
    """
    Les echanges dematerialises et leurs pieces.

    Aucun service ne les ecrit : l'ecran est en lecture seule, et le depot
    reel des pieces passera par `POST /api/pieces` (ADR 017). Les lignes sont
    donc posees par l'ORM — un echange est un contenant, il ne porte aucune
    regle metier que le semis pourrait contourner.
    """
    archiviste = annuaire["archiviste"]

    for reference, intitule, nature, compte, age, delai, attendus, deposees, clos in ECHANGES:
        partenaire = annuaire.get(compte)
        if partenaire is None:
            continue
        ouvert = date.today() - timedelta(days=age)
        echange = EchangeDematerialise.objects.create(
            reference=reference,
            intitule=intitule,
            nature=nature,
            partenaire=partenaire,
            ouvert_le=ouvert,
            echeance=ouvert + timedelta(days=delai),
            attendus=attendus,
            clos_le=ouvert + timedelta(days=delai - 5) if clos else None,
        )
        for rang in range(deposees):
            PieceEchange.objects.create(
                echange=echange,
                nom=f"{reference}-piece-{rang + 1}.pdf",
                taille=f"{(rang + 3) * 4 / 10:.1f} Mo",
                deposee_le=ouvert + timedelta(days=rang * 3),
                depose_par=archiviste,
            )
    ecrire(f"  {len(ECHANGES)} echanges dematerialises")

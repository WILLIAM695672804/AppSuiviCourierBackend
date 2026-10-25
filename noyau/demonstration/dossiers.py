"""
Les dossiers a instruire — §3.6 et §3.7.

Le pilier n'expose que **cinq gestes** : ouvrir, demander un complement,
enregistrer sa reception, retourner a une etape anterieure, fusionner un
courrier-type. Rien n'y fait *avancer* un dossier d'une etape a la suivante, et
rien n'y nomme d'instructeur : `services.ouvrir` laisse deliberement
`instructeur = None`, parce que la regle designe une structure et non une
personne.

Le semis ecrit donc l'etape et l'instructeur **en SQL**, en connaissance de
cause. Sans cela, les vingt-deux dossiers seraient tous en qualification, sans
instructeur, et les quatre colonnes du registre — qualification, instruction,
validation, notification — se resumeraient a une seule. La lacune est ouverte
en A66 ; le semis la contourne, il ne la tranche pas.

Les regles d'affectation, elles, passent par le referentiel : sans regle, la
fiche d'instruction affiche « aucune regle ne couvre ce dossier » sur toutes
les lignes, ce qui est exact et n'apprend rien. Quatre regles suffisent a
montrer la mecanique du plus specifique l'emporte (RF-BPM-02).
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.db import connection

from dossier import services
from dossier.modeles import Dossier, RegleAffectation
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure

GRAINE = 20260819

#: (libelle, type, criticite, montant minimum, code structure, priorite)
#:
#: La derniere n'a aucun critere : c'est la regle par defaut, celle qui
#: s'applique quand aucune autre ne couvre le dossier.
REGLES = [
    (
        "Les réclamations sont instruites par la Direction des affaires juridiques.",
        "reclamation",
        None,
        None,
        "DAJ",
        20,
    ),
    (
        "Les autorisations d'occupation du domaine portuaire relèvent de la Direction "
        "du domaine et de la logistique maritime.",
        "autorisation",
        None,
        None,
        "DDLM",
        20,
    ),
    (
        "Au-delà de 50 millions de francs, le dossier passe par la Direction financière "
        "et comptable.",
        None,
        None,
        50_000_000,
        "DFC",
        10,
    ),
    (
        "Les dossiers urgents sont instruits par la Direction des affaires "
        "juridiques, saisine immédiate.",
        None,
        "urgent",
        None,
        "DAJ",
        5,
    ),
]

#: Les dossiers.
#:
#: (ouvreur, type, objet, demandeur, criticite, montant, age en jours,
#:  delai d'instruction, etape atteinte, instructeur ou `None`)
#:
#: L'age et le delai font le retard : un dossier de 60 jours avec 30 jours de
#: delai est en retard, et c'est ainsi que le compteur rouge du registre se
#: remplit — jamais en forcant un etat.
DOSSIERS = [
    # --- Clos ------------------------------------------------------------
    (
        "agent.daj",
        "reclamation",
        "Réclamation sur la facturation des surestaries de mars",
        "CAMTRANS Logistique",
        "standard",
        12_400_000,
        96,
        30,
        "clos",
        "agent.daj",
    ),
    (
        "agent.daj",
        "demande",
        "Demande de communication du règlement d'exploitation",
        "Groupement des Transitaires du Littoral",
        "standard",
        None,
        88,
        30,
        "clos",
        "agent.daj",
    ),
    (
        "agent.dfc",
        "demande",
        "Demande d'étalement de la dette de redevances domaniales",
        "SOTRAPAL SA",
        "sensible",
        84_000_000,
        80,
        45,
        "clos",
        "agent.dfc",
    ),
    (
        "agent.daj",
        "autorisation",
        "Autorisation d'occupation temporaire du terre-plein sud",
        "Entreprise BATIPORT",
        "standard",
        None,
        74,
        30,
        "clos",
        "chef.ddlm",
    ),
    (
        "agent.dfc",
        "requete",
        "Requête en restitution de caution de soumission",
        "Cabinet NGUELE & Associés",
        "standard",
        5_000_000,
        70,
        30,
        "clos",
        "agent.dfc",
    ),
    (
        "agent.daj",
        "acte",
        "Projet de convention d'occupation du magasin cale 12",
        "Douala International Terminal",
        "sensible",
        320_000_000,
        66,
        45,
        "clos",
        "agent.dfc",
    ),
    # --- Notification -----------------------------------------------------
    (
        "agent.daj",
        "reclamation",
        "Contestation de l'application du tarif conteneur frigorifique",
        "Maersk Cameroun",
        "standard",
        8_900_000,
        52,
        30,
        "notification",
        "agent.daj",
    ),
    (
        "agent.dfc",
        "demande",
        "Demande de remise gracieuse de pénalités de retard",
        "Établissements MBALLA & Fils",
        "standard",
        3_200_000,
        47,
        30,
        "notification",
        "agent.dfc",
    ),
    # --- Validation --------------------------------------------------------
    (
        "agent.daj",
        "acte",
        "Renouvellement de la convention de manutention conventionnelle",
        "Bolloré Transport & Logistics",
        "sensible",
        780_000_000,
        44,
        45,
        "validation",
        "agent.dfc",
    ),
    (
        "agent.daj",
        "autorisation",
        "Autorisation d'installation d'un poste de soutage",
        "SOTRAPAL SA",
        "standard",
        None,
        38,
        30,
        "validation",
        "chef.ddlm",
    ),
    (
        "agent.dfc",
        "requete",
        "Requête en révision du barème de stationnement des camions",
        "Syndicat des Dockers du Port",
        "sensible",
        None,
        35,
        45,
        "validation",
        "agent.daj",
    ),
    # --- Instruction --------------------------------------------------------
    (
        "agent.daj",
        "reclamation",
        "Réclamation pour avarie sur marchandise en zone sous douane",
        "Cameroon Shipping Lines",
        "urgent",
        45_000_000,
        33,
        15,
        "instruction",
        "agent.daj",
    ),
    (
        "agent.dfc",
        "demande",
        "Demande de raccordement électrique du quai 51",
        "Douala International Terminal",
        "standard",
        62_000_000,
        27,
        30,
        "instruction",
        "agent.dfc",
    ),
    (
        "agent.daj",
        "autorisation",
        "Autorisation de travaux de dragage aux abords du quai 41",
        "Entreprise BATIPORT",
        "sensible",
        210_000_000,
        24,
        45,
        "instruction",
        "chef.ddlm",
    ),
    (
        "agent.daj",
        "reclamation",
        "Réclamation des riverains sur les nuisances nocturnes",
        "Association des Riverains de Bonabéri",
        "standard",
        None,
        21,
        30,
        "instruction",
        "agent.daj",
    ),
    (
        "agent.dfc",
        "acte",
        "Avenant au contrat de fourniture de carburant",
        "SOTRAPAL SA",
        "standard",
        96_000_000,
        18,
        30,
        "instruction",
        "agent.dfc",
    ),
    (
        "agent.daj",
        "requete",
        "Requête en indemnisation après immobilisation d'un navire",
        "Maersk Cameroun",
        "urgent",
        150_000_000,
        16,
        15,
        "instruction",
        "agent.daj",
    ),
    # --- Qualification -------------------------------------------------------
    (
        "agent.daj",
        "demande",
        "Demande d'agrément comme prestataire de collecte de déchets",
        "COOP-PECHE Littoral",
        "standard",
        None,
        9,
        30,
        "qualification",
        None,
    ),
    (
        "agent.dfc",
        "demande",
        "Demande de compensation des créances croisées",
        "CAMTRANS Logistique",
        "standard",
        41_000_000,
        6,
        30,
        "qualification",
        None,
    ),
    (
        "agent.daj",
        "reclamation",
        "Réclamation sur le refus d'accès au terminal à conteneurs",
        "Groupement des Transitaires du Littoral",
        "urgent",
        None,
        4,
        15,
        "qualification",
        None,
    ),
    (
        "agent.daj",
        "autorisation",
        "Autorisation de survol par drone pour levé topographique",
        "Cabinet NGUELE & Associés",
        "standard",
        None,
        2,
        30,
        "qualification",
        None,
    ),
    (
        "agent.dfc",
        "acte",
        "Protocole d'accord transactionnel avec un manutentionnaire",
        "Bolloré Transport & Logistics",
        "sensible",
        540_000_000,
        1,
        45,
        "qualification",
        None,
    ),
]

#: Les complements reclames, par rang de dossier : (rang, objet, age de la
#: demande, recu).
#:
#: Un complement demande et jamais recu est le cas qui compte : c'est lui qui
#: alimente « en attente de complement », et l'echeance du dossier **ne bouge
#: pas** pour autant (§3.7).
COMPLEMENTS = [
    (0, "Copie des connaissements des trois expéditions contestées", 90, True),
    (2, "Échéancier signé et attestation de garantie bancaire", 76, True),
    (8, "Attestation de conformité fiscale de moins de trois mois", 40, True),
    (11, "Constat d'avarie contradictoire signé des deux parties", 30, False),
    (13, "Étude d'impact hydro-sédimentaire", 20, False),
    (16, "Rapport d'expertise sur l'immobilisation du navire", 14, False),
    (18, "États financiers certifiés des deux derniers exercices", 5, False),
]

#: Les retours a une etape anterieure — RF-BPM-06. Un registre sans aucun
#: retour laisse croire que le circuit ne va que dans un sens.
RETOURS = [
    (
        8,
        "instruction",
        "Le projet de convention ne reprend pas la clause de révision tarifaire "
        "annuelle exigée par la Direction générale.",
    ),
    (
        6,
        "instruction",
        "Le projet de réponse ne répond pas au grief tarifaire soulevé par le réclamant.",
    ),
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose les regles d'affectation, puis les dossiers. Rend leur nombre."""
    deja = Dossier.objects.count()
    if deja:
        ecrire(f"  {deja} dossiers deja en base — passe")
        return 0

    _regles(ecrire)
    tirage = random.Random(GRAINE)
    courriers = _courriers_d_origine()

    poses: list[Dossier] = []
    for rang, fiche in enumerate(DOSSIERS):
        poses.append(_ouvrir(fiche, annuaire, courriers, rang, tirage))

    _reclamer(poses, annuaire)
    _retourner(poses, annuaire)

    ecrire(f"  {len(poses)} dossiers, {len(COMPLEMENTS)} complements")
    return len(poses)


def _regles(ecrire) -> None:
    """
    Le referentiel des regles. `get_or_create` : la table n'est pas videe par
    la remise a zero, c'est un referentiel et non un fait.
    """
    structures = {s.code: s for s in Structure.objects.filter(valide_au__isnull=True)}
    for libelle, type_dossier, criticite, seuil, code, priorite in REGLES:
        structure = structures.get(code)
        if structure is None:
            continue
        _, cree = RegleAffectation.objects.get_or_create(
            libelle=libelle,
            defaults={
                "type_dossier": type_dossier,
                "criticite": criticite,
                "montant_minimum": seuil,
                "structure": structure,
                "priorite": priorite,
            },
        )
        if cree:
            ecrire(f"  regle d'affectation vers {code}")


def _courriers_d_origine() -> list:
    """
    Les courriers dont un dossier peut naitre — §3.6.

    Un dossier sur trois environ en cite un : le depot direct existe aussi, et
    un registre ou tous les dossiers viendraient d'un courrier laisserait croire
    que la saisie directe n'est pas prevue.
    """
    from courrier.modeles import Courrier

    return list(Courrier.objects.order_by("id").values_list("id", "numero")[:40])


def _ouvrir(fiche, annuaire: dict, courriers: list, rang: int, tirage) -> Dossier:
    (
        ouvreur,
        type_dossier,
        objet,
        demandeur,
        criticite,
        montant,
        age,
        delai,
        etape,
        instructeur,
    ) = fiche

    origine = courriers[rang % len(courriers)] if courriers and rang % 3 == 0 else None

    dossier = services.ouvrir(
        annuaire[ouvreur],
        type_dossier=type_dossier,
        objet=objet,
        demandeur=demandeur,
        # L'echeance est saisie a partir d'aujourd'hui : `ouvrir` refuse une
        # echeance passee. Le recul se fait juste apres, sur les deux dates a
        # la fois, ce qui preserve le delai accorde.
        echeance=(date.today() + timedelta(days=delai)).isoformat(),
        contexte=_contexte(type_dossier, tirage),
        criticite=criticite,
        montant=montant,
        courrier_id=origine[0] if origine else None,
        courrier_reference=origine[1] if origine else "",
    )

    _retrodater(dossier, age)
    _poser_etape(dossier, etape, annuaire.get(instructeur), age)
    dossier.refresh_from_db()
    return dossier


#: Le contexte que l'agent de guichet ecrit en ouvrant le dossier. Une colonne
#: toujours vide se lit comme une colonne inutile.
CONTEXTES = {
    "reclamation": [
        "Réclamation reçue au guichet, pièces jointes au dépôt.",
        "Le demandeur conteste le montant et demande un réexamen contradictoire.",
    ],
    "demande": [
        "Demande formulée par courrier, transmise après cotation.",
        "Le demandeur sollicite une réponse écrite avant la fin du mois.",
    ],
    "autorisation": [
        "Le site concerné relève du domaine portuaire concédé.",
        "Avis technique de l'exploitation à recueillir avant décision.",
    ],
    "requete": [
        "Requête déposée par conseil, accusé de réception délivré.",
        "Le demandeur invoque un préjudice chiffré, pièces à vérifier.",
    ],
    "acte": [
        "Projet d'acte soumis au visa juridique avant signature.",
        "Négociation engagée, le projet reprend les termes convenus en séance.",
    ],
}


def _contexte(type_dossier: str, tirage: random.Random) -> str:
    return tirage.choice(CONTEXTES.get(type_dossier) or CONTEXTES["demande"])


def _retrodater(dossier: Dossier, age: int) -> None:
    """
    Recule l'ouverture et l'echeance **du meme nombre de jours**.

    Recalculer l'echeance a partir de la date reculee aurait donne un second
    delai, different de celui que `ouvrir` a inscrit : deux verites pour le
    meme dossier.
    """
    if age <= 0:
        return
    from noyau.demonstration.courriers import _horodatage

    horodatage = _horodatage(date.today() - timedelta(days=age))
    with connection.cursor() as curseur:
        curseur.execute(
            """
            UPDATE dossier
               SET ouvert_le = ouvert_le - %s * INTERVAL '1 day',
                   echeance  = echeance  - %s * INTERVAL '1 day',
                   cree_le   = %s
             WHERE id = %s
            """,
            [age, age, horodatage, dossier.pk],
        )
        curseur.execute(
            "UPDATE evenement SET survenu_le = %s WHERE objet_type = 'dossier' AND objet_id = %s",
            [horodatage, dossier.pk],
        )


def _poser_etape(dossier: Dossier, etape: str, instructeur, age: int) -> None:
    """
    Pose l'etape atteinte et l'instructeur nomme — **en SQL, faute de service**.

    Le pilier ne sait faire remonter un dossier (`retourner`), jamais le faire
    avancer, et ne nomme aucun instructeur. Ecrire ces deux colonnes ici est le
    seul moyen de montrer un registre a quatre colonnes ; le faire dans
    `services.py` reviendrait a inventer le geste que A66 pose comme question.

    La cloture porte sa date, sinon la contrainte `dossier_cloture_coherente`
    refuse la ligne — et elle a raison : la file de versement se lit sur
    `clos_le`.
    """
    if etape == "qualification" and instructeur is None:
        return

    clos_le = date.today() - timedelta(days=max(1, age // 6)) if etape == "clos" else None
    with connection.cursor() as curseur:
        curseur.execute(
            "UPDATE dossier SET etape = %s, instructeur_id = %s, clos_le = %s WHERE id = %s",
            [etape, instructeur.pk if instructeur else None, clos_le, dossier.pk],
        )


def _reclamer(poses: list[Dossier], annuaire: dict) -> None:
    """
    Les complements reclames au demandeur — §3.7.

    L'acteur est la DSR : son perimetre porte sur tout, et `_dossier_ouvrable`
    borne l'ecriture au perimetre comme la lecture. Un instructeur de la DAJ
    n'aurait pas vu les dossiers de la DFC.
    """
    dsr = annuaire["dsr"]
    for rang, objet, age, recu in COMPLEMENTS:
        if rang >= len(poses):
            continue
        dossier = poses[rang]
        if dossier.etape == "clos":
            # Un dossier clos ne se reclame plus : `_dossier_ouvrable` refuse.
            continue
        complement = services.demander_complement(
            dsr,
            dossier_id=dossier.pk,
            objet=objet,
            echeance=(date.today() + timedelta(days=15)).isoformat(),
        )
        if recu:
            services.enregistrer_complement(dsr, dossier_id=dossier.pk, complement_id=complement.pk)
        _retrodater_complement(complement.pk, age)


def _retrodater_complement(complement_id: int, age: int) -> None:
    with connection.cursor() as curseur:
        curseur.execute(
            """
            UPDATE complement_dossier
               SET demande_le = demande_le - %s * INTERVAL '1 day',
                   echeance   = echeance   - %s * INTERVAL '1 day',
                   recu_le    = CASE WHEN recu_le IS NULL THEN NULL
                                     ELSE recu_le - %s * INTERVAL '1 day' END
             WHERE id = %s
            """,
            [age, age, max(0, age - 8), complement_id],
        )


def _retourner(poses: list[Dossier], annuaire: dict) -> None:
    """RF-BPM-06. Le motif est obligatoire, et court n'est pas un motif."""
    dsr = annuaire["dsr"]
    for rang, cible, motif in RETOURS:
        if rang >= len(poses):
            continue
        dossier = poses[rang]
        if dossier.etape in ("clos", "qualification"):
            continue
        services.retourner(dsr, dossier_id=dossier.pk, etape_cible=cible, motif=motif)

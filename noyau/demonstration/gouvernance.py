"""
Les instances, leurs decisions, et ce qui empeche d'y sieger — §3.3, §17, §19.

Quatre registres tiennent dans ce module, parce qu'ils se citent l'un l'autre :

  * les **seances** et leur ordre du jour, avec les documents deposes — a
    l'heure ou hors delai, c'est ce que l'ecran de ponctualite montre ;
  * les **decisions** (ADR 006 : decision d'instance, prescription de filiale
    et recommandation externe sont un seul objet), les structures qu'elles
    chargent, leurs jalons, leurs avancements et les relances de la DSR ;
  * les **absences** et le planning des **conges**, qui disent pourquoi un
    directeur convoque n'etait pas la ;
  * les **entites exterieures** et les **representations**, l'aval du §3.3.

Comme ailleurs, aucun geste du pilier ne **prononce l'execution** d'une
decision : `execute_le` n'est ecrit par aucun service. Le semis le pose en SQL,
et la question est ouverte en A66 — la meme que pour l'activite realisee et le
dossier qui avance.

Les jalons et les participants n'ont pas de service non plus : aucun ecran ne
les saisit. Ils sont poses par l'ORM, ce qui reste honnete tant qu'aucune regle
metier ne pese sur eux — un jalon est une ligne d'echeance, pas une decision.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace

from django.db import connection

from gouvernance import services
from gouvernance.modeles import (
    CongeDroit,
    CongePeriode,
    Engagement,
    EngagementJalon,
    EntiteExterne,
    OrganeGestion,
    OrganisationExterne,
    Representation,
    Seance,
    SeanceParticipant,
)
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur

GRAINE = 20260819

#: Les seances : (type, intitule, jours par rapport a aujourd'hui, president,
#: code structure organisatrice, points de l'ordre du jour, documents deposes).
#:
#: Les jours negatifs sont passes, les positifs a venir. Les deux sont
#: indispensables : le registre sert autant a preparer qu'a rendre compte, et un
#: registre sans seance a venir ouvre l'ecran de preparation sur le vide.
#:
#: `documents` : (nature, libelle, jours de depot par rapport a la seance). Un
#: depot posterieur a l'echeance est **hors delai**, et c'est ce que la fiche
#: signale — d'ou un depot tardif volontaire.
SEANCES = [
    (
        "CODIR",
        "Comité de direction du mois de mai",
        -104,
        "dg",
        "DG",
        [
            ("Exécution du plan d'actions au premier trimestre", "dcg"),
            ("Situation du recouvrement des créances", "dir.dfc"),
            ("Point sur le temps de séjour des conteneurs", "dir.dexp"),
        ],
        [
            ("Ordre du jour", "Ordre du jour du CODIR de mai", -7),
            ("Compte rendu", "Compte rendu du CODIR de mai", 4),
        ],
    ),
    (
        "Session du Conseil d'administration",
        "Première session ordinaire du Conseil d'administration",
        -88,
        "dg",
        "DG",
        [
            ("Approbation des comptes de l'exercice 2025", "dir.dfc"),
            ("Rapport d'activité 2025", "dsr"),
            ("Programme d'investissement 2026", "dir.dexp"),
        ],
        [
            ("Ordre du jour", "Ordre du jour de la session", -12),
            ("Procès-verbal", "Procès-verbal de la première session ordinaire", 18),
        ],
    ),
    (
        "CODIR",
        "Comité de direction du mois de juin",
        -72,
        "dg",
        "DG",
        [
            ("Suivi des décisions du CODIR de mai", "dsr"),
            ("Plan de formation : point d'étape", "dir.drh"),
            ("Sécurisation du système d'information", "dir.dsi"),
        ],
        [
            ("Ordre du jour", "Ordre du jour du CODIR de juin", -6),
            ("Compte rendu", "Compte rendu du CODIR de juin", 9),
        ],
    ),
    (
        "Réunion présidée par le DG",
        "Réunion de coordination sur le dragage du chenal",
        -55,
        "dg",
        "DG",
        [
            ("État d'avancement du marché de dragage", "dir.dexp"),
            ("Financement et avis de non-objection du bailleur", "dir.dfc"),
        ],
        [
            ("Compte rendu", "Relevé de conclusions de la réunion de coordination", 3),
        ],
    ),
    (
        "CODIR",
        "Comité de direction du mois de juillet",
        -40,
        "dg",
        "DG",
        [
            ("Exécution budgétaire au premier semestre", "dir.dfc"),
            ("Dossiers contentieux en cours", "dir.daj"),
            ("Préparation du budget 2027", "dir.dfc"),
        ],
        [
            ("Ordre du jour", "Ordre du jour du CODIR de juillet", -5),
            # Depose apres l'echeance : c'est le cas que l'ecran doit signaler.
            ("Compte rendu", "Compte rendu du CODIR de juillet", 21),
        ],
    ),
    (
        "Rapport d'activité",
        "Présentation du rapport d'activité du premier semestre",
        -21,
        "dsr",
        "DSR",
        [
            ("Rapport consolidé du premier semestre", "dsr"),
            ("Suites données aux recommandations de l'audit", "auditeur"),
        ],
        [
            ("Ordre du jour", "Ordre du jour de la présentation", -4),
        ],
    ),
    (
        "CODIR",
        "Comité de direction du mois d'août",
        6,
        "dg",
        "DG",
        [
            ("Suivi des décisions non exécutées", "dsr"),
            ("Situation des effectifs et plan de recrutement", "dir.drh"),
            ("Avancement de la plateforme de suivi des courriers", "dir.dsi"),
        ],
        [
            ("Ordre du jour", "Ordre du jour du CODIR d'août", -3),
        ],
    ),
    (
        "Session du Conseil d'administration",
        "Deuxième session ordinaire du Conseil d'administration",
        27,
        "dg",
        "DG",
        [
            ("Budget prévisionnel 2027", "dir.dfc"),
            ("Rapport d'activité du premier semestre", "dsr"),
        ],
        [],
    ),
]

#: Les decisions consignees : (instance, objet, jours ecoules depuis la
#: decision, delai d'execution en jours, codes des structures chargees — la
#: premiere pilote —, avancement declare par le pilote, etat vise).
#:
#: `etat` : `execute`, `retard`, `en_cours`, `a_lancer`, `suspendu`. Il n'est
#: jamais force : l'echeance et l'avancement le produisent, sauf l'execution et
#: la suspension, qui n'ont aucun geste pour les prononcer (A66).
DECISIONS = [
    (
        "CODIR",
        "Ramener le délai moyen de traitement du courrier sous dix jours ouvrés.",
        104,
        60,
        ["DSI", "SCC"],
        100,
        "execute",
    ),
    (
        "Conseil d'administration",
        "Approuver le programme d'investissement 2026 et en confier l'exécution "
        "à la Direction de l'exploitation.",
        88,
        180,
        ["DEXP", "DFC"],
        65,
        "en_cours",
    ),
    (
        "Conseil d'administration",
        "Ramener l'encours des créances antérieures à 2025 sous deux milliards "
        "de francs avant la fin de l'exercice.",
        88,
        150,
        ["DFC", "DAJ"],
        47,
        "en_cours",
    ),
    (
        "CODIR",
        "Produire un état mensuel du temps de séjour des conteneurs, "
        "diffusé avant le 10 de chaque mois.",
        72,
        30,
        ["DEXP", "DCG"],
        100,
        "execute",
    ),
    (
        "CODIR",
        "Adopter une politique de sécurité du système d'information "
        "et la faire approuver par le CODIR.",
        72,
        45,
        ["DSI"],
        70,
        "retard",
    ),
    (
        "Directeur général",
        "Établir la liste nominative des dix premiers débiteurs du Port "
        "et le montant de leur dette.",
        62,
        15,
        ["DFC"],
        100,
        "execute",
    ),
    (
        "Directeur général",
        "Suspendre les travaux de dragage jusqu'à l'avis de non-objection du bailleur de fonds.",
        55,
        90,
        ["DEXP", "DFC"],
        30,
        "suspendu",
    ),
    (
        "CODIR",
        "Doter chaque poste d'une fiche de fonction avant la fin de l'exercice.",
        40,
        140,
        ["DRH"],
        55,
        "en_cours",
    ),
    (
        "CODIR",
        "Régler les contentieux d'avarie antérieurs à 2024 par voie transactionnelle.",
        40,
        60,
        ["DAJ", "DFC"],
        35,
        "retard",
    ),
    (
        "CODIR",
        "Présenter au prochain comité un plan de réduction des charges de "
        "fonctionnement de dix pour cent.",
        21,
        45,
        ["DFC", "DAG"],
        20,
        "en_cours",
    ),
    (
        "Directeur général",
        "Mettre en service les installations de réception des déchets d'exploitation.",
        21,
        75,
        ["DEXP", "DDLM"],
        0,
        "a_lancer",
    ),
    (
        "CODIR",
        "Consolider les tableaux de bord des directions dans un tableau de bord "
        "unique de la Direction générale.",
        12,
        60,
        ["DCG", "DSI"],
        0,
        "a_lancer",
    ),
]

#: Les jalons, par rang de decision : (rang, libelle, part du delai, fait).
#:
#: Un jalon echu et non fait est le signal qui distingue « prend du retard » de
#: « oublie » — la vue `v_engagement_etat` le remonte a part.
JALONS = [
    (1, "Notification des marchés d'investissement", 0.3, True),
    (1, "Réception des premiers équipements", 0.7, False),
    (2, "Mise en demeure des dix premiers débiteurs", 0.2, True),
    (2, "Signature des échéanciers négociés", 0.6, False),
    (4, "Rédaction du projet de politique", 0.5, True),
    (4, "Adoption en comité de direction", 0.9, False),
    (8, "Inventaire des dossiers d'avarie", 0.3, True),
    (8, "Premières transactions signées", 0.8, False),
    (9, "Cartographie des charges par nature", 0.4, False),
]

#: Les relances de la DSR, par rang de decision.
RELANCES = [
    (4, "La politique de sécurité était attendue au 30 juin. Où en est le projet ?"),
    (8, "Deuxième relance : aucune transaction signée à ce jour."),
    (8, "Le CODIR d'août demandera un point précis sur ce dossier."),
    (10, "Rien n'est engagé un mois après la décision. Merci d'indiquer un calendrier."),
]

#: Les absences declarees : (responsable, type, debut relatif, duree,
#: interimaire ou `None`).
#:
#: Une absence **sans interimaire** est le cas que la DSR doit voir : c'est elle
#: qui laisse une direction sans signature.
ABSENCES = [
    ("dir.dfc", "Congé annuel", -30, 15, "focal.dfc"),
    ("dir.dexp", "Mission", -12, 5, "focal.dexp"),
    ("dir.drh", "Formation", -5, 10, None),
    ("dir.daj", "Congé annuel", 8, 21, "agent.daj"),
    ("dir.dsi", "Mission", 15, 4, "focal.dsi"),
    ("dcg", "Absence exceptionnelle", 3, 2, None),
]

#: Le planning des conges : (agent, debut relatif, duree, etat, motif de report).
#:
#: Les quatre etats sont representes. Un planning ou tout serait valide ne
#: montrerait pas l'arbitrage, qui est la raison d'etre de l'ecran.
CONGES = [
    ("dir.dfc", -30, 15, "valide", None),
    ("dir.dexp", 20, 21, "arbitre", None),
    ("dir.drh", 40, 15, "souhaite", None),
    ("dir.dsi", 34, 20, "souhaite", None),
    ("dir.dag", 12, 10, "valide", None),
    (
        "dir.daj",
        26,
        21,
        "reporte",
        "La direction serait sans signature pendant la session du Conseil d'administration.",
    ),
    ("agent.dfc", 55, 12, "souhaite", None),
    ("focal.dexp", 18, 8, "arbitre", None),
]

#: Les filiales et succursales — l'amont du §3.3 : (sigle, libelle, nature,
#: organe, jours avant la prochaine session, etat de preparation, documents
#: attendus, documents recus).
ENTITES = [
    (
        "SEPBC",
        "Société d'Exploitation des Parcs à Bois du Cameroun",
        "filiale",
        "conseil_administration",
        18,
        "dossier_en_cours",
        8,
        5,
    ),
    (
        "REP-NDJ",
        "Représentation du PAD à N'Djamena",
        "succursale",
        "comite_gestion",
        40,
        "a_preparer",
        6,
        0,
    ),
    (
        "REP-BGI",
        "Représentation du PAD à Bangui",
        "succursale",
        "comite_gestion",
        -9,
        "tenue",
        6,
        6,
    ),
    (
        "SOCAPORT",
        "Société Camerounaise de Services Portuaires",
        "filiale",
        "assemblee_generale",
        6,
        "dossier_transmis",
        10,
        10,
    ),
]

#: Les organisations ou le Port est represente, et ses mandats — l'aval du §3.3 :
#: (sigle, libelle, nature, representant, suppleant, mandat en mois, reunions
#: tenues, reunions auxquelles le representant a participe, apport).
REPRESENTATIONS = [
    (
        "AGPAOC",
        "Association de Gestion des Ports de l'Afrique de l'Ouest et du Centre",
        "organisation_portuaire",
        "dg",
        "dir.dexp",
        36,
        6,
        5,
        "Accès aux statistiques comparées de la sous-région.",
    ),
    (
        "CNCC",
        "Conseil National des Chargeurs du Cameroun",
        "comite_national",
        "dir.dexp",
        "focal.dexp",
        24,
        9,
        4,
        None,
    ),
    (
        "CNFE",
        "Comité National de Facilitation des Échanges",
        "comite_national",
        "dir.dsi",
        None,
        24,
        4,
        4,
        "Interconnexion au guichet unique portée par ce comité.",
    ),
    (
        "GICAM",
        "Groupement Inter-patronal du Cameroun",
        "association_professionnelle",
        "dir.dfc",
        None,
        12,
        11,
        3,
        None,
    ),
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose seances, decisions, absences, conges et representations."""
    if Seance.objects.exists():
        ecrire(f"  {Seance.objects.count()} seances deja en base — passe")
        return 0

    tirage = random.Random(GRAINE)
    seances = _seances(annuaire, ecrire)
    decisions = _decisions(annuaire, seances, tirage, ecrire)
    _absences(annuaire, ecrire)
    _conges(annuaire, ecrire)
    _entites_et_mandats(annuaire, ecrire)
    return len(decisions)


# ---------------------------------------------------------------------
#  Seances
# ---------------------------------------------------------------------


def _seances(annuaire: dict, ecrire) -> list[Seance]:
    att = annuaire["att.dsr"]
    posees: list[Seance] = []

    for type_seance, intitule, recul, president, structure, points, documents in SEANCES:
        jour = date.today() + timedelta(days=recul)
        seance = services.creer_seance(
            att,
            SimpleNamespace(
                type=type_seance,
                intitule=intitule,
                date=jour.isoformat(),
                presidentId=annuaire[president].pk,
                structure=structure,
                # `echeance_depot` est posterieure a la seance — le service
                # refuse l'inverse. C'est la date a laquelle les pieces de la
                # seance, compte rendu compris, doivent etre au registre ; un
                # depot ulterieur est « hors delai », et la fiche le signale.
                echeanceDepot=(jour + timedelta(days=10)).isoformat(),
                ordreDuJour=[
                    SimpleNamespace(point=point, rapporteurId=annuaire[rapporteur].pk)
                    for point, rapporteur in points
                ],
            ),
        )
        _convoquer(seance, annuaire, recul)
        for nature, libelle, decalage in documents:
            _deposer(seance, att, nature, libelle, jour + timedelta(days=decalage))
        posees.append(seance)

    ecrire(f"  {len(posees)} seances inscrites au registre")
    return posees


#: Qui siege au comite de direction. Le CODIR est le conseil des directeurs :
#: tous y sont convoques, et l'absence de l'un se lit contre le registre des
#: disponibilites.
CONVOQUES = [
    "dg",
    "dir.dfc",
    "dir.dexp",
    "dir.dsi",
    "dir.drh",
    "dir.daj",
    "dir.dag",
    "dir.damp",
    "dir.dcap",
    "dsr",
    "dcg",
]


def _convoquer(seance: Seance, annuaire: dict, recul: int) -> None:
    """
    Les convoques, et qui etait la.

    Aucun ecran ne saisit la presence : la table est posee par l'ORM. Pour une
    seance a venir, personne n'est encore present — c'est l'etat normal, et non
    une absence generale.
    """
    tenue = recul < 0
    for rang, identifiant in enumerate(CONVOQUES):
        agent = annuaire.get(identifiant)
        if agent is None:
            continue
        # Un ou deux absents par seance : le registre sert precisement a
        # montrer qu'un directeur convoque n'etait pas la.
        absent = tenue and (rang + seance.pk) % 7 == 0
        SeanceParticipant.objects.create(
            seance=seance,
            utilisateur=agent,
            present=tenue and not absent,
            excuse=absent,
        )


def _deposer(seance: Seance, agent: Utilisateur, nature: str, libelle: str, jour: date) -> None:
    """
    Le depot d'un document de seance, puis sa date reelle.

    `deposer_document` date du jour — c'est son travail. La date est reculee
    ensuite, sinon tous les comptes rendus des trois derniers mois auraient ete
    deposes aujourd'hui, et la ponctualite du §3.3 se serait lue a l'envers.
    """
    document = services.deposer_document(
        agent,
        seance.pk,
        SimpleNamespace(
            seanceId=seance.pk,
            nature=nature,
            libelle=libelle,
            nomFichier=f"{seance.reference}-{nature.lower().replace(' ', '-')}.pdf",
            poids="1.4 Mo",
        ),
    )
    with connection.cursor() as curseur:
        curseur.execute(
            "UPDATE seance_document SET depose_le = %s WHERE id = %s",
            [min(jour, date.today()), document.pk],
        )


# ---------------------------------------------------------------------
#  Decisions
# ---------------------------------------------------------------------

#: Qui declare l'avancement d'une decision : le directeur de la structure
#: pilote. `consigner_avancement` exige le **rattachement**, pas le perimetre de
#: lecture — la DSR voit tout et ne declare rien, c'est une garde et non un
#: oubli.
DECLARANTS = {
    "DSI": "dir.dsi",
    "DFC": "dir.dfc",
    "DEXP": "dir.dexp",
    "DRH": "dir.drh",
    "DAJ": "dir.daj",
    "DAG": "dir.dag",
    "DAMP": "dir.damp",
    "DCAP": "dir.dcap",
    "DCG": "dcg",
    "SCC": "chef.cab",
    "DDLM": "chef.ddlm",
}

#: L'observation qui accompagne une declaration. Un chiffre qui bouge sans
#: explication ne se relit pas six mois plus tard.
OBSERVATIONS = [
    "Les travaux avancent conformément au calendrier arrêté en séance.",
    "L'exécution dépend d'un avis externe encore attendu.",
    "Deux des trois volets sont livrés ; le dernier est en cours.",
    "Les moyens ont été mobilisés, les premiers résultats sont mesurables.",
    "Le calendrier initial ne pourra pas être tenu ; une révision sera proposée.",
]


def _decisions(annuaire: dict, seances: list[Seance], tirage, ecrire) -> list[Engagement]:
    from noyau.organisation.modeles import Structure

    att = annuaire["att.dsr"]
    structures = {s.code: s for s in Structure.objects.filter(valide_au__isnull=True)}
    posees: list[Engagement] = []

    for rang, (instance, objet, age, delai, codes, avancement, etat) in enumerate(DECISIONS):
        jour = date.today() - timedelta(days=age)
        chargees = [structures[code] for code in codes if code in structures]
        if not chargees:
            continue

        engagement = services.creer_engagement(
            att,
            SimpleNamespace(
                instance=instance,
                # La seance citee par sa reference exacte, ou rien : deviner
                # produirait un rattachement faux et invisible.
                seance=_seance_du_jour(seances, jour),
                objet=objet,
                contexte="",
                dateDecision=jour.isoformat(),
                echeance=(jour + timedelta(days=delai)).isoformat(),
                structures=[s.pk for s in chargees],
            ),
        )
        _poser_jalons(engagement, rang, chargees[0], jour, delai)

        if avancement:
            declarant = annuaire.get(DECLARANTS.get(codes[0], ""))
            if declarant is not None:
                services.consigner_avancement(
                    declarant,
                    engagement.pk,
                    SimpleNamespace(
                        decisionId=engagement.pk,
                        avancement=avancement,
                        observation=tirage.choice(OBSERVATIONS),
                        jalonsFaits=[],
                    ),
                )

        if etat == "execute":
            _prononcer_execution(engagement, att, jour + timedelta(days=delai))
        elif etat == "suspendu":
            _prononcer_suspension(engagement, att)

        _retrodater(engagement, jour)
        posees.append(engagement)

    _relancer(posees, annuaire, ecrire)
    ecrire(f"  {len(posees)} decisions consignees")
    return posees


def _seance_du_jour(seances: list[Seance], jour: date) -> str:
    """La reference de la seance tenue ce jour-la, ou la chaine vide."""
    for seance in seances:
        if seance.date_seance == jour:
            return seance.reference
    return ""


def _poser_jalons(engagement: Engagement, rang: int, pilote, jour: date, delai: int) -> None:
    ordre = 1
    for rang_decision, libelle, part, fait in JALONS:
        if rang_decision != rang:
            continue
        echeance = jour + timedelta(days=int(delai * part))
        EngagementJalon.objects.create(
            engagement=engagement,
            structure=pilote,
            libelle=libelle,
            echeance=echeance,
            fait_le=echeance if fait else None,
            ordre=ordre,
        )
        ordre += 1


def _prononcer_execution(engagement: Engagement, agent: Utilisateur, jour: date) -> None:
    """
    Pose `execute_le` — **aucun service ne le fait**, voir A66.

    Sans cette ecriture, une decision a cent pour cent reste « en cours » ou
    bascule « en retard » des son echeance : le registre n'aurait jamais montre
    l'etat « executee », et le taux d'execution du §17 serait reste a zero.
    """
    from noyau.demonstration.courriers import _horodatage

    with acteur(agent), connection.cursor() as curseur:
        curseur.execute(
            "UPDATE engagement SET execute_le = %s, execute_par = %s WHERE id = %s",
            [_horodatage(min(jour, date.today() - timedelta(days=1))), agent.pk, engagement.pk],
        )


def _prononcer_suspension(engagement: Engagement, agent: Utilisateur) -> None:
    """Meme lacune que ci-dessus : la suspension d'une decision n'a pas de geste."""
    with acteur(agent), connection.cursor() as curseur:
        curseur.execute(
            """
            UPDATE engagement
               SET suspendu_le = now(), suspendu_par = %s, motif_suspension = %s
             WHERE id = %s
            """,
            [
                agent.pk,
                "Exécution suspendue dans l'attente de l'avis de non-objection du bailleur.",
                engagement.pk,
            ],
        )


def _relancer(posees: list[Engagement], annuaire: dict, ecrire) -> None:
    """
    Les relances de la DSR — §1.1.

    Une decision executee ne se relance pas : `relancer` le refuse, et il a
    raison — le compteur ferait paraitre defaillante une structure qui a livre.
    """
    dsr = annuaire["dsr"]
    emises = 0
    for rang, motif in RELANCES:
        if rang >= len(posees):
            continue
        engagement = posees[rang]
        if engagement.execute_le is not None:
            continue
        services.relancer(
            dsr,
            engagement.pk,
            SimpleNamespace(decisionId=engagement.pk, motif=motif, structureId=None),
        )
        emises += 1
    ecrire(f"  {emises} relances sur decisions")


def _retrodater(engagement: Engagement, jour: date) -> None:
    from noyau.demonstration.courriers import _horodatage

    horodatage = _horodatage(min(jour, date.today() - timedelta(days=1)))
    with connection.cursor() as curseur:
        curseur.execute(
            "UPDATE engagement SET cree_le = %s WHERE id = %s", [horodatage, engagement.pk]
        )
        curseur.execute(
            """
            UPDATE evenement SET survenu_le = %s
             WHERE objet_type = 'engagement' AND objet_id = %s
               AND type_evenement = 'engagement_consigne'
            """,
            [horodatage, engagement.pk],
        )


# ---------------------------------------------------------------------
#  Disponibilites et conges
# ---------------------------------------------------------------------


def _absences(annuaire: dict, ecrire) -> None:
    att = annuaire["att.dsr"]
    posees = 0
    for identifiant, type_absence, depart, duree, interimaire in ABSENCES:
        absent = annuaire.get(identifiant)
        if absent is None:
            continue
        du = date.today() + timedelta(days=depart)
        services.declarer_absence(
            att,
            SimpleNamespace(
                responsableId=absent.pk,
                type=type_absence,
                du=du.isoformat(),
                au=(du + timedelta(days=duree)).isoformat(),
                interimaireId=annuaire[interimaire].pk if interimaire else None,
            ),
        )
        posees += 1
    ecrire(f"  {posees} absences declarees")


def _conges(annuaire: dict, ecrire) -> None:
    """
    Le planning des conges.

    Aucun service ne l'ecrit : l'ecran est en lecture seule a ce jour. Les
    lignes sont donc posees par l'ORM, ce qui reste sans risque — un souhait de
    conge ne porte aucune regle metier tant que personne ne l'arbitre a l'ecran.
    """
    annee = date.today().year
    posees = 0
    for identifiant, depart, duree, etat, motif in CONGES:
        agent = annuaire.get(identifiant)
        if agent is None:
            continue
        droit, _ = CongeDroit.objects.get_or_create(
            utilisateur=agent, annee=annee, defaults={"droits_jours": 30}
        )
        du = date.today() + timedelta(days=depart)
        CongePeriode.objects.create(
            conge_droit=droit,
            du=du,
            au=du + timedelta(days=duree),
            etat=etat,
            motif_report=motif,
            arbitre_le=None,
        )
        posees += 1
    ecrire(f"  {posees} periodes de conge")


# ---------------------------------------------------------------------
#  Filiales et representations
# ---------------------------------------------------------------------


def _entites_et_mandats(annuaire: dict, ecrire) -> None:
    for sigle, libelle, nature, organe, jours, etat, attendus, recus in ENTITES:
        entite, _ = EntiteExterne.objects.get_or_create(
            sigle=sigle,
            defaults={"libelle": libelle, "nature": nature, "valide_du": date(2020, 1, 1)},
        )
        OrganeGestion.objects.get_or_create(
            entite_externe=entite,
            organe=organe,
            defaults={
                "prochaine_session": date.today() + timedelta(days=jours),
                "etat_preparation": etat,
                "documents_attendus": attendus,
                "documents_recus": recus,
            },
        )

    for (
        sigle,
        libelle,
        nature,
        representant,
        suppleant,
        mois,
        tenues,
        participees,
        apport,
    ) in REPRESENTATIONS:
        organisation, _ = OrganisationExterne.objects.get_or_create(
            sigle=sigle, defaults={"libelle": libelle, "nature": nature}
        )
        Representation.objects.get_or_create(
            organisation_externe=organisation,
            representant=annuaire[representant],
            defaults={
                "suppleant": annuaire[suppleant] if suppleant else None,
                "mandat_du": date.today() - timedelta(days=30 * (mois // 2)),
                "mandat_au": date.today() + timedelta(days=30 * (mois // 2)),
                "reunions_tenues": tenues,
                "reunions_participees": participees,
                "apport": apport,
            },
        )
    ecrire(f"  {len(ENTITES)} entites exterieures, {len(REPRESENTATIONS)} representations")

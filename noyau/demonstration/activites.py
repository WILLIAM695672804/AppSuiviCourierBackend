"""
Les plans d'actions annuels et leurs activites — le pilier du §15 au §20.

**Tout passe par `activite.services`**, pour la meme raison que le registre des
courriers : le code d'activite vient d'un declencheur, l'avancement est
recalcule depuis les taches (arbitrage n° 1), et chaque geste inscrit son
evenement. Des `INSERT` directs auraient donne des activites sans code, a
l'avancement fige, et une fiche de vie vide.

Ce que le jeu doit montrer, ecran par ecran :

  * les cinq **etats affiches** de `v_activite_etat` — programmee, en cours,
    en retard, realisee, suspendue — car un tableau de bord ou aucune activite
    n'est en retard ne prouve pas que le calcul du retard fonctionne ;
  * l'avancement **somme des taches** (ADR 049) : chaque tache porte sa part,
    la structure declare ce qu'elle a obtenu, l'activite en fait la somme ;
  * les **gestes d'autorite** du §17 et du §19 : instruction rattachee, levee,
    suspension, reprise, relance ;
  * le **cycle du plan** (A5) : brouillon, soumis, retourne, valide. Les quatre
    statuts a la fois, faute de quoi l'ecran de validation de la DCG s'ouvre sur
    une liste vide.

Le cycle du plan se joue **en dernier** : un plan valide n'accepte plus
d'activite, et le semis se serait arrete au milieu.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace

from django.db import connection

from activite import services
from activite.modeles import Activite, PlanActions
from noyau.identite.modeles import Utilisateur
from noyau.journal.contexte import acteur

#: La meme graine que le registre des courriers : une demonstration se refait a
#: l'identique ou elle ne se compare pas.
GRAINE = 20260819

#: L'annee de l'exercice ouvert. Lue en base au moment du semis — l'ecrire ici
#: aurait fait echouer le chargement le 1er janvier suivant.
ANNEE: int = 0

#: Les activites, par structure porteuse.
#:
#: `etat` dit ce que l'ecran doit montrer, et **non** ce qui est ecrit en base :
#: `activite.etat` est pose par declencheur, et « en retard » comme
#: « programmee » se deduisent des dates (arbitrage n° 2). D'ou des periodes
#: choisies, pas des etats forces :
#:
#:  * `retard`     — fin depassee, avancement incomplet ;
#:  * `realisee`   — toutes les taches faites ;
#:  * `en_cours`   — periode courante, avancement partiel ;
#:  * `programmee` — debut a venir ;
#:  * `suspendue`  — suspension ouverte, prononcee plus bas.
#:
#: `taches` : (intitule, mois de fin, faite). Les parts sont egales — le jeu
#: montre la somme, pas la ponderation — et une tache faite obtient toute la
#: sienne. Une fiche sans tache recoit la tache unique de la reprise SQL,
#: `TACHE_UNIQUE`, qui obtient `avancement` (ADR 049).
#:
#: `indicateurs` : (libelle, unite, reference, cible, [trois releves]).
ACTIVITES = [
    # --- Direction des systemes d'information --------------------------
    {
        "focal": "focal.dsi",
        "responsable": "agent.dsi",
        "axe": "Port innovant et responsable",
        "intitule": "Deploiement de la plateforme de suivi des courriers",
        "objectif": "Dematerialiser le traitement du courrier de bout en bout",
        "resultats": "Plateforme en service dans les 8 directions, agents formes",
        "budget": 185_000_000,
        "periode": ((1, 15), (12, 15)),
        "etat": "en_cours",
        "taches": [
            ("Cadrage fonctionnel et validation du descriptif", 3, True),
            ("Developpement du registre et de la cotation", 6, True),
            ("Reprise de l'organigramme et des habilitations", 8, True),
            ("Formation des agents de session", 10, False),
            ("Mise en service et accompagnement", 12, False),
        ],
        "indicateurs": [
            ("Directions raccordees", "directions", "0", "8", ["2", "5", "6"]),
            ("Agents formes", "agents", "0", "120", ["0", "34", "58"]),
        ],
    },
    {
        "focal": "focal.dsi",
        "responsable": "focal.dsi",
        "axe": "Port innovant et responsable",
        "intitule": "Securisation du systeme d'information portuaire",
        "objectif": "Reduire l'exposition aux incidents de securite",
        "resultats": "Politique de securite adoptee, sauvegardes eprouvees",
        "budget": 62_000_000,
        "periode": ((2, 1), (7, 31)),
        "etat": "retard",
        "taches": [
            ("Audit de l'existant", 3, True),
            ("Redaction de la politique de securite", 5, True),
            ("Test de restauration des sauvegardes", 7, False),
        ],
        "indicateurs": [],
    },
    {
        "focal": "focal.dsi",
        "responsable": "agent.dsi",
        "axe": "Port compétitif et fluide",
        "intitule": "Interconnexion avec le guichet unique du commerce exterieur",
        "objectif": "Supprimer la double saisie des declarations",
        "resultats": "Flux automatise, delai de transmission sous 2 heures",
        "budget": 44_000_000,
        "periode": ((9, 1), (12, 31)),
        "etat": "programmee",
        "taches": [],
        "avancement": 0,
        "indicateurs": [],
    },
    # --- Direction financiere et comptable ------------------------------
    {
        "focal": "focal.dfc",
        "responsable": "agent.dfc",
        "axe": "Port attractif et performant",
        "intitule": "Recouvrement des creances portuaires anterieures a 2025",
        "objectif": "Ramener l'encours ancien sous le seuil de 2 milliards",
        "resultats": "Encours reduit de 40 %, echeanciers signes",
        "budget": 0,
        "periode": ((1, 5), (12, 31)),
        "etat": "en_cours",
        "taches": [
            ("Etat des lieux des creances par secteur", 2, True),
            ("Mise en demeure des debiteurs principaux", 4, True),
            ("Negociation des echeanciers", 9, False),
            ("Saisine du contentieux pour les refus", 11, False),
        ],
        "indicateurs": [
            ("Taux de recouvrement", "%", "18", "60", ["24", "38", "47"]),
            ("Encours ancien", "millions FCFA", "3200", "1900", ["3050", "2610", "2340"]),
        ],
    },
    {
        "focal": "focal.dfc",
        "responsable": "focal.dfc",
        "axe": "Port attractif et performant",
        "intitule": "Elaboration du budget programme 2027",
        "objectif": "Aligner le budget sur les trois axes strategiques",
        "resultats": "Budget adopte par le conseil avant le 31 decembre",
        "budget": 0,
        "periode": ((6, 1), (12, 20)),
        "etat": "en_cours",
        "taches": [],
        "avancement": 35,
        "indicateurs": [],
    },
    {
        "focal": "focal.dfc",
        "responsable": "agent.dfc",
        "axe": "Port attractif et performant",
        "intitule": "Certification des comptes de l'exercice 2025",
        "objectif": "Obtenir une certification sans reserve",
        "resultats": "Rapport du commissaire aux comptes remis",
        "budget": 28_000_000,
        "periode": ((1, 10), (6, 30)),
        "etat": "realisee",
        "taches": [
            ("Arrete des comptes", 3, True),
            ("Travaux du commissaire aux comptes", 5, True),
            ("Reponse aux observations", 6, True),
        ],
        "indicateurs": [],
    },
    # --- Direction de l'exploitation -------------------------------------
    {
        "focal": "focal.dexp",
        "responsable": "focal.dexp",
        "axe": "Port compétitif et fluide",
        "intitule": "Reduction du temps de sejour des conteneurs",
        "objectif": "Ramener le sejour moyen a 7 jours",
        "resultats": "Sejour moyen sous 8 jours au dernier trimestre",
        "budget": 95_000_000,
        "periode": ((1, 15), (12, 31)),
        "etat": "en_cours",
        "taches": [
            ("Diagnostic des points de blocage", 3, True),
            ("Reorganisation des aires de stockage", 6, True),
            ("Facturation incitative des sejours longs", 9, False),
            ("Bilan et ajustement", 12, False),
        ],
        "indicateurs": [
            ("Sejour moyen des conteneurs", "jours", "11,5", "7", ["10,8", "9,4", "8,6"]),
            ("Taux d'occupation des aires", "%", "88", "75", ["86", "81", "78"]),
        ],
    },
    {
        "focal": "focal.dexp",
        "responsable": "focal.dexp",
        "axe": "Port compétitif et fluide",
        "intitule": "Dragage d'entretien du chenal d'acces",
        "objectif": "Maintenir le tirant d'eau admissible a 12,5 metres",
        "resultats": "Cotes retablies sur toute la longueur du chenal",
        "budget": 1_250_000_000,
        "periode": ((3, 1), (11, 30)),
        "etat": "suspendue",
        "taches": [
            ("Bathymetrie de reference", 4, True),
            ("Passation du marche de dragage", 6, True),
            ("Campagne de dragage", 10, False),
        ],
        "indicateurs": [
            ("Tirant d'eau admissible", "metres", "11,2", "12,5", ["11,4", "11,8", "11,9"]),
        ],
    },
    {
        "focal": "focal.dexp",
        "responsable": "focal.dexp",
        "axe": "Port innovant et responsable",
        "intitule": "Plan de gestion des dechets d'exploitation",
        "objectif": "Se conformer a la convention MARPOL",
        "resultats": "Installations de reception en service",
        "budget": 210_000_000,
        "periode": ((2, 1), (8, 15)),
        "etat": "retard",
        "taches": [
            ("Etude d'impact environnemental", 4, True),
            ("Travaux des installations de reception", 7, False),
            ("Agrement des prestataires collecteurs", 8, False),
        ],
        "indicateurs": [],
    },
    # --- Direction des ressources humaines --------------------------------
    {
        "focal": "focal.drh",
        "responsable": "focal.drh",
        "axe": "Port attractif et performant",
        "intitule": "Plan de formation du personnel 2026",
        "objectif": "Former 300 agents aux metiers portuaires",
        "resultats": "300 agents formes, evaluation a chaud realisee",
        "budget": 140_000_000,
        "periode": ((1, 20), (12, 15)),
        "etat": "en_cours",
        "taches": [
            ("Recensement des besoins par direction", 3, True),
            ("Passation des marches de formation", 5, True),
            ("Sessions du premier semestre", 7, True),
            ("Sessions du second semestre", 12, False),
        ],
        "indicateurs": [
            ("Agents formes", "agents", "0", "300", ["48", "141", "186"]),
        ],
    },
    {
        "focal": "focal.drh",
        "responsable": "focal.drh",
        "axe": "Port attractif et performant",
        "intitule": "Refonte de la grille des emplois et competences",
        "objectif": "Doter chaque poste d'une fiche de fonction",
        "resultats": "Referentiel des emplois adopte",
        "budget": 35_000_000,
        "periode": ((4, 1), (12, 31)),
        "etat": "en_cours",
        "taches": [],
        "avancement": 55,
        "indicateurs": [],
    },
    {
        "focal": "focal.drh",
        "responsable": "focal.drh",
        "axe": "Port innovant et responsable",
        "intitule": "Amelioration des conditions d'hygiene et de securite au travail",
        "objectif": "Reduire de moitie les accidents de travail",
        "resultats": "Equipements de protection distribues, comite HSE installe",
        "budget": 78_000_000,
        "periode": ((10, 1), (12, 31)),
        "etat": "programmee",
        "taches": [],
        "avancement": 0,
        "indicateurs": [],
    },
    # --- Controle de gestion ----------------------------------------------
    {
        "focal": "focal.dcg",
        "responsable": "focal.dcg",
        "axe": "Port attractif et performant",
        "intitule": "Mise en place du tableau de bord de la direction generale",
        "objectif": "Doter le CODIR d'un tableau de bord mensuel",
        "resultats": "Tableau de bord diffuse chaque mois avant le 10",
        "budget": 18_000_000,
        "periode": ((1, 5), (9, 30)),
        "etat": "en_cours",
        "taches": [
            ("Dictionnaire des indicateurs", 3, True),
            ("Calendrier de production des donnees", 5, True),
            ("Premiere edition du tableau de bord", 7, True),
            ("Automatisation de la collecte", 9, False),
        ],
        "indicateurs": [
            ("Editions diffusees dans les delais", "%", "0", "100", ["50", "75", "80"]),
        ],
    },
    {
        "focal": "focal.dcg",
        "responsable": "focal.dcg",
        "axe": "Port compétitif et fluide",
        "intitule": "Evaluation des contrats de concession",
        "objectif": "Verifier le respect des engagements des concessionnaires",
        "resultats": "Rapport d'evaluation par concession",
        "budget": 22_000_000,
        "periode": ((2, 15), (7, 31)),
        "etat": "retard",
        "taches": [],
        "avancement": 70,
        "indicateurs": [],
    },
]

#: Les suspensions prononcees, par intitule d'activite : (motif, reprise).
#:
#: La seconde est **reprise**, et c'est le point : une suspension sans reprise
#: laisse croire que le geste est a sens unique, et l'ecran de reprise ne se
#: montre jamais.
SUSPENSIONS = [
    (
        "Dragage d'entretien du chenal d'acces",
        "Marche suspendu dans l'attente de l'avis de non-objection du bailleur.",
        None,
    ),
    (
        "Refonte de la grille des emplois et competences",
        "Travaux interrompus pendant la negociation de la convention collective.",
        "Negociation aboutie, les travaux reprennent.",
    ),
]

#: Les instructions du §17, par intitule : (origine, texte, echeance en jours,
#: commentaire de levee ou `None`).
INSTRUCTIONS = [
    (
        "Securisation du systeme d'information portuaire",
        "Instruction verbale",
        "Presenter le rapport de test de restauration au prochain CODIR.",
        21,
        None,
    ),
    (
        "Plan de gestion des dechets d'exploitation",
        "Instruction verbale",
        "Transmettre le calendrier revise des travaux sous huitaine.",
        -12,
        None,
    ),
    (
        "Recouvrement des creances portuaires anterieures a 2025",
        "Instruction verbale",
        "Produire la liste nominative des dix premiers debiteurs.",
        -30,
        "Liste produite et transmise au Directeur general.",
    ),
]

#: Les relances emises par la DSR sur les activites en retard — §1.1.
RELANCES = [
    (
        "Plan de gestion des dechets d'exploitation",
        "Echeance depassee depuis un mois sans declaration d'avancement. "
        "Merci d'actualiser la fiche avant la fin de la semaine.",
    ),
    (
        "Evaluation des contrats de concession",
        "Le rapport d'evaluation etait attendu au 31 juillet. Ou en est-il ?",
    ),
]

#: Le cycle du plan (A5) : (code structure, action, motif).
#:
#: Les quatre statuts sont representes — DEXP-OP reste au brouillon en ne
#: figurant pas dans cette liste.
CYCLE_DES_PLANS = [
    ("DSI-GL", "soumettre", None),
    ("DSI-GL", "valider", None),
    ("DFC-CPT", "soumettre", None),
    ("DFC-CPT", "retourner", "Les budgets de deux activites ne sont pas justifies."),
    ("DRH-GP", "soumettre", None),
    ("DCG-MPE", "soumettre", None),
    ("DCG-MPE", "valider", None),
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Pose les plans d'actions et leurs activites. Rend le nombre d'activites."""
    global ANNEE

    deja = Activite.objects.count()
    if deja:
        ecrire(f"  {deja} activites deja en base — passe")
        return 0

    from activite.modeles import Exercice

    exercice = Exercice.objects.filter(ouvert=True).order_by("-annee").first()
    assert exercice is not None
    ANNEE = exercice.annee
    tirage = random.Random(GRAINE)

    posees: dict[str, Activite] = {}
    for fiche in ACTIVITES:
        activite = _poser(fiche, annuaire, tirage)
        posees[str(fiche["intitule"])] = activite

    _suspendre(posees, annuaire, ecrire)
    _instruire(posees, annuaire, ecrire)
    _relancer(posees, annuaire, ecrire)
    # En dernier : un plan valide n'accepte plus d'activite.
    _jouer_le_cycle(annuaire, ecrire)

    ecrire(f"  {len(posees)} activites dans {PlanActions.objects.count()} plans")
    return len(posees)


# ---------------------------------------------------------------------
#  Une activite
# ---------------------------------------------------------------------


def _poser(fiche: dict, annuaire: dict, tirage: random.Random) -> Activite:
    (mois_debut, jour_debut), (mois_fin, jour_fin) = fiche["periode"]
    focal = annuaire[fiche["focal"]]
    taches, obtenues = _decouper(fiche, mois_debut, mois_fin)

    activite = services.creer_activite(
        focal,
        SimpleNamespace(
            intitule=fiche["intitule"],
            axe=fiche["axe"],
            objectif=fiche["objectif"],
            etatReferenceGeneral="",
            resultatsAttendus=fiche["resultats"],
            debut=date(ANNEE, mois_debut, jour_debut).isoformat(),
            fin=date(ANNEE, mois_fin, jour_fin).isoformat(),
            budgetValide=fiche["budget"] or None,
            responsableId=annuaire[fiche["responsable"]].pk,
            taches=taches,
        ),
    )

    # L'observation est tiree **une fois** par activite, comme avant l'ADR 049 :
    # un tirage par tache aurait decale toute la suite du generateur, et la
    # demonstration ne se serait plus refaite a l'identique des releves.
    observation = _observation(fiche["etat"], tirage)
    for tache, obtenue in zip(activite.taches.order_by("ordre", "pk"), obtenues, strict=True):
        if obtenue > 0:
            _declarer(focal, activite, tache.pk, obtenue, observation)
    if not any(obtenues):
        # Une declaration a zero, pour que la fiche de vie porte l'observation
        # meme sur une activite qui n'a pas commence.
        _declarer(focal, activite, activite.taches.order_by("ordre", "pk")[0].pk, 0, observation)

    for libelle, unite, reference, cible, releves in fiche["indicateurs"]:
        _mesurer(focal, activite, libelle, unite, reference, cible, releves)

    if fiche["etat"] == "realisee":
        _declarer_realisee(activite, focal)

    _retrodater(activite, date(ANNEE, mois_debut, jour_debut))
    activite.refresh_from_db()
    return activite


#: Le libelle de la reprise SQL et de l'importeur DFC, a la lettre (ADR 049).
TACHE_UNIQUE = "Exécution de l'activité"


def _decouper(fiche: dict, mois_debut: int, mois_fin: int) -> tuple[list, list[float]]:
    """
    Les taches a creer avec l'activite (RG-1) et ce que chacune obtient.

    Parts egales en centiemes entiers, le reliquat sur la derniere : trois
    taches font 33,33 / 33,33 / 33,34, et la somme tombe sur 100 (RG-3). Chaque
    tache commence au debut de l'activite et finit a son mois, ramene dans la
    periode (RG-9) — la regle meme de la reprise SQL.
    """
    lignes = fiche["taches"] or [(TACHE_UNIQUE, mois_fin, False)]
    base = 10000 // len(lignes)
    parts = [base] * (len(lignes) - 1) + [10000 - base * (len(lignes) - 1)]

    taches, obtenues = [], []
    for (intitule, mois, faite), part in zip(lignes, parts, strict=True):
        taches.append(
            SimpleNamespace(
                libelle=intitule,
                valeurPrevue=part / 100,
                moisDebut=f"{ANNEE}-{mois_debut:02d}",
                moisFin=f"{ANNEE}-{max(mois_debut, min(mois, mois_fin)):02d}",
            )
        )
        obtenues.append(part / 100 if faite else 0.0)

    if not fiche["taches"]:
        obtenues = [float(fiche.get("avancement", 0))]
    return taches, obtenues


def _declarer(focal, activite: Activite, tache_id: int, obtenue: float, observation: str) -> None:
    services.declarer_avancement(
        focal,
        activite.pk,
        SimpleNamespace(tacheId=tache_id, valeurObtenue=obtenue, observation=observation),
    )


def _declarer_realisee(activite: Activite, agent: Utilisateur) -> None:
    """
    Pose `etat = 'realisee'`, en SQL — **faute de service qui le fasse**.

    Aucun geste du pilier n'ecrit cet etat : ni `declarer_avancement`, ni le
    declencheur d'avancement, ni aucune route. Une activite a cent pour cent
    reste donc « en cours », et « en retard » des que sa date de fin est passee.
    C'est une lacune, pas une regle — elle est ouverte en A66, et le semis ne
    la contourne que pour montrer l'etat que la vue sait afficher.

    Ecrire l'etat directement est admis **ici et nulle part ailleurs** : le
    faire dans `services.py` reviendrait a trancher A66 par le code.
    """
    # Le contexte d'acteur est indispensable : `historiser_champs()` refuse
    # toute ecriture anonyme sur `activite`, et `etat` est une colonne suivie.
    with acteur(agent), connection.cursor() as curseur:
        curseur.execute("UPDATE activite SET etat = 'realisee' WHERE id = %s", [activite.pk])


#: Ce qu'un point focal ecrit dans la case « observation ». Une observation vide
#: fait une fiche de vie muette : la colonne existe, l'ecran l'affiche, et rien
#: n'y figure jamais.
OBSERVATIONS = {
    "en_cours": [
        "Execution conforme au calendrier.",
        "Avancement satisfaisant, aucune difficulte signalee.",
        "Les prestataires sont mobilises, le rythme se maintient.",
    ],
    "retard": [
        "Retard imputable au delai de passation du marche.",
        "Difficultes de tresorerie ; le calendrier sera revu.",
        "En attente de l'avis technique de la direction concernee.",
    ],
    "realisee": [
        "Activite achevee, resultats conformes aux attentes.",
    ],
    "programmee": [
        "Demarrage prevu conformement au plan.",
    ],
    "suspendue": [
        "Travaux engages avant la suspension.",
    ],
}


def _observation(etat: str, tirage: random.Random) -> str:
    choix = OBSERVATIONS.get(etat) or OBSERVATIONS["en_cours"]
    return tirage.choice(choix)


def _mesurer(focal, activite, libelle, unite, reference, cible, releves) -> None:
    """
    L'indicateur et sa **serie** de mesures.

    Trois releves et non un seul : `relever_indicateur` date du jour et refuse
    d'ecraser une mesure precedente — c'est la suite qui montre une progression.
    Le semis pose donc le releve, le recule, recommence. Sans cette suite, la
    courbe de la fiche d'activite n'a qu'un point et ne se dessine pas.
    """
    indicateur = services.ajouter_indicateur(
        focal,
        activite.pk,
        SimpleNamespace(libelle=libelle, unite=unite, etatReference=reference, cible=cible),
    )
    for rang, valeur in enumerate(releves):
        services.relever_indicateur(
            focal, activite.pk, indicateur.pk, SimpleNamespace(realise=valeur)
        )
        recul = (len(releves) - 1 - rang) * 30
        if recul:
            with connection.cursor() as curseur:
                curseur.execute(
                    """
                    UPDATE indicateur_mesure
                       SET date_mesure = %s
                     WHERE activite_indicateur_id = %s AND date_mesure = %s
                    """,
                    [
                        date.today() - timedelta(days=recul),
                        indicateur.pk,
                        date.today(),
                    ],
                )


def _retrodater(activite: Activite, debut: date) -> None:
    """
    Date l'inscription au plan du jour ou l'activite a commence.

    Une activite de janvier creee aujourd'hui affiche « inscrite au plan il y a
    deux heures » sur sa fiche de vie, et les series mensuelles du tableau de
    bord montrent quinze inscriptions le meme jour.
    """
    from noyau.demonstration.courriers import _horodatage

    horodatage = _horodatage(min(debut, date.today() - timedelta(days=1)))
    with connection.cursor() as curseur:
        curseur.execute("UPDATE activite SET cree_le = %s WHERE id = %s", [horodatage, activite.pk])
        curseur.execute(
            """
            UPDATE evenement SET survenu_le = %s
             WHERE objet_type = 'activite' AND objet_id = %s
               AND type_evenement = 'activite_creee'
            """,
            [horodatage, activite.pk],
        )


# ---------------------------------------------------------------------
#  Les gestes d'autorite
# ---------------------------------------------------------------------


def _suspendre(posees: dict, annuaire: dict, ecrire) -> None:
    """§19. La DSR prononce, la fiche porte la trace."""
    dsr = annuaire["dsr"]
    for intitule, motif, reprise in SUSPENSIONS:
        activite = posees.get(intitule)
        if activite is None:
            continue
        services.basculer_suspension(
            dsr, activite.pk, SimpleNamespace(action="suspendre", motif=motif, reference=None)
        )
        if reprise:
            services.basculer_suspension(
                dsr, activite.pk, SimpleNamespace(action="reprendre", motif=reprise, reference=None)
            )
    ecrire(f"  {len(SUSPENSIONS)} suspensions prononcees")


def _instruire(posees: dict, annuaire: dict, ecrire) -> None:
    """
    §17. Le DG decide, la DSR consigne — d'ou l'acteur.

    Une echeance negative est **depassee** : c'est l'instruction echue et non
    levee qui rend une activite critique (§20), et sans elle l'indicateur de
    criticite reste a zero.
    """
    dsr = annuaire["dsr"]
    for intitule, origine, texte, jours, levee in INSTRUCTIONS:
        activite = posees.get(intitule)
        if activite is None:
            continue
        instruction = services.rattacher_instruction(
            dsr,
            activite.pk,
            SimpleNamespace(
                origine=origine,
                reference=None,
                texte=texte,
                responsableId=activite.responsable_id,
                echeance=(date.today() + timedelta(days=jours)).isoformat(),
            ),
        )
        if levee:
            services.lever_instruction(
                dsr, activite.pk, instruction.pk, SimpleNamespace(commentaire=levee)
            )
    ecrire(f"  {len(INSTRUCTIONS)} instructions rattachees")


def _relancer(posees: dict, annuaire: dict, ecrire) -> None:
    """§1.1. La relance est une escalade : personne ne se relance soi-meme."""
    dsr = annuaire["dsr"]
    emises = 0
    for intitule, texte in RELANCES:
        activite = posees.get(intitule)
        if activite is None or activite.responsable_id == dsr.pk:
            continue
        services.relancer(dsr, activite.pk, SimpleNamespace(texte=texte))
        emises += 1
    ecrire(f"  {emises} relances emises")


def _jouer_le_cycle(annuaire: dict, ecrire) -> None:
    """
    Le cycle du plan, joue jusqu'a montrer les quatre statuts.

    La structure soumet, le controle de gestion valide ou retourne — **jamais
    la meme personne** : `_valider` refuse de valider ce qu'on a soumis, et
    c'est bien ce que la demonstration doit montrer.
    """
    porteurs = {
        "DSI-GL": annuaire["focal.dsi"],
        "DFC-CPT": annuaire["focal.dfc"],
        "DRH-GP": annuaire["focal.drh"],
        "DCG-MPE": annuaire["focal.dcg"],
    }
    for sigle, action, motif in CYCLE_DES_PLANS:
        agent = porteurs[sigle] if action == "soumettre" else annuaire["dcg"]
        services.changer_etat_plan(
            agent,
            SimpleNamespace(annee=ANNEE, structureSigle=sigle, action=action, motif=motif),
        )
    ecrire(f"  {len(CYCLE_DES_PLANS)} mouvements sur les plans d'actions")

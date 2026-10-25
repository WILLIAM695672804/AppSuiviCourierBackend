"""
Ce qui se lit des journaux — I-01 / I-02.

**Lecture seule, sans exception.** Ce module n'a ni fonction d'ecriture ni
fonction de suppression, et il ne doit jamais en avoir : une piste d'audit
qu'on peut corriger ne prouve rien devant un controle. Les journaux sont
alimentes par `noyau.journal.service` (evenements, acces) et par des
declencheurs PostgreSQL (`champ_historique`) ; jamais d'ici.

Trois sources, trois roles distincts, et l'ecran les separe pour cette raison :

 * `evenement` — ce que l'application a **fait**. Un enregistrement, une
   cotation, une habilitation modifiee.
 * `champ_historique` — ce qui a **change**, colonne par colonne, y compris
   quand la modification vient d'un SQL direct hors application. C'est ce qui
   remplit la colonne « avant / apres » du panneau de droite.
 * `journal_acces` — qui a seulement **regarde**. C'est celui qu'on ouvre quand
   une information a fuite.

Le second est joint au premier, et non presente a part : « quelqu'un a modifie
le delai » ne vaut rien ; « le delai est passe de 72 h a 48 h le 4 aout, par
A. Kouassi » vaut quelque chose.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.db import connection
from django.utils import timezone

from noyau.identite.modeles import Utilisateur, UtilisateurSession
from noyau.parametres.service import valeur as parametre

#: Les familles d'evenements que l'ecran propose en filtre, et le prefixe des
#: `type_evenement` qui les composent.
#:
#: La correspondance est **ici et nulle part ailleurs** : le front envoie le
#: libelle affiche (« Habilitation »), la base stocke des codes
#: (`profil_attribue`). Laisser le front deviner le prefixe l'aurait rendu
#: dependant du nommage interne des evenements.
FAMILLES: dict[str, tuple[str, ...]] = {
    "Enregistrement": ("courrier_enregistre", "piece_"),
    "Cotation": ("cotation_", "affectation_"),
    "Traitement": ("traitement_", "activite_", "avancement_", "tache_", "instruction_"),
    "Signature": ("signature_", "validation_", "depart_"),
    # `regle_` : les arbitrages de la zone H (`regle_tranchee`, `regle_modifiee`)
    # sont du parametrage. Sans ce prefixe ils tombaient dans « Traitement » par
    # repli, et l'auditeur qui filtre sur le parametrage rate exactement les
    # ecritures qu'il cherche — celles qui changent une regle de l'institution.
    "Paramétrage": ("parametre_", "regle_", "niveau_", "structure_", "circuit_", "mention_"),
    "Habilitation": (
        "compte_",
        "profil_",
        "perimetre_",
        "delegation_",
        "session_",
        "permission_",
    ),
}

#: Ce que le front nomme, en face de ce que la colonne `action` porte.
ACTIONS = {
    "consultation": "Consultation",
    "liste": "Consultation",
    "telechargement": "Téléchargement",
    "impression": "Impression",
    "export": "Export",
}

#: Les actions qui, a elles seules, appellent le regard de l'auditeur. Sortir
#: des donnees de l'application n'est pas la meme chose que les consulter :
#: c'est le geste apres lequel l'institution n'en a plus le controle.
ACTIONS_SIGNALEES = frozenset({"export", "impression", "telechargement"})


# =====================================================================
#  Journal des evenements
# =====================================================================


def journal_evenements(filtre: str = "Tous", limite: int = 200) -> dict:
    """
    Ce que l'application a fait, du plus recent au plus ancien.

    La limite n'est pas un confort : la table est partitionnee par annee et
    compte des millions de lignes en regime etabli. Un ecran qui les demanderait
    toutes ne s'afficherait jamais, et l'auditeur qui cherche un fait precis
    passe par le filtre, pas par le defilement.
    """
    conditions = ["1 = 1"]
    parametres: list[Any] = []

    prefixes = FAMILLES.get(filtre)
    if prefixes:
        conditions.append("(" + " OR ".join(["type_evenement LIKE %s"] * len(prefixes)) + ")")
        parametres.extend(f"{prefixe}%" for prefixe in prefixes)

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT id, survenu_le, type_evenement, libelle, detail,
                   acteur_id, objet_type, objet_id, courrier_id, donnees
            FROM evenement
            WHERE {" AND ".join(conditions)}
            ORDER BY survenu_le DESC
            LIMIT %s
            """,
            [*parametres, limite],
        )
        lignes = curseur.fetchall()

    acteurs = _acteurs({ligne[5] for ligne in lignes})
    differences = _differences_par_objet([(ligne[6], ligne[7], ligne[1]) for ligne in lignes])

    evenements = []
    for (
        identifiant,
        survenu_le,
        type_evenement,
        libelle,
        detail,
        acteur_id,
        objet_type,
        objet_id,
        courrier_id,
        donnees,
    ) in lignes:
        acteur = acteurs.get(acteur_id)
        evenements.append(
            {
                "id": identifiant,
                "heure": timezone.localtime(survenu_le).strftime("%H:%M"),
                "date": timezone.localtime(survenu_le).strftime("%d/%m/%Y"),
                "type": _famille(type_evenement),
                "libelle": libelle,
                # Le courrier n'existe pas encore cote serveur : la colonne est
                # portee par le schema, jamais renseignee. On ne fabrique pas
                # de reference.
                "courrier": None,
                "courrierId": courrier_id,
                "auteur": acteur["nom"] if acteur else "Système",
                "initiales": acteur["initiales"] if acteur else "SY",
                "poste": acteur["poste"] if acteur else "Traitement automatique",
                "champs": _champs(objet_type, objet_id, detail, donnees),
                "differences": differences.get((objet_type, objet_id), []),
            }
        )

    return {"compteurs": _compteurs_evenements(), "evenements": evenements}


def _famille(type_evenement: str) -> str:
    """
    A quelle famille appartient un evenement.

    « Traitement » est le repli, et non « Autre » : un evenement inconnu du
    tableau est presque toujours une ecriture metier d'un pilier neuf. Le
    ranger dans un fourre-tout l'aurait fait disparaitre du filtre le plus
    consulte.
    """
    for famille, prefixes in FAMILLES.items():
        if any(type_evenement.startswith(prefixe) for prefixe in prefixes):
            return famille
    return "Traitement"


def _champs(objet_type: str, objet_id: int, detail: str | None, donnees: str | dict | None) -> list:
    """
    Ce que l'evenement porte, en clair.

    L'objet vient toujours en tete : sans lui, une ligne « Profil attribue »
    ne dit pas a qui. Les `donnees` suivent, et seules les valeurs simples en
    sortent — une liste ou un dictionnaire imbriques s'afficheraient comme du
    JSON brut dans une colonne de tableau.

    **Le curseur brut rend le JSONB en chaine.** C'est `JSONField` qui decode,
    pas le pilote ; une requete SQL sur `evenement`, table `managed = False`
    lue au curseur, recupere le texte tel qu'il est stocke. D'ou le decodage
    ici, et le repli silencieux : un journal ne doit pas devenir illisible
    parce qu'une ligne porte une donnee mal formee.
    """
    champs = [{"libelle": "Objet", "valeur": f"{objet_type} #{objet_id}"}]

    if detail:
        champs.append({"libelle": "Détail", "valeur": detail})

    if isinstance(donnees, str):
        try:
            donnees = json.loads(donnees)
        except ValueError:
            donnees = None
    if not isinstance(donnees, dict):
        donnees = None

    for cle, valeur in (donnees or {}).items():
        if isinstance(valeur, (str, int, float, bool)):
            champs.append({"libelle": cle, "valeur": str(valeur)})

    return champs


def _differences_par_objet(objets: list[tuple[str, int, datetime]]) -> dict:
    """
    Les valeurs avant / apres, prises dans `champ_historique`.

    **La jointure se fait sur l'objet et la seconde**, pas sur l'evenement :
    les deux tables ne se connaissent pas. `champ_historique` est alimentee par
    declencheur — elle enregistre aussi ce qui a change hors application — et
    lui poser une cle etrangere vers `evenement` aurait rendu impossible
    d'enregistrer une modification faite en SQL direct, qui est justement ce
    qu'un auditeur cherche.

    La tolerance d'une seconde est le prix de cette independance. Elle peut
    rattacher a un evenement une modification concomitante faite par ailleurs ;
    c'est preferable a ne rien montrer.
    """
    if not objets:
        return {}

    clauses = []
    parametres: list[Any] = []
    for objet_type, objet_id, survenu_le in objets:
        clauses.append("(table_cible = %s AND ligne_id = %s AND survenu_le BETWEEN %s AND %s)")
        parametres.extend(
            [
                objet_type,
                objet_id,
                survenu_le - timedelta(seconds=1),
                survenu_le + timedelta(seconds=1),
            ]
        )

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT table_cible, ligne_id, colonne, valeur_avant, valeur_apres
            FROM champ_historique
            WHERE {" OR ".join(clauses)}
            ORDER BY survenu_le
            """,
            parametres,
        )
        lignes = curseur.fetchall()

    groupes: dict[tuple[str, int], list] = defaultdict(list)
    for table_cible, ligne_id, colonne, avant, apres in lignes:
        groupes[(table_cible, ligne_id)].append(
            {
                "champ": colonne,
                # « (vide) » et non une chaine vide : une cellule vide se lit
                # comme une donnee manquante, pas comme un champ efface.
                "avant": avant if avant is not None else "(vide)",
                "apres": apres if apres is not None else "(vide)",
            }
        )

    return groupes


def _compteurs_evenements() -> list[dict]:
    """
    Trois chiffres en tete d'ecran, et le troisieme est le seul qui compte.

    Une piste d'audit se juge sur ce qui lui manque : un evenement sans acteur
    identifie est une ecriture que personne n'endosse. Le socle l'interdit par
    declencheur (RNF-TRACE-01) ; le compteur verifie que le declencheur tient.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*) FILTER (WHERE survenu_le >= now() - interval '30 days'),
                   count(*) FILTER (WHERE survenu_le >= now() - interval '24 hours'),
                   count(*) FILTER (WHERE acteur_id IS NULL
                                      AND survenu_le >= now() - interval '30 days')
            FROM evenement
            """
        )
        mois, jour, sans_acteur = curseur.fetchone()

    return [
        {
            "libelle": "Événements sur 30 jours",
            "valeur": f"{mois:,}".replace(",", " "),
            "note": "Toutes familles confondues",
            "ton": "neutre",
        },
        {
            "libelle": "Dernières 24 heures",
            "valeur": f"{jour:,}".replace(",", " "),
            "note": "Activité du jour",
            "ton": "neutre",
        },
        {
            "libelle": "Sans acteur identifié",
            "valeur": str(sans_acteur),
            "note": (
                "Le socle l'interdit par déclencheur"
                if sans_acteur == 0
                else "Écritures que personne n'endosse — à examiner"
            ),
            "ton": "neutre" if sans_acteur == 0 else "danger",
        },
    ]


# =====================================================================
#  Journal des acces
# =====================================================================


def journal_acces(filtre: str = "Tous", limite: int = 200) -> dict:
    """
    Qui a regarde quoi.

    **Ce journal peut etre vide, et ce n'est pas une panne.**
    `noyau.journal.service.tracer_acces` n'est appelee que sur la lecture d'un
    objet sensible — c'est delibere : tracer chaque liste ferait grossir la
    table de plusieurs millions de lignes par mois sans rien apprendre a
    personne. Tant que le pilier courrier n'existe pas, la seule lecture
    sensible du depot est la fiche d'un agent.
    """
    conditions = ["1 = 1"]
    parametres: list[Any] = []

    if filtre == "Export":
        conditions.append("action IN ('export', 'impression', 'telechargement')")
    elif filtre == "Session confidentielle":
        conditions.append("objet_type = 'courrier_confidentiel'")
    elif filtre == "Signalé":
        # Le signalement se calcule apres coup (voir `_signaler`) : la requete
        # ramene large et le filtre s'applique en Python. C'est acceptable a
        # cette limite ; ce ne le serait plus a dix mille lignes.
        pass

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT id, survenu_le, acteur_id, objet_type, objet_id, action, adresse_ip
            FROM journal_acces
            WHERE {" AND ".join(conditions)}
            ORDER BY survenu_le DESC
            LIMIT %s
            """,
            [*parametres, limite],
        )
        lignes = curseur.fetchall()

    acteurs = _acteurs({ligne[2] for ligne in lignes})
    volumes = _volumes_par_acteur()
    seuil = _seuil_volume(volumes)

    acces = []
    for identifiant, survenu_le, acteur_id, objet_type, objet_id, action, adresse in lignes:
        acteur = acteurs.get(acteur_id)
        alerte, motif = _signaler(
            action=action,
            objet_type=objet_type,
            volume=volumes.get(acteur_id, 0),
            seuil=seuil,
        )

        if filtre == "Signalé" and not alerte:
            continue

        acces.append(
            {
                "id": identifiant,
                "heure": timezone.localtime(survenu_le).strftime("%H:%M"),
                "date": timezone.localtime(survenu_le).strftime("%d/%m/%Y"),
                "agent": acteur["nom"] if acteur else "Compte supprimé",
                "initiales": acteur["initiales"] if acteur else "??",
                "poste": acteur["poste"] if acteur else "—",
                "objet": f"{objet_type} #{objet_id}" if objet_id else objet_type,
                "session": acteur["session"] if acteur else "—",
                "action": ACTIONS.get(action, action.capitalize()),
                "controle": "Signalé" if alerte else "Conforme",
                "champs": [
                    {"libelle": "Objet", "valeur": objet_type, "alerte": False},
                    {
                        "libelle": "Adresse IP",
                        "valeur": adresse or "Non enregistrée",
                        "alerte": False,
                    },
                    {
                        "libelle": "Volume 7 j",
                        "valeur": f"{volumes.get(acteur_id, 0)} consultations",
                        "alerte": volumes.get(acteur_id, 0) > seuil,
                    },
                ],
                "motif": motif,
                "alerte": alerte,
                "activite": _activite_de(acteur_id),
            }
        )

    return {"acces": acces, "signales": sum(1 for a in acces if a["alerte"])}


def _signaler(*, action: str, objet_type: str, volume: int, seuil: int) -> tuple[bool, str]:
    """
    Ce qui appelle le regard de l'auditeur, et pourquoi.

    Trois motifs, dans l'ordre de gravite. Le motif est **rendu en clair** :
    une pastille « Signalé » sans explication ne produit qu'un soupcon, et
    l'auditeur qui la voit doit pouvoir juger sur place plutot que d'ouvrir une
    enquete pour un export legitime.

    Le troisieme motif — le volume — repose sur un seuil sans source, tenu dans
    `parametre` (`tracabilite.facteur_volume_anormal`, statut `hypothese`).
    Voir A23.
    """
    if objet_type == "courrier_confidentiel":
        return True, (
            "Consultation d'un courrier de la session confidentielle. "
            "Toute lecture y est signalée par construction, quel que soit le lecteur."
        )

    if action in ACTIONS_SIGNALEES:
        return True, (
            f"{ACTIONS.get(action, action)} : la donnée sort de l'application. "
            "Le geste est légitime, sa trace est conservée."
        )

    if volume > seuil:
        return True, (
            f"{volume} consultations sur sept jours, au-delà du seuil de {seuil}. "
            "Un volume seul ne prouve rien — il désigne une activité à expliquer."
        )

    return False, "Consultation conforme au périmètre de l'agent."


def _volumes_par_acteur() -> dict[int, int]:
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT acteur_id, count(*)
            FROM journal_acces
            WHERE survenu_le >= now() - interval '7 days'
            GROUP BY acteur_id
            """
        )
        return dict(curseur.fetchall())


def _seuil_volume(volumes: dict[int, int]) -> int:
    """
    Au-dela de combien de consultations un volume devient-il anormal.

    Un seuil absolu ne veut rien dire : l'agent du courrier central consulte
    cent fois par jour, un directeur trois fois par semaine. Le seuil est donc
    **relatif a la mediane** des agents actifs, multipliee par un facteur.

    Le facteur, lui, n'a aucune source — c'est A23. Il vit dans `parametre`
    pour etre corrigible sans redeploiement.
    """
    facteur = parametre("tracabilite.facteur_volume_anormal", 3)

    actifs = sorted(v for v in volumes.values() if v > 0)
    if not actifs:
        return 0

    mediane = actifs[len(actifs) // 2]
    return int(mediane * facteur)


def _activite_de(acteur_id: int | None) -> list[dict]:
    """
    Ce que l'agent a fait sur sept jours, par action.

    La part est rendue en pourcentage **du total de l'agent**, pas de
    l'institution : le panneau repond a « que fait cette personne », pas a
    « quelle place tient-elle ».
    """
    if acteur_id is None:
        return []

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT action, count(*)
            FROM journal_acces
            WHERE acteur_id = %s AND survenu_le >= now() - interval '7 days'
            GROUP BY action
            ORDER BY count(*) DESC
            """,
            [acteur_id],
        )
        lignes = curseur.fetchall()

    total = sum(nombre for _, nombre in lignes)
    if total == 0:
        return []

    return [
        {
            "libelle": ACTIONS.get(action, action.capitalize()),
            "valeur": str(nombre),
            "part": f"{round(nombre * 100 / total)}%",
            "alerte": action in ACTIONS_SIGNALEES,
        }
        for action, nombre in lignes
    ]


# =====================================================================
#  Outils
# =====================================================================


def _acteurs(identifiants: set[int | None]) -> dict[int, dict]:
    """
    Qui sont les agents cites, en une requete.

    Les journaux portent `acteur_id` en `BIGINT` nu, sans cle etrangere : c'est
    voulu au socle — supprimer un compte ne doit pas pouvoir effacer sa trace,
    et une cle etrangere l'aurait soit empeche, soit propage. La contrepartie
    est ici : la jointure se fait a la main, et un identifiant sans compte
    correspondant est normal.
    """
    connus = {i for i in identifiants if i is not None}
    if not connus:
        return {}

    agents = Utilisateur.objects.filter(pk__in=connus).select_related("poste", "structure")

    # La session courrier en une requete pour tout le lot : la demander agent
    # par agent ferait N requetes sur un ecran qui en affiche deux cents.
    sessions = dict(
        UtilisateurSession.objects.filter(utilisateur_id__in=connus, retire_le__isnull=True)
        .select_related("session")
        .values_list("utilisateur_id", "session__libelle")
    )

    return {
        agent.pk: {
            "nom": agent.nom_complet,
            "initiales": agent.initiales,
            "poste": agent.poste.libelle if agent.poste else "—",
            "session": sessions.get(agent.pk, "—"),
        }
        for agent in agents
    }


# =====================================================================
#  Historique des champs — I-03
# =====================================================================

#: Les tables portant le declencheur `historiser_champs()`, avec le nom sous
#: lequel l'ecran les designe.
#:
#: La liste est **ecrite ici et verifiee par un test** contre `pg_trigger`.
#: Elle ne peut pas etre deduite a l'execution sans interroger le catalogue
#: systeme a chaque appel, et un ecran qui proposerait une table non historisee
#: renverrait toujours zero ligne — ce qui se lit « rien n'a change » et non
#: « rien n'est trace ». Les deux ne se ressemblent pas du tout.
TABLES_HISTORISEES: dict[str, str] = {
    "courrier": "Courrier",
    "cotation": "Cotation",
    "cotation_suivi": "Cotation pour suivi",
    "structure": "Structure",
    "activite": "Activité",
    "paa": "Plan annuel d'activités",
    "tache": "Tâche",
    "instruction_activite": "Instruction sur activité",
    "seance": "Séance",
    "engagement_structure": "Engagement de structure",
    "disponibilite": "Disponibilité",
    "conge_periode": "Congé",
}


def historique_champs(
    *,
    table_cible: str | None = None,
    ligne_id: int | None = None,
    hors_application: bool = False,
    limite: int = 200,
) -> dict:
    """
    Ce qui a change, colonne par colonne — I-03.

    **Ce n'est pas le journal des evenements sous un autre angle.** Les deux
    tables sont alimentees par des chemins independants : `evenement` par le
    code applicatif, `champ_historique` par un declencheur PostgreSQL. Une
    modification faite en SQL direct — correction en base, script de reprise,
    intervention d'un prestataire — laisse une ligne ici et **aucune** la-bas.

    C'est tout l'interet de l'ecran, et la raison du drapeau `horsApplication` :
    une valeur qui a change sans qu'aucun evenement ne l'explique est ce qu'un
    auditeur cherche en premier.

    `limite` est bornee par l'appelant. La table compte des millions de lignes
    par an en regime etabli, et n'est jamais parcourue en entier.
    """
    conditions = ["TRUE"]
    parametres: list[Any] = []

    if table_cible:
        conditions.append("h.table_cible = %s")
        parametres.append(table_cible)
    if ligne_id is not None:
        conditions.append("h.ligne_id = %s")
        parametres.append(ligne_id)

    # La correlation avec `evenement` se fait sur l'objet et la seconde, comme
    # dans `_differences_par_objet` : les deux tables ne se connaissent pas, et
    # leur poser une cle etrangere aurait rendu impossible d'enregistrer une
    # modification faite hors application — precisement ce qu'on cherche ici.
    #
    # `table_cible = objet_type` suppose que le pilier nomme son objet comme sa
    # table. C'est le cas partout au depot, et le test le verifie sur les
    # ecritures reelles.
    correlation = """
        NOT EXISTS (
            SELECT 1 FROM evenement e
            WHERE e.objet_type = h.table_cible
              AND e.objet_id = h.ligne_id
              AND e.survenu_le BETWEEN h.survenu_le - interval '1 second'
                                   AND h.survenu_le + interval '1 second'
        )
    """
    if hors_application:
        conditions.append(correlation)

    with connection.cursor() as curseur:
        curseur.execute(
            f"""
            SELECT h.id, h.survenu_le, h.table_cible, h.ligne_id, h.colonne,
                   h.valeur_avant, h.valeur_apres, h.acteur_id,
                   {correlation} AS hors_application
            FROM champ_historique h
            WHERE {" AND ".join(conditions)}
            ORDER BY h.survenu_le DESC, h.id DESC
            LIMIT %s
            """,
            [*parametres, limite],
        )
        lignes = curseur.fetchall()

    acteurs = _acteurs({ligne[7] for ligne in lignes})

    modifications = []
    for (
        identifiant,
        survenu_le,
        table,
        ligne,
        colonne,
        avant,
        apres,
        acteur_id,
        isole,
    ) in lignes:
        local = timezone.localtime(survenu_le)
        acteur = acteurs.get(acteur_id) if acteur_id else None
        modifications.append(
            {
                "id": identifiant,
                "date": local.strftime("%d/%m/%Y"),
                "heure": local.strftime("%H:%M:%S"),
                "table": table,
                "tableLibelle": TABLES_HISTORISEES.get(table, table),
                "ligneId": ligne,
                # La colonne est rendue telle qu'elle est en base. Traduire
                # `date_echeance` en « Échéance » supposerait un dictionnaire de
                # plusieurs centaines d'entrees, invente pour la plupart — et
                # un auditeur qui recoupe avec la base veut le nom de la
                # colonne, pas une paraphrase.
                "colonne": colonne,
                # « (vide) » et non une chaine vide : une cellule vide se lit
                # comme une donnee manquante, pas comme un champ efface.
                "avant": avant if avant is not None else "(vide)",
                "apres": apres if apres is not None else "(vide)",
                "auteur": acteur["nom"] if acteur else "Traitement automatique",
                "initiales": acteur["initiales"] if acteur else "SY",
                "poste": acteur["poste"] if acteur else "—",
                "horsApplication": isole,
            }
        )

    return {
        "tables": _tables_historisees(),
        "modifications": modifications,
        # Compte sur ce qui est rendu, et non sur la table entiere : un total
        # global exigerait un parcours complet des partitions a chaque
        # affichage, pour un chiffre que personne ne peut recouper avec la
        # liste qu'il a sous les yeux.
        "horsApplication": sum(1 for m in modifications if m["horsApplication"]),
    }


def _tables_historisees() -> list[dict]:
    """
    Les tables tracees, avec le volume de leur historique.

    Le compte est rendu **meme a zero**, et c'est le point : une table livree
    mais jamais modifiee doit apparaitre dans le selecteur. L'omettre ferait
    croire qu'elle n'est pas tracee, ce qui est l'inverse de la verite.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT table_cible, count(*)
            FROM champ_historique
            GROUP BY table_cible
            """
        )
        volumes = dict(curseur.fetchall())

    return [
        {"cle": cle, "libelle": libelle, "modifications": volumes.get(cle, 0)}
        for cle, libelle in TABLES_HISTORISEES.items()
    ]

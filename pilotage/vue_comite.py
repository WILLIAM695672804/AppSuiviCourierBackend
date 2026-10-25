"""
La vue d'ensemble du Comite de direction — §3.2.

**Le Comite de direction est le conseil des directeurs**, une instance ou ils
siegent ensemble, et non un poste occupe par quelqu'un. Cette restitution est
donc celle de l'instance : elle est calculee sur toutes les directions.

Ce qu'elle en *montre* a change. Les scores sortaient direction par direction,
une colonne chacune ; passe quelques directions le graphique devenait illisible
et ne servait plus personne. Le college se lit maintenant par agregats — score
moyen, dispersion, reperes — et le membre connecte y trouve sa propre position,
score et rang. Voir l'ADR 026.

Ce qui la separe de la vue du Directeur general tient en une phrase. Celle-ci
repond a « ou se situent les directions les unes par rapport aux autres, et
laquelle decroche ? » ; celle-la repond a « ou en est l'institution ? ». Le
Comite compare, le Directeur general constate.

Le perimetre est institutionnel, et c'est une derogation assumee au
cloisonnement par structure — la meme que celle du Directeur general. Un conseil
de directeurs qui ne verrait pas les directions ne delibererait sur rien. La
derogation tient parce que la reponse n'expose que des **agregats de
structure** : aucun objet nominatif, aucun courrier, aucun agent.
"""

from datetime import date

from django.db import connection
from django.utils import timezone

from noyau.calendrier import MOIS_COURTS, libelle_mois, mois_precedent
from noyau.identite.modeles import Utilisateur
from performance import matrice as calcul
from pilotage import mesures

INSTITUTION = "Port autonome de Douala"

#: L'instance dont le Comite suit ses propres decisions.
INSTANCE_CODIR = "codir"

#: Les etats d'execution d'une decision, dans l'ordre ou ils se lisent : ce qui
#: est fait, ce qui avance, ce qui a decroche.
ETATS_DECISION = [
    ("execute", "Exécutées"),
    ("en_cours", "En cours"),
    ("en_retard", "En retard"),
]


def vue_ensemble(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict:
    """L'ecran entier du Comite de direction."""
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)

    classement = calcul.matrice(utilisateur, annee, mois)["lignes"]

    return {
        "institution": INSTITUTION,
        # Le sigle du membre designe la structure dont le bloc de position est
        # servi. Un directeur siege au Comite sans cesser de repondre de sa
        # branche : c'est de celle-la qu'il vient voir la place.
        "structureSigle": utilisateur.structure.code if utilisateur.structure else None,
        # ISO, et non « 16 aout 2026 » : le front applique `formaterDateHeure`
        # a ce champ, et `new Date("16 aout 2026")` rend une date invalide qui
        # fait tomber l'ecran entier. Un mois ecrit en toutes lettres n'est pas
        # une donnee, c'est un affichage — et l'affichage appartient au front.
        # Voir docs/pieges.md.
        "actualiseLe": timezone.now().isoformat(),
        "exercice": f"Exercice {jour.year}",
        "reperes": _reperes(classement, annee, mois, jour),
        "positionMembre": _position_membre(classement, utilisateur),
        "decisionsParEtat": _decisions_par_etat(),
        "activitesParEtat": _activites_par_etat(),
        "evolutionScoreMoyen": _evolution_score_moyen(utilisateur, annee, mois),
        "dispersion": _dispersion(utilisateur, annee, mois),
    }


# =====================================================================
#  La position du membre
# =====================================================================


def _position_membre(classement: list[dict], utilisateur: Utilisateur) -> dict | None:
    """
    La place de la direction du membre connecte, et elle seule.

    Le classement entier reste calcule — la moyenne, la dispersion et les
    reperes en vivent — mais il ne sort plus colonne par colonne. Passe quelques
    directions, l'histogramme des scores cesse d'etre lisible : les colonnes se
    serrent, les sigles se chevauchent, et le membre n'y retrouve plus la
    sienne. Ce qu'il vient chercher tient en deux nombres, son score et son
    rang ; le collegue de la colonne d'a cote, il le lit dans la moyenne et dans
    la dispersion, qui ne dependent pas de la largeur de l'ecran.

    Sort a `null` a deux titres : le membre ne dirige aucune structure, ou la
    sienne n'entre pas au classement du mois. La page le dit alors en toutes
    lettres plutot que d'afficher un rang invente.
    """
    if utilisateur.structure is None:
        return None

    ligne = next(
        (c for c in classement if c["structureSigle"] == utilisateur.structure.code),
        None,
    )
    if ligne is None:
        return None

    return {
        "structureSigle": ligne["structureSigle"],
        "structureLibelle": ligne["structureLibelle"],
        "scoreGlobal": ligne["scoreGlobal"],
        "feu": ligne["feu"],
        "rang": ligne["rang"],
        "rangPrecedent": ligne["rangPrecedent"],
        "totalStructures": len(classement),
        "moyenneCollege": _moyenne(classement),
    }


# =====================================================================
#  La bande haute
# =====================================================================


def _reperes(classement: list[dict], annee: int, mois: int, jour: date) -> list[dict]:
    moyenne = _moyenne(classement)
    ecart = (
        round(classement[0]["scoreGlobal"] - classement[-1]["scoreGlobal"], 1)
        if len(classement) > 1
        else None
    )
    execution = mesures.execution_activites(a_la_date=jour)
    en_retard = mesures.decisions_en_retard()

    return [
        {
            "libelle": "Directions classées",
            "valeur": str(len(classement)),
            "note": libelle_mois(annee, mois),
        },
        {
            "libelle": "Score moyen du collège",
            "valeur": f"{moyenne} / 100" if moyenne is not None else "Non mesuré",
            "note": "moyenne des scores globaux",
        },
        {
            "libelle": "Écart entre extrêmes",
            "valeur": f"{ecart} pts" if ecart is not None else "Non mesuré",
            "note": (
                f"{classement[0]['structureSigle']} devant {classement[-1]['structureSigle']}"
                if len(classement) > 1
                else "une seule direction classée"
            ),
        },
        {
            "libelle": "Exécution des activités",
            "valeur": f"{execution} %" if execution is not None else "Non mesuré",
            "note": "toutes directions confondues",
        },
        {
            "libelle": "Décisions en retard",
            "valeur": str(en_retard),
            "note": "échéance dépassée, décision non exécutée",
        },
        {
            "libelle": "Activités critiques",
            "valeur": str(mesures.activites_critiques()),
            "note": "en retard et sous contrainte échue (§20)",
        },
    ]


def _moyenne(classement: list[dict]) -> float | None:
    if not classement:
        return None
    return round(sum(ligne["scoreGlobal"] for ligne in classement) / len(classement), 1)


# =====================================================================
#  Les repartitions
# =====================================================================


def _decisions_par_etat() -> list[dict]:
    """
    Les decisions du Comite, par etat d'execution.

    Les seules decisions du CODIR : le Comite delibere sur ce qu'il a decide,
    pas sur ce que le Conseil d'administration a prescrit — celles-la relevent
    d'une autre seance.
    """
    engagements = mesures.engagements_vivants().filter(instance=INSTANCE_CODIR)
    etats = mesures.etats_engagements(engagements)

    comptes = {code: 0 for code, _ in ETATS_DECISION}
    for etat in etats.values():
        if etat in comptes:
            comptes[etat] += 1
        else:
            # Un etat que la vue `v_engagement_etat` ajouterait sans qu'on le
            # sache tombe dans « en cours » plutot que de disparaitre du total.
            comptes["en_cours"] += 1

    return [{"libelle": libelle, "valeur": comptes[code]} for code, libelle in ETATS_DECISION]


def _activites_par_etat() -> list[dict]:
    """
    Les activites de toutes les directions, par etat affiche.

    L'etat affiche vient de `v_activite_etat` : « en retard » et « programmee »
    ne sont pas stockes, ils se deduisent des dates (arbitrage n° 2 du pilier
    activites). Compter la colonne `etat` aurait montre zero retard.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT v.etat_affiche, count(*)
            FROM v_activite_etat v
            JOIN activite a ON a.id = v.id
            WHERE a.invalide_le IS NULL
            GROUP BY v.etat_affiche
            ORDER BY count(*) DESC
            """
        )
        lignes = curseur.fetchall()

    libelles = {
        "en_cours": "En cours",
        "realisee": "Réalisées",
        "suspendue": "Suspendues",
        "en_retard": "En retard",
        "programmee": "Programmées",
    }
    return [{"libelle": libelles.get(etat, etat), "valeur": nombre} for etat, nombre in lignes]


# =====================================================================
#  Les deux courbes
# =====================================================================


def _evolution_score_moyen(utilisateur: Utilisateur, annee: int, mois: int) -> list[dict]:
    """
    Le score moyen des directions, mois par mois.

    Un classement ne dit pas si l'ensemble progresse : deux directions peuvent
    echanger leurs rangs pendant que toutes decrochent. C'est ce que cette
    courbe montre et que le classement cache.
    """
    points = []
    for annee_serie, mois_serie in mesures.mois_glissants(annee, mois, 6):
        lignes = calcul.matrice(utilisateur, annee_serie, mois_serie)["lignes"]
        moyenne = _moyenne(lignes)
        if moyenne is not None:
            points.append({"mois": MOIS_COURTS[mois_serie - 1], "valeur": moyenne})
    return points


def _dispersion(utilisateur: Utilisateur, annee: int, mois: int) -> list[dict]:
    """
    L'ecart entre la direction la mieux notee et la moins bien notee.

    La dispersion du college : elle dit si l'institution avance groupee ou si un
    peloton se detache. Un mois ou une seule direction est classee ne produit
    pas de point — un ecart de zero se lirait comme une egalite parfaite.
    """
    points = []
    for annee_serie, mois_serie in mesures.mois_glissants(annee, mois, 6):
        lignes = calcul.matrice(utilisateur, annee_serie, mois_serie)["lignes"]
        if len(lignes) > 1:
            ecart = lignes[0]["scoreGlobal"] - lignes[-1]["scoreGlobal"]
            points.append({"mois": MOIS_COURTS[mois_serie - 1], "valeur": round(ecart, 1)})
    return points

"""
Le calcul de la matrice de scoring — §2.

« La matrice de scoring administratif des structures agrege, sur une base
mensuelle, les resultats lies a l'execution des activites, au traitement du
courrier et des dossiers, ainsi qu'a la conformite aux rituels. Elle produit
ainsi un classement et une evaluation globale de chaque structure. »

**Le score se recalcule, il ne se stocke pas** (ADR 010). Chaque lecture
interroge les piliers sources ; il n'existe aucune table de scores a
resynchroniser, donc aucune possibilite qu'un chiffre affiche contredise sa
source.

**Le mois en cours n'est pas comparable.** Une structure dont le rapport est du
le 5 du mois suivant n'a rien depose le 12 du mois courant : la classer
reviendrait a la punir d'un delai qu'elle respecte. La matrice le dit —
`provisoire` — plutot que de refuser de s'afficher, parce que la DSR a besoin
de voir venir.

**Un critere sans source ne vaut pas zero.** Une structure sans activite au
plan, sans courrier cloture dans le mois ou sans obligation echue sort a `None`
sur ce critere, feu « inconnu », et il est **retire du calcul du score global**
apres renormalisation des poids. Le compter pour zero aurait puni l'absence de
matiere comme un echec.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import connection

from noyau.feu import feu
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import Structure
from noyau.organisation.tete import regrouper
from performance.modeles import Critere


def bornes(annee: int, mois: int) -> tuple[date, date]:
    """Le premier et le dernier jour du mois observe."""
    return date(annee, mois, 1), date(annee, mois, monthrange(annee, mois)[1])


def est_provisoire(annee: int, mois: int) -> bool:
    """
    Vrai tant que le mois n'est pas revolu.

    Le classement d'un mois en cours n'est pas comparable d'une structure a
    l'autre : celle dont l'echeance tombe le 25 a deja ete mesuree, celle dont
    l'echeance tombe le 5 du mois suivant ne l'a pas ete.
    """
    _, fin = bornes(annee, mois)
    return date.today() <= fin


def lignes_classees(utilisateur: Utilisateur) -> list[tuple[Structure, list[int]]]:
    """
    Ce que chaque ligne du classement porte : la structure qui la nomme, et
    les structures sur lesquelles ses criteres se mesurent.

    **Pour qui consolide, une ligne par tete de structure**, et le score se
    **recalcule sur tout le sous-arbre** : les activites, courriers et
    obligations de la DSI, de DSI-ET et de DSI-IN sont comptes ensemble, comme
    si la direction etait une seule structure. Ce n'est pas une moyenne de
    moyennes — un score ne s'additionne pas, et moyenner aurait fait peser un
    secretariat de trois agents autant que la Capitainerie. Arbitrage de
    l'utilisateur du 31 aout 2026.

    Pour un directeur, rien ne change : une ligne par structure classee, chacune
    mesuree sur elle-meme. La consolidation porte sur le regroupement, jamais
    sur l'acces — c'est le perimetre qui borne, et lui seul (D5).

    Le sommet de la ligne hierarchique et les organes deliberants sortent du
    classement consolide : ils n'ont pas de tete, et une Direction generale
    comparee a ses propres directions ne se compare a rien.
    """
    return [
        (porteuse, sorted(s.pk for s in membres))
        for porteuse, membres in regrouper(utilisateur, structures_classees())
    ]


def matrice(utilisateur: Utilisateur, annee: int, mois: int) -> dict:
    """Le classement du mois, structure par structure — voir
    `lignes_classees` pour ce qui entre au classement, et a quelle maille."""
    criteres = list(Critere.objects.filter(actif=True))

    lignes: list[dict[str, Any]] = []
    for structure, perimetre in lignes_classees(utilisateur):
        notes = _notes(perimetre, criteres, annee, mois)
        lignes.append(
            {
                "structureSigle": structure.code,
                "structureLibelle": structure.libelle,
                "scoreGlobal": _score_global(notes, criteres),
                "criteres": [
                    {
                        "code": critere.code,
                        "libelle": critere.libelle,
                        "poids": critere.poids,
                        "note": notes[critere.code]["note"] or 0,
                        "feu": feu(notes[critere.code]["note"]),
                    }
                    for critere in criteres
                ],
            }
        )

    lignes = _classer(lignes)
    _poser_le_rang_precedent(lignes, utilisateur, annee, mois, criteres)

    scores: list[float] = [float(ligne["scoreGlobal"]) for ligne in lignes]
    moyenne = round(sum(scores) / len(scores), 1) if scores else 0.0

    return {
        "periode": {"granularite": "mois", "annee": annee, "rang": mois},
        "provisoire": est_provisoire(annee, mois),
        "lignes": lignes,
        "compteurs": _compteurs(lignes, moyenne),
        "moyenneInstitution": moyenne,
    }


def fiche(utilisateur: Utilisateur, sigle: str, annee: int, mois: int) -> dict | None:
    """
    La decomposition du score d'une structure.

    **Un score global sans sa decomposition est indefendable.** Un directeur
    classe neuvieme doit pouvoir voir lequel des criteres l'y place, sans quoi
    le classement ne produit que du ressentiment. C'est la seule raison d'etre
    de cet ecran.
    """
    complete = matrice(utilisateur, annee, mois)
    ligne = next((c for c in complete["lignes"] if c["structureSigle"] == sigle), None)
    if ligne is None:
        return None

    # La fiche se mesure sur le meme perimetre que la ligne du classement,
    # sinon la decomposition contredirait le score qu'elle explique.
    perimetre = next(
        (pks for structure, pks in lignes_classees(utilisateur) if structure.code == sigle),
        None,
    )
    if perimetre is None:
        return None

    criteres = list(Critere.objects.filter(actif=True))
    notes = _notes(perimetre, criteres, annee, mois)

    return {
        "structureSigle": ligne["structureSigle"],
        "structureLibelle": ligne["structureLibelle"],
        "periode": complete["periode"],
        "rang": ligne["rang"],
        "rangPrecedent": ligne["rangPrecedent"],
        "totalStructures": len(complete["lignes"]),
        "scoreGlobal": ligne["scoreGlobal"],
        "scorePrecedent": _score_du_mois_precedent(perimetre, annee, mois),
        "feu": ligne["feu"],
        "moyenneInstitution": complete["moyenneInstitution"],
        "criteres": [
            {
                "code": critere.code,
                "libelle": critere.libelle,
                "poids": critere.poids,
                "note": notes[critere.code]["note"] or 0,
                "feu": feu(notes[critere.code]["note"]),
                "sousIndicateurs": notes[critere.code]["sous"],
            }
            for critere in criteres
        ],
        "historique": _historique(perimetre, criteres, annee, mois),
    }


# =====================================================================
#  Les criteres
# =====================================================================


def _notes(perimetre: list[int], criteres: list[Critere], annee: int, mois: int) -> dict:
    """
    La note de chaque critere, et ce qui la compose.

    Un critere inconnu de `MESURES` rend `None` et le dit dans son sous-
    indicateur. C'est voulu : la DSR peut creer un critere avant que quiconque
    sache le mesurer, et l'ecran doit alors afficher « non mesuré » et non
    « zéro ».
    """
    resultats = {}
    for critere in criteres:
        mesure = MESURES.get(critere.code)
        if mesure is None:
            resultats[critere.code] = {
                "note": None,
                "sous": [
                    {
                        "libelle": critere.libelle,
                        "valeur": "—",
                        "cible": "—",
                        "taux": 0,
                        "feu": "inconnu",
                    }
                ],
            }
            continue
        resultats[critere.code] = mesure(perimetre, annee, mois)
    return resultats


def _critere_activites(perimetre: list[int], annee: int, mois: int) -> dict:
    """
    Ce que la structure a inscrit a son plan d'actions, et ce qu'elle en a fait.

    Deux sous-indicateurs, et le second n'est pas redondant : une structure peut
    n'avoir aucune activite en retard et un avancement moyen de 20 % — cela
    signifie que ses echeances sont lointaines, pas qu'elle avance.

    `v_activite_etat` porte l'etat **affiche**, qui deduit « en retard » des
    dates (arbitrage n° 2 du pilier activites). C'est cette vue qu'on
    interroge, et non la colonne `etat` : elle ne connait pas le retard.
    """
    _, fin = bornes(annee, mois)

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE v.etat_affiche <> 'en_retard'),
                   coalesce(avg(v.avancement_retenu), 0)
            FROM v_activite_etat v
            JOIN activite a ON a.id = v.id
            WHERE v.structure_id = ANY(%s)
              AND a.invalide_le IS NULL
              AND a.date_debut <= %s
            """,
            [perimetre, fin],
        )
        total, a_l_heure, avancement = curseur.fetchone()

    if not total:
        return {
            "note": None,
            "sous": [
                {
                    "libelle": "Activités au plan d'actions",
                    "valeur": "Aucune",
                    "cible": "—",
                    "taux": 0,
                    "feu": "inconnu",
                }
            ],
        }

    taux_heure = round(a_l_heure / total * 100, 1)
    taux_avancement = round(float(avancement), 1)

    return {
        "note": round((taux_heure + taux_avancement) / 2, 1),
        "sous": [
            {
                "libelle": "Activités menées à l'heure",
                "valeur": f"{a_l_heure} / {total}",
                "cible": f"{total} / {total}",
                "taux": taux_heure,
                "feu": feu(taux_heure),
            },
            {
                "libelle": "Avancement moyen du plan",
                "valeur": f"{taux_avancement} %",
                "cible": "100 %",
                "taux": taux_avancement,
                "feu": feu(taux_avancement),
            },
        ],
    }


def _critere_courrier(perimetre: list[int], annee: int, mois: int) -> dict:
    """
    Les courriers clotures dans le mois, et la part qui l'a ete dans le delai.

    **Mesure depuis le 27 aout 2026**, quand la cloture a eu une route. Jusque-la
    ce critere sortait a `None` avec la mention « le pilier courrier n'est pas en
    service » : c'etait vrai, aucun geste ne refermait un courrier.

    La date se lit sur `courrier.cloture_le`, que la contrainte
    `courrier_cloture_coherente` lie au statut — l'un ne va pas sans l'autre
    (ADR 037). `modifie_le` n'aurait pas convenu : il bouge a chaque correction
    de saisie.

    Le denominateur ne retient que les courriers **a echeance**. Un courrier sans
    delai n'est ni a l'heure ni en retard, et le compter au numerateur aurait
    recompense la structure a qui l'on ne fixe rien.
    """
    debut, fin = bornes(annee, mois)

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE c.cloture_le::date <= c.date_limite)
              FROM courrier c
             WHERE c.cloture_le >= %s
               AND c.cloture_le < (%s::date + INTERVAL '1 day')
               AND c.invalide_le IS NULL
               AND c.date_limite IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM cotation ct
                     JOIN cotation_structure cs ON cs.cotation_id = ct.id
                    WHERE ct.courrier_id = c.id
                      AND ct.invalide_le IS NULL
                      AND cs.structure_id = ANY(%s)
               )
            """,
            [debut, fin, perimetre],
        )
        total, dans_le_delai = curseur.fetchone()

    if not total:
        return {
            "note": None,
            "sous": [
                {
                    "libelle": "Courriers traités dans le délai",
                    "valeur": "Aucun courrier clôturé ce mois-ci",
                    "cible": "—",
                    "taux": 0,
                    "feu": "inconnu",
                }
            ],
        }

    taux = round(dans_le_delai / total * 100, 1)
    return {
        "note": taux,
        "sous": [
            {
                "libelle": "Courriers traités dans le délai",
                "valeur": f"{dans_le_delai} / {total}",
                "cible": f"{total} / {total}",
                "taux": taux,
                "feu": feu(taux),
            }
        ],
    }


def _critere_rituels(perimetre: list[int], annee: int, mois: int) -> dict:
    """
    Les productions attendues au calendrier officiel, deposees a l'echeance.

    **Une obligation non deposee compte pour zero, jamais comme absente.** Le
    contraire aurait recompense la structure qui ne depose rien : sa moyenne se
    serait calculee sur un denominateur vide, donc parfaite.

    Les obligations retenues sont celles dont l'**echeance** tombe dans le
    mois, et non celles dont la periode couvre le mois : c'est l'echeance qui
    engage, et le rapport de juillet est du le 5 aout.
    """
    debut, fin = bornes(annee, mois)

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE depose_le IS NOT NULL AND depose_le <= echeance)
            FROM obligation
            WHERE structure_id = ANY(%s) AND echeance BETWEEN %s AND %s
            """,
            [perimetre, debut, fin],
        )
        dues, a_temps = curseur.fetchone()

    if not dues:
        return {
            "note": None,
            "sous": [
                {
                    "libelle": "Productions attendues",
                    "valeur": "Aucune sur la période",
                    "cible": "—",
                    "taux": 0,
                    "feu": "inconnu",
                }
            ],
        }

    taux = round(a_temps / dues * 100, 1)
    return {
        "note": taux,
        "sous": [
            {
                "libelle": "Productions déposées à l'échéance",
                "valeur": f"{a_temps} / {dues}",
                "cible": f"{dues} / {dues}",
                "taux": taux,
                "feu": feu(taux),
            }
        ],
    }


#: Ce que chaque critere sait mesurer, et avec quoi.
#:
#: La correspondance est **ici et nulle part ailleurs**. Un critere cree en base
#: sans etre inscrit dans cette table rend une note inconnue — ce qui est le bon
#: comportement : la DSR peut decider qu'un axe compte avant que quiconque sache
#: le mesurer, et l'ecran doit alors afficher « non mesuré » et non « zéro ».
MESURES = {
    "ACT": _critere_activites,
    "COUR": _critere_courrier,
    "RIT": _critere_rituels,
}


# =====================================================================
#  Agregation et classement
# =====================================================================


def _score_global(notes: dict, criteres: list[Critere]) -> float:
    """
    La moyenne ponderee, **renormalisee sur les criteres mesures**.

    Un critere sans source est retire du calcul, poids compris. C'est ce qui
    distingue « on ne sait pas » de « c'est nul », et la difference n'est pas
    theorique : une structure a qui l'on n'a fixe aucun delai de courrier, ou
    qui n'en a cloture aucun ce mois-ci, plafonnerait aux deux tiers de sa note
    sans avoir rien fait de mal.
    """
    retenus = [c for c in criteres if notes[c.code]["note"] is not None]
    poids_total = sum(c.poids for c in retenus)
    if not poids_total:
        return 0.0

    somme = Decimal(0)
    for critere in retenus:
        somme += Decimal(str(notes[critere.code]["note"])) * critere.poids
    return float(round(somme / poids_total, 1))


def _classer(lignes: list[dict]) -> list[dict]:
    """
    Le classement, du meilleur au moins bon.

    **Deux scores egaux partagent le meme rang.** Departager sur le sigle aurait
    fait dependre le rang de l'alphabet, ce qu'aucune direction n'accepterait —
    et le suivant reprend au rang qui suit le nombre d'ex aequo, comme dans un
    classement sportif.
    """
    lignes.sort(key=lambda ligne: (-ligne["scoreGlobal"], ligne["structureSigle"]))

    rang = 0
    precedent = None
    for position, ligne in enumerate(lignes, start=1):
        if ligne["scoreGlobal"] != precedent:
            rang = position
            precedent = ligne["scoreGlobal"]
        ligne["rang"] = rang
        ligne["feu"] = feu(ligne["scoreGlobal"])
        ligne["rangPrecedent"] = None
    return lignes


def _poser_le_rang_precedent(
    lignes: list[dict], utilisateur: Utilisateur, annee: int, mois: int, criteres: list[Critere]
) -> None:
    """
    Le rang du mois d'avant, pour lire l'evolution.

    Il est **recalcule** et non lu : il n'y a pas de table de scores (ADR 010).
    Le cout est un second passage sur les memes requetes, sur une dizaine de
    structures — negligeable devant le risque d'un historique fige qui
    contredirait le present.

    `None` quand la structure n'existait pas le mois precedent : « nouvelle
    entrante » se lit, une fleche verte depuis un rang imaginaire ne se lit pas.
    """
    precedent_annee, precedent_mois = (annee - 1, 12) if mois == 1 else (annee, mois - 1)

    rangs = {}
    provisoires: list[dict[str, Any]] = []
    for structure, perimetre in lignes_classees(utilisateur):
        notes = _notes(perimetre, criteres, precedent_annee, precedent_mois)
        provisoires.append(
            {"structureSigle": structure.code, "scoreGlobal": _score_global(notes, criteres)}
        )
    for ligne in _classer(provisoires):
        rangs[ligne["structureSigle"]] = ligne["rang"]

    for ligne in lignes:
        ligne["rangPrecedent"] = rangs.get(ligne["structureSigle"])


def _score_du_mois_precedent(perimetre: list[int], annee: int, mois: int) -> float | None:
    precedent_annee, precedent_mois = (annee - 1, 12) if mois == 1 else (annee, mois - 1)
    criteres = list(Critere.objects.filter(actif=True))
    return _score_global(_notes(perimetre, criteres, precedent_annee, precedent_mois), criteres)


def _historique(perimetre: list[int], criteres: list[Critere], annee: int, mois: int) -> list[dict]:
    """
    Les douze derniers mois, du plus ancien au plus recent.

    Dans cet ordre parce que c'est celui d'une courbe : le temps va de gauche a
    droite. Le tableau du classement, lui, va du meilleur au moins bon — deux
    ordres differents pour deux lectures differentes.
    """
    from noyau.administration.lecture import MOIS

    points = []
    courant_annee, courant_mois = annee, mois
    for _ in range(12):
        notes = _notes(perimetre, criteres, courant_annee, courant_mois)
        points.append(
            {
                "periode": f"{MOIS[courant_mois - 1]} {str(courant_annee)[2:]}",
                "score": _score_global(notes, criteres),
            }
        )
        courant_annee, courant_mois = (
            (courant_annee - 1, 12) if courant_mois == 1 else (courant_annee, courant_mois - 1)
        )

    points.reverse()
    return points


def structures_classees() -> list[Structure]:
    """
    Les structures classees : celles dont le **niveau** porte
    `ligne_statistiques`.

    Ce drapeau existe pour cela — « apparait comme ligne dans les tableaux
    statistiques » — et il est **administre**, pas ecrit ici. Filtrer sur
    `parent IS NULL` aurait donne une seule ligne, la Direction Generale, qui
    ne se compare a personne ; filtrer sur un rang en dur aurait fige a deux
    etages un organigramme dont le principe 3 dit qu'il en compte autant que
    l'administrateur en cree.

    Un etage trop fin rend le classement illisible : c'est a l'administrateur
    de retirer `ligne_statistiques` aux niveaux qu'il ne veut pas voir classes.
    """
    return list(
        Structure.objects.en_vigueur()
        .filter(niveau_hierarchique__ligne_statistiques=True)
        .order_by("code")
    )


def _compteurs(lignes: list[dict], moyenne: float) -> list[dict]:
    """Trois chiffres de tete. Le troisieme est celui qu'on vient chercher."""
    en_alerte = sum(1 for ligne in lignes if ligne["feu"] == "rouge")
    non_mesurees = sum(1 for ligne in lignes if ligne["scoreGlobal"] == 0)

    return [
        {
            "libelle": "Structures classées",
            "valeur": len(lignes),
            "note": "Structures de premier niveau en vigueur",
            "feu": "inconnu" if not lignes else "vert",
        },
        {
            "libelle": "Moyenne de l'institution",
            "valeur": moyenne,
            "note": "Moyenne des scores globaux, non pondérée par la taille",
            "feu": feu(moyenne) if lignes else "inconnu",
        },
        {
            "libelle": "Structures en alerte",
            "valeur": en_alerte,
            "note": (
                "Aucune structure sous le seuil rouge"
                if not en_alerte
                else f"{non_mesurees} sans aucune donnée mesurable"
            ),
            "feu": "vert" if not en_alerte else "rouge",
        },
    ]

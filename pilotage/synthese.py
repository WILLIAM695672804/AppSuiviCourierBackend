"""
La note de synthese d'instance — §3.1 et §3.2.

Le Directeur general « exporte en un clic les syntheses au format PDF pour
diffusion avant les instances » ; le Comite de direction « recoit, avant chaque
instance, les exports de synthese generes automatiquement ».

**C'est un document, pas un tableau de bord.** Il se lit une fois, sur papier,
en seance. Deux consequences pour le serveur :

 1. Les faits marquants sont des **phrases**, pas des chiffres. Un lecteur en
    seance ne recompose pas « 62 » et « 71 » en « l'execution a progresse de
    neuf points » ; c'est au producteur de la note de l'ecrire.
 2. Une phrase ne s'ecrit que sur une mesure disponible. Quand la mesure manque,
    la note le dit — « le traitement du courrier n'est pas mesure » — plutot que
    de taire l'absence, qui se lirait comme une absence de probleme (ADR 011).

La note porte sur la **prochaine seance** : c'est celle qu'on prepare. A defaut,
sur la derniere tenue, parce qu'une note vide n'aide personne a comprendre
pourquoi elle est vide.
"""

import re
import unicodedata
from datetime import date

from gouvernance.modeles import Seance
from noyau.calendrier import en_toutes_lettres, libelle_mois, mois_precedent
from noyau.documents.structure import (
    Bloc,
    Cellule,
    Chiffre,
    Chiffres,
    Colonne,
    Document,
    Encadre,
    Paragraphe,
    Puces,
    Section,
    Tableau,
    retenir,
)
from noyau.feu import SEUIL_ORANGE, SEUIL_VERT, feu
from noyau.identite.modeles import Utilisateur
from noyau.parametres.service import valeur as parametre
from performance import matrice as calcul
from pilotage import mesures

LIBELLES_INSTANCE = dict(Seance.TYPES)


def synthese(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> dict:
    """La note, prete a imprimer."""
    jour = aujourd_hui or date.today()
    annee, mois = mois_precedent(jour.year, jour.month)

    seance = _seance_a_preparer(jour)
    classement = calcul.matrice(utilisateur, annee, mois)["lignes"]

    execution = mesures.execution_activites()
    echues = mesures.decisions_echues(jour)
    executees = mesures.decisions_executees(annee, mois)

    return {
        "instance": _instance(seance),
        "seance": seance.intitule if seance else "Aucune séance programmée",
        "dateSeance": seance.date_seance.isoformat() if seance else jour.isoformat(),
        "producteur": _producteur(seance),
        "periode": libelle_mois(annee, mois),
        "faitsMarquants": _faits_marquants(annee, mois, execution, executees, echues),
        # Zero plutot que `null` : l'ecran est un document imprime, et un
        # « — » au milieu d'une phrase se lit comme une donnee perdue. Ce qui
        # n'est pas mesurable est dit dans les faits marquants, en toutes
        # lettres.
        "executionActivites": execution if execution is not None else 0,
        "decisionsEchues": echues,
        "decisionsExecutees": executees,
        "classement": [
            {
                "rang": ligne["rang"],
                "sigle": ligne["structureSigle"],
                "libelle": ligne["structureLibelle"],
                "score": ligne["scoreGlobal"],
                "feu": ligne["feu"],
            }
            for ligne in classement
        ],
        "pointsDAttention": _points_d_attention(jour, classement, execution),
    }


def _seance_a_preparer(jour: date) -> Seance | None:
    prochaine = (
        Seance.objects.filter(invalide_le__isnull=True, date_seance__gte=jour)
        .order_by("date_seance")
        .first()
    )
    if prochaine is not None:
        return prochaine

    return Seance.objects.filter(invalide_le__isnull=True).order_by("-date_seance").first()


def _instance(seance: Seance | None) -> str:
    if seance is None:
        return "Comité de direction"
    return LIBELLES_INSTANCE.get(seance.type_seance, seance.type_seance)


def _producteur(seance: Seance | None) -> str:
    """
    La structure qui tient le secretariat de la seance.

    Le §3.3 confie ce secretariat a la DSR ; la note le lit neanmoins de la
    seance, parce qu'un rapport sectoriel est produit par la structure qui le
    rend, et non par la DSR.
    """
    if seance is None or seance.structure is None:
        return "Division du Suivi et de la Relance"
    return seance.structure.libelle


def _faits_marquants(
    annee: int,
    mois: int,
    execution: float | None,
    executees: int,
    echues: int,
) -> list[str]:
    """
    Ce qu'on retient du mois, en phrases.

    Chaque phrase repose sur une mesure existante. Aucune n'interprete : la
    note dit ce qui s'est passe, l'instance dit pourquoi.
    """
    annee_avant, mois_avant = mois_precedent(annee, mois)
    faits: list[str] = []

    if execution is None:
        faits.append(
            "Aucune activité n'a démarré sur la période : le taux d'exécution n'est pas mesurable."
        )
    else:
        avant = mesures.execution_mensuelle(annee_avant, mois_avant)
        evolution = mesures.variation(execution, avant)
        phrase = f"Le taux d'exécution des activités s'établit à {execution} %"
        faits.append(f"{phrase} ({evolution} sur un mois)." if evolution else f"{phrase}.")

    a_temps, obligations = mesures.ponctualite_obligations()
    if obligations:
        faits.append(
            f"{a_temps} production{'s' if a_temps > 1 else ''} sur {obligations} "
            "ont été déposées à l'échéance du calendrier officiel."
        )
    else:
        faits.append("Aucune production n'était attendue au calendrier officiel sur la période.")

    faits.append(
        f"{executees} décision{'s' if executees > 1 else ''} d'instance "
        f"{'ont' if executees > 1 else 'a'} été exécutée{'s' if executees > 1 else ''} "
        f"dans le mois, pour {echues} échéance{'s' if echues > 1 else ''} arrivée"
        f"{'s' if echues > 1 else ''} à terme."
    )

    critiques = mesures.activites_critiques()
    if critiques:
        faits.append(
            f"{critiques} activité{'s' if critiques > 1 else ''} "
            f"{'sont' if critiques > 1 else 'est'} critique"
            f"{'s' if critiques > 1 else ''} au sens du §20 — en retard et portant "
            "une contrainte échue."
        )

    # Dit, et non tu : une note qui passerait le courrier sous silence
    # laisserait croire qu'il va bien.
    faits.append(
        "Le traitement du courrier et l'instruction des dossiers ne sont pas "
        "mesurés : les piliers correspondants ne sont pas en service."
    )
    return faits


def _points_d_attention(jour: date, classement: list[dict], execution: float | None) -> list[dict]:
    """
    Ce sur quoi l'instance doit se prononcer.

    Un point d'attention nomme une structure ou un objet ; « la performance
    globale est perfectible » n'engage personne et ne se decide pas.
    """
    points: list[dict] = []

    # Les structures **mesurées** dont le score est bas — voir
    # `mesures.lignes_mesurees` : un score de zero faute de saisie n'est pas un
    # score de zero, et la note d'instance ne met pas une structure en cause
    # pour un plan d'actions qu'elle n'a pas encore inscrit.
    fragiles = [
        ligne
        for ligne in mesures.lignes_mesurees(classement)
        if ligne["scoreGlobal"] < SEUIL_ORANGE
    ]
    if fragiles:
        points.append(
            {
                "titre": "Structures sous le seuil d'alerte",
                "texte": (
                    "Au dernier mois clos, "
                    + ", ".join(
                        f"{ligne['structureSigle']} ({ligne['scoreGlobal']}/100)"
                        for ligne in fragiles
                    )
                    + " passent sous 60 sur 100. Un plan de redressement relève de l'instance."
                ),
                "feu": "rouge",
            }
        )

    en_retard = mesures.decisions_en_retard()
    if en_retard:
        points.append(
            {
                "titre": "Décisions dont l'échéance est dépassée",
                "texte": (
                    f"{en_retard} décision{'s' if en_retard > 1 else ''} "
                    f"{'restent' if en_retard > 1 else 'reste'} à exécuter après échéance. "
                    "Le registre des décisions en donne le détail, structure par structure."
                ),
                "feu": "rouge",
            }
        )

    sans_interim = mesures.absences_sans_interim(jour)
    if sans_interim:
        points.append(
            {
                "titre": "Responsables absents sans intérim",
                "texte": (
                    f"{sans_interim} responsable{'s' if sans_interim > 1 else ''} "
                    f"{'sont' if sans_interim > 1 else 'est'} absent"
                    f"{'s' if sans_interim > 1 else ''} sans suppléant désigné : "
                    "les dossiers de leur structure n'avancent pas."
                ),
                "feu": "orange",
            }
        )

    if execution is not None and execution < SEUIL_VERT:
        points.append(
            {
                "titre": "Exécution des plans d'actions",
                "texte": (
                    f"L'exécution moyenne s'établit à {execution} %, sous la cible de "
                    f"{SEUIL_VERT} %. Le détail par structure figure au classement mensuel."
                ),
                "feu": feu(execution),
            }
        )

    if not points:
        points.append(
            {
                "titre": "Aucun point d'attention",
                "texte": (
                    "Aucune structure sous le seuil, aucune décision hors délai, "
                    "aucun responsable absent sans suppléance à la date de la note."
                ),
                "feu": "vert",
            }
        )
    return points


# =====================================================================
#  La note en tant que document — ADR 023
#
#  `synthese()` sert l'ecran ; `synthese_document()` sert le fichier. Les deux
#  partent des memes mesures : deux calculs auraient fini par donner deux
#  chiffres, et c'est celui du papier qu'on aurait commente en seance.
#
#  Ce qui distingue le document de l'ecran n'est pas le contenu, c'est la
#  **forme** : sections numerotees et renumerotables, tableau long renvoye en
#  annexe, feux ecrits en toutes lettres parce qu'une note se photocopie en
#  noir et blanc.
# =====================================================================

#: Les libelles des feux, en toutes lettres. La couleur ajoute, elle ne porte
#: jamais seule l'information — voir §3.2 et le meme choix a l'ecran.
LIBELLES_FEU = {
    "vert": "Satisfaisant",
    "orange": "À surveiller",
    "rouge": "Sous le seuil",
    "inconnu": "Non mesuré",
}

#: Ce que le corps garde d'un classement bascule en annexe : les meilleures et
#: les moins bonnes. Le milieu du tableau n'appelle aucune decision.
EXTREMES_AU_CORPS = 3

#: Longueur maximale d'un sigle d'instance dans la reference du document. Une
#: reference se cite a voix haute et se retape a la main.
LONGUEUR_SIGLE = 8


def synthese_document(utilisateur: Utilisateur, aujourd_hui: date | None = None) -> Document:
    """
    La note de synthese, prete a rendre en Word ou en PDF — §3.1 et §3.2.

    Le contenu varie avec les donnees : une section sans objet disparait et la
    numerotation se recalcule, un classement long part en annexe, et les
    phrases se composent depuis les mesures disponibles.
    """
    donnees = synthese(utilisateur, aujourd_hui)
    seuil = parametre("pilotage.lignes_avant_annexe", 12)
    classement = donnees["classement"]
    en_annexe = len(classement) > seuil

    corps = classement if not en_annexe else _extremes(classement)

    sections = retenir(
        Section(
            titre="Faits marquants de la période",
            blocs=(Puces(items=tuple(donnees["faitsMarquants"])),),
        ),
        Section(
            titre="Chiffres d'ensemble",
            blocs=(
                Chiffres(
                    items=(
                        Chiffre(
                            libelle="Exécution des activités",
                            valeur=f"{_nombre_ecrit(donnees['executionActivites'])} %",
                        ),
                        Chiffre(
                            libelle="Décisions arrivées à échéance",
                            valeur=str(donnees["decisionsEchues"]),
                        ),
                        Chiffre(
                            libelle="Décisions exécutées",
                            valeur=str(donnees["decisionsExecutees"]),
                        ),
                    )
                ),
            ),
        ),
        _section_classement(corps, en_annexe=en_annexe, total=len(classement)),
        Section(
            titre="Points appelant un arbitrage",
            blocs=tuple(
                Encadre(titre=point["titre"], texte=point["texte"], feu=point["feu"])
                for point in donnees["pointsDAttention"]
            ),
        ),
        Section(
            titre="Portée de la note",
            blocs=(
                Paragraphe(
                    texte=(
                        "Document produit automatiquement à partir des registres tenus "
                        f"dans l'application. Les chiffres portent sur {donnees['periode']} "
                        "et n'engagent que les données remontées par les structures à la "
                        "date d'édition."
                    )
                ),
            ),
        ),
    )

    annexes: tuple[Section, ...] = ()
    if en_annexe:
        annexes = (
            Section(
                titre="Classement complet des structures",
                blocs=(_tableau_classement(classement),),
            ),
        )

    return Document(
        titre=f"Note de synthèse — {donnees['instance']}",
        surtitre=donnees["producteur"],
        sous_titre=(
            f"{donnees['seance']} · séance du {_jour_en_lettres(donnees['dateSeance'])} · "
            f"période observée : {donnees['periode']}"
        ),
        reference=_reference(donnees),
        sections=sections,
        annexes=annexes,
    )


def _section_classement(lignes: list[dict], *, en_annexe: bool, total: int) -> Section:
    """
    Le classement, ou son extrait quand il est long.

    Le renvoi a l'annexe est **ecrit** : un tableau ampute sans explication se
    lit comme un classement de six structures, et l'institution en compte
    vingt-quatre.
    """
    blocs: list[Bloc] = [_tableau_classement(lignes)]
    if en_annexe:
        blocs.append(
            Paragraphe(
                texte=(
                    f"Seules les {len(lignes)} structures aux deux extrémités du classement "
                    f"figurent ci-dessus. Les {total} structures classées sont reprises en "
                    "annexe A."
                )
            )
        )
    return Section(titre="Classement des structures", blocs=tuple(blocs))


def _tableau_classement(lignes: list[dict]) -> Tableau:
    return Tableau(
        colonnes=(
            Colonne(entete="Rang"),
            Colonne(entete="Structure", poids=5),
            Colonne(entete="Score", a_droite=True),
            Colonne(entete="Cotation", poids=3),
        ),
        lignes=tuple(
            (
                Cellule(texte=str(ligne["rang"])),
                Cellule(texte=f"{ligne['sigle']} — {ligne['libelle']}"),
                Cellule(texte=_score_ecrit(ligne["score"])),
                Cellule(
                    texte=LIBELLES_FEU.get(ligne["feu"], ligne["feu"]),
                    barre=_barre(ligne["score"]),
                    feu=ligne["feu"],
                ),
            )
            for ligne in lignes
        ),
        legende="Score global sur 100, au dernier mois clos.",
    )


def _score_ecrit(score: float | None) -> str:
    """
    Le score, ou son absence en toutes lettres.

    Ni « — » ni « 0 » quand la mesure manque : un zero se lit comme un echec et
    se commente en seance, alors que rien ne le soutient (ADR 011).
    """
    return "Non mesuré" if score is None else _nombre_ecrit(score)


def _nombre_ecrit(valeur: float) -> str:
    """
    Un nombre a la francaise : virgule decimale, entier sans « ,0 ».

    Python ecrit « 70.0 » ; un document institutionnel ecrit « 70 ». Le point
    decimal anglais sur une note qui part en seance se voit, et il se voit
    d'autant plus que la phrase voisine dit deja « 0,0 pt ».
    """
    if float(valeur).is_integer():
        return str(int(valeur))
    return f"{valeur}".replace(".", ",")


def _barre(score: float | None) -> int | None:
    """
    Le score en pourcentage de remplissage.

    `None` quand la structure n'est pas mesuree : une barre vide se lirait
    comme un zero, et un zero comme un echec (ADR 011).
    """
    if score is None:
        return None
    return max(0, min(100, round(score)))


def _extremes(classement: list[dict]) -> list[dict]:
    """Les premieres et les dernieres du classement — le milieu ne decide rien."""
    if len(classement) <= 2 * EXTREMES_AU_CORPS:
        return classement
    return classement[:EXTREMES_AU_CORPS] + classement[-EXTREMES_AU_CORPS:]


def _jour_en_lettres(iso: str) -> str:
    """
    « 2026-09-03 » → « 3 septembre 2026 ».

    L'ecran formate la date cote front ; le document n'a pas de front. Une note
    institutionnelle qui annoncerait « séance du 2026-09-03 » se verrait.
    """
    return en_toutes_lettres(date.fromisoformat(iso))


def _reference(donnees: dict) -> str:
    """
    La reference du document, citee en seance.

    Elle porte la date de seance et non celle de l'edition : deux tirages de la
    meme note s'appellent pareil, et c'est ce qu'on veut — c'est la note de
    cette seance-la.
    """
    return f"NOTE-{_sigle_instance(donnees['instance'])}-{donnees['dateSeance']}"


def _sigle_instance(instance: str) -> str:
    """
    Le sigle de l'instance, pour la reference — « CODIR », « SCA », « RPDG ».

    Les libelles reels de `Seance.TYPES` vont du sigle deja constitue
    (« CODIR ») a la phrase (« Reunion presidee par le DG ») : un mot deja tout
    en majuscules est repris tel quel, les mots courts (« du », « le »,
    « d' ») ne siglent rien, et les autres donnent leur initiale.

    Sans accent : la reference se retape a la main, et se cite a voix haute.
    """
    sans_accent = unicodedata.normalize("NFKD", instance).encode("ascii", "ignore").decode()
    mots = [mot for mot in re.split(r"[^A-Za-z]+", sans_accent) if mot]

    sigle = ""
    for mot in mots:
        if mot.isupper():
            sigle += mot
        elif len(mot) > 3:
            sigle += mot[0]

    # Un libelle fait de mots courts ne doit pas produire une reference vide :
    # « NOTE--2026-09-03 » ne se cite pas.
    if not sigle:
        sigle = "".join(mot[0] for mot in mots)
    return sigle[:LONGUEUR_SIGLE].upper()

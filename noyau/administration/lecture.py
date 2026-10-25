"""
Le tableau de bord de l'administrateur fonctionnel — §3.9.

**Il ne compte pas des courriers, il compte des actes.** L'administrateur
fonctionnel n'a pas de portefeuille a suivre ; ce qu'il surveille, c'est
l'usage de l'outil, l'etat de son referentiel et les acces qui sortent de
l'ordinaire. Lui presenter le tableau de bord metier reviendrait a lui montrer
le travail des autres.

La source unique de la volumetrie est la table `evenement` — donc **ce que
l'application a inscrit**, pas ce qui existe en base. Un import massif fait en
SQL direct n'apparait pas ici, et c'est voulu : la question posee est « l'outil
sert-il », pas « la base est-elle grosse ».

Les valeurs sortent **deja formatees**. L'ecran n'agrege rien : les totaux
d'une institution ne se calculent pas dans un navigateur, et deux ecrans qui
arrondiraient differemment le meme chiffre finiraient par se contredire.

Le decoupage par permission est ici et non seulement au front. Le front cache
les blocs qu'un compte ne doit pas voir ; sans le meme filtre au serveur, la
reponse porterait quand meme les acces signales a qui n'a pas `AUDIT`. C'est
exactement le genre d'oubli qui ne produit aucune erreur.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.db import connection
from django.utils import timezone

from noyau.calendrier import MOIS_COURTS
from noyau.habilitation.dependances import PERM
from noyau.habilitation.modeles import Delegation, Profil, UtilisateurProfil
from noyau.habilitation.resolution import comptes_du_portail, possede
from noyau.identite.modeles import Utilisateur
from noyau.organisation.modeles import NiveauHierarchique, Poste, Structure
from noyau.perimetre.modeles import Perimetre
from noyau.tracabilite.lecture import FAMILLES, journal_acces

#: Les trois periodes que l'ecran propose, et comment chacune se lit.
#:
#: `pas` est l'unite de regroupement de la courbe, et elle change avec la
#: duree : trois cent soixante-cinq barres ne se lisent pas, trente si. Le
#: front n'en sait rien — il affiche les libelles que le serveur lui donne.
PERIODES: dict[str, dict[str, Any]] = {
    "30j": {"jours": 30, "pas": "day", "libelle": "30 derniers jours"},
    "trimestre": {"jours": 91, "pas": "week", "libelle": "trimestre"},
    "annee": {"jours": 365, "pas": "month", "libelle": "année"},
}

#: Les mois vivent dans `noyau/calendrier.py` depuis que le pilotage les
#: demande a son tour. Le nom local reste : `performance/matrice.py` l'importe
#: d'ici, et le renommer n'aurait rien appris a personne.
MOIS = MOIS_COURTS


def tableau_de_bord(utilisateur: Utilisateur, periode: str = "30j") -> dict:
    """
    Tout l'ecran en une reponse.

    Une seule route et non quatre, parce que les quatre blocs se lisent
    ensemble : « trois cents operations » ne veut rien dire sans « et douze
    structures sur quinze n'en ont fait aucune ». Quatre appels auraient aussi
    fait clignoter l'ecran a chaque changement de periode.

    Les blocs qu'un compte n'a pas le droit de voir sortent **vides**, et non
    absents : le schema de reponse reste le meme pour tout le monde, ce qui
    evite au front d'avoir a distinguer « pas le droit » de « rien a montrer ».
    """
    reglage = PERIODES.get(periode) or PERIODES["30j"]
    fin = timezone.now()
    debut = fin - timedelta(days=reglage["jours"])
    debut_precedent = debut - timedelta(days=reglage["jours"])

    voit_journaux = possede(utilisateur, PERM.AUDIT)
    voit_comptes = possede(utilisateur, PERM.ADM_HAB)
    voit_structures = possede(utilisateur, PERM.ADM_ORG)

    total = _compter_evenements(debut, fin)
    precedent = _compter_evenements(debut_precedent, debut)

    adoption = _adoption(debut, total) if voit_structures else []
    acces = _acces() if voit_journaux else _acces_vides()

    return {
        "indicateurs": _indicateurs(
            total=total,
            precedent=precedent,
            adoption=adoption,
            signales=acces["signales"],
            voit_journaux=voit_journaux,
            voit_comptes=voit_comptes,
            voit_structures=voit_structures,
            libelle_periode=reglage["libelle"],
        ),
        "activite": _serie(debut, fin, reglage["pas"]) if voit_journaux else [],
        "operationsTotal": total if voit_journaux else 0,
        "operationsVariation": _variation(total, precedent) if voit_journaux else "—",
        "parType": _par_famille(debut, fin) if voit_journaux else [],
        "adoption": adoption,
        "structuresInactives": sum(1 for ligne in adoption if ligne["derniereActivite"] is None),
        "referentiel": _referentiel() if (voit_comptes or voit_structures) else [],
        "anomalies": _anomalies(voit_comptes=voit_comptes, voit_structures=voit_structures),
        "acces": acces,
    }


# =====================================================================
#  Volumetrie
# =====================================================================


def _compter_evenements(debut: datetime, fin: datetime) -> int:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT count(*) FROM evenement WHERE survenu_le >= %s AND survenu_le < %s",
            [debut, fin],
        )
        return curseur.fetchone()[0]


def _serie(debut: datetime, fin: datetime, pas: str) -> list[dict]:
    """
    La courbe, trous compris.

    **Les periodes sans operation sont rendues a zero**, pas omises. Une courbe
    qui saute les jours creux se lit comme une activite continue : c'est
    precisement l'inverse de ce que l'administrateur doit voir.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT date_trunc(%s, survenu_le) AS pas, count(*)
            FROM evenement
            WHERE survenu_le >= %s AND survenu_le < %s
            GROUP BY 1
            ORDER BY 1
            """,
            [pas, debut, fin],
        )
        comptes = {ligne[0].date(): ligne[1] for ligne in curseur.fetchall()}

    points = []
    for borne in _bornes(debut, fin, pas):
        points.append({"periode": _libelle_borne(borne, pas), "operations": comptes.get(borne, 0)})
    return points


def _bornes(debut: datetime, fin: datetime, pas: str) -> list:
    """Les debuts de periode couverts, calcules en Python.

    `generate_series` aurait fait la meme chose en SQL, mais la troncature
    doit etre identique a celle de `date_trunc` pour que les cles se
    rencontrent — la refaire ici, sur le meme fuseau, evite un decalage d'un
    jour qui ne se verrait qu'en fin de mois.
    """
    courant = timezone.localtime(debut).date()
    borne_fin = timezone.localtime(fin).date()
    bornes = []

    if pas == "week":
        courant = courant - timedelta(days=courant.weekday())
    elif pas == "month":
        courant = courant.replace(day=1)

    while courant <= borne_fin:
        bornes.append(courant)
        if pas == "day":
            courant = courant + timedelta(days=1)
        elif pas == "week":
            courant = courant + timedelta(days=7)
        else:
            courant = (courant.replace(day=28) + timedelta(days=4)).replace(day=1)

    return bornes


def _libelle_borne(borne, pas: str) -> str:
    if pas == "day":
        return borne.strftime("%d/%m")
    if pas == "week":
        return f"S{borne.isocalendar().week}"
    return MOIS[borne.month - 1]


def _variation(total: int, precedent: int) -> str:
    """
    L'ecart avec la periode precedente de meme duree.

    « Nouveau » et non « +100 % » quand la periode precedente est vide : un
    pourcentage calcule sur zero ne veut rien dire, et l'application est encore
    assez jeune pour que le cas soit le plus frequent.
    """
    if precedent == 0:
        return "Nouveau" if total else "—"

    ecart = round((total - precedent) / precedent * 100)
    return f"{ecart:+d} %"


def _par_famille(debut: datetime, fin: datetime) -> list[dict]:
    """
    La repartition par famille d'operation.

    Les familles sont celles du journal des evenements, et il n'y en a pas
    deux jeux : « 300 cotations » et « 300 corrections de parametrage » ne
    racontent pas la meme institution, mais ils doivent porter le meme nom
    dans les deux ecrans.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT type_evenement, count(*)
            FROM evenement
            WHERE survenu_le >= %s AND survenu_le < %s
            GROUP BY 1
            """,
            [debut, fin],
        )
        lignes = curseur.fetchall()

    from noyau.tracabilite.lecture import _famille

    totaux: dict[str, int] = defaultdict(int)
    for type_evenement, nombre in lignes:
        totaux[_famille(type_evenement)] += nombre

    total = sum(totaux.values())

    # Toutes les familles sortent, y compris a zero : une famille absente se
    # lirait comme une famille qui n'existe pas, alors qu'elle n'a servi a
    # personne sur la periode — ce qui est justement l'information.
    return [
        {
            "libelle": famille,
            "valeur": totaux.get(famille, 0),
            "part": round(totaux.get(famille, 0) / total * 100) if total else 0,
        }
        for famille in FAMILLES
    ]


# =====================================================================
#  Adoption
# =====================================================================


def _adoption(debut: datetime, total: int) -> list[dict]:
    """
    Qui se sert reellement de l'application, par structure de premier niveau.

    **De premier niveau**, c'est-a-dire par direction : une ligne par service
    donnerait cinquante lignes ou personne ne verrait qu'une direction entiere
    est absente. Chaque agent est donc remonte a la racine de son
    rattachement.

    Un service dont la direction est close remonte a lui-meme et forme sa
    propre ligne. C'est la meme decision que pour l'organigramme : on n'invente
    pas un rattachement, on montre ce qui est.
    """
    racines, appartenance = _racines()

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT acteur_id, count(*), max(survenu_le)
            FROM evenement
            WHERE survenu_le >= %s AND acteur_id IS NOT NULL
            GROUP BY acteur_id
            """,
            [debut],
        )
        activite = {ligne[0]: (ligne[1], ligne[2]) for ligne in curseur.fetchall()}

    structure_de = dict(
        Utilisateur.objects.filter(pk__in=activite).values_list("pk", "structure_id")
    )

    operations: dict[int, int] = defaultdict(int)
    derniere: dict[int, datetime] = {}
    for acteur_id, (nombre, survenu_le) in activite.items():
        racine = appartenance.get(structure_de.get(acteur_id))
        if racine is None:
            continue
        operations[racine] += nombre
        if racine not in derniere or survenu_le > derniere[racine]:
            derniere[racine] = survenu_le

    comptes = _comptes_par_racine(appartenance)

    lignes = []
    for racine_id, libelle in racines.items():
        actifs, habilites = comptes.get(racine_id, (0, 0))
        nombre = operations.get(racine_id, 0)
        lignes.append(
            {
                "structure": libelle,
                "actifs": actifs,
                "habilites": habilites,
                "operations": nombre,
                "part": round(nombre / total * 100) if total else 0,
                "derniereActivite": (
                    timezone.localtime(derniere[racine_id]).strftime("%d/%m/%Y")
                    if racine_id in derniere
                    else None
                ),
            }
        )

    return sorted(lignes, key=lambda ligne: (-ligne["operations"], ligne["structure"]))


def _racines() -> tuple[dict[int, str], dict[int | None, int]]:
    """
    Les structures de premier niveau, et a laquelle chaque structure remonte.

    La remontee s'arrete des qu'un parent n'est plus en vigueur : une structure
    orpheline devient sa propre racine plutot que de disparaitre du tableau.
    Le garde-fou sur les visites protege d'un cycle — l'ecrire coute une ligne,
    le decouvrir en production coute une boucle infinie.
    """
    structures = {
        structure.pk: structure
        for structure in Structure.objects.en_vigueur().only("id", "code", "libelle", "parent_id")
    }

    appartenance: dict[int | None, int] = {}
    for identifiant in structures:
        courant = identifiant
        visitees = {courant}
        while True:
            parent = structures[courant].parent_id
            if parent is None or parent not in structures or parent in visitees:
                break
            visitees.add(parent)
            courant = parent
        appartenance[identifiant] = courant

    racines = {
        identifiant: structures[identifiant].code for identifiant in set(appartenance.values())
    }
    return racines, appartenance


def _comptes_par_racine(appartenance: dict[int | None, int]) -> dict[int, tuple[int, int]]:
    """
    Comptes actifs et comptes habilites, par structure de premier niveau.

    « Habilite » veut dire : porte au moins un profil non retire. Un compte
    actif sans profil peut se connecter et ne peut rien faire — c'est un compte
    ouvert a moitie, et l'ecart entre les deux chiffres est ce que
    l'administrateur doit voir.
    """
    habilites = set(
        UtilisateurProfil.objects.filter(retire_le__isnull=True).values_list(
            "utilisateur_id", flat=True
        )
    )

    resultat: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for identifiant, structure_id in Utilisateur.objects.filter(actif=True).values_list(
        "pk", "structure_id"
    ):
        racine = appartenance.get(structure_id)
        if racine is None:
            continue
        resultat[racine][0] += 1
        if identifiant in habilites:
            resultat[racine][1] += 1

    return {racine: (valeurs[0], valeurs[1]) for racine, valeurs in resultat.items()}


# =====================================================================
#  Sante du referentiel
# =====================================================================


def _referentiel() -> list[dict]:
    """Ce que le referentiel contient, sans jugement — les defauts sont a cote."""
    return [
        {
            "libelle": "Structures en vigueur",
            "valeur": Structure.objects.en_vigueur().count(),
        },
        {"libelle": "Postes de travail", "valeur": Poste.objects.en_vigueur().count()},
        {"libelle": "Niveaux hiérarchiques", "valeur": NiveauHierarchique.objects.count()},
        {"libelle": "Comptes actifs", "valeur": Utilisateur.objects.filter(actif=True).count()},
        {"libelle": "Profils", "valeur": Profil.objects.filter(invalide_le__isnull=True).count()},
        {
            "libelle": "Délégations en cours",
            "valeur": Delegation.objects.filter(
                invalide_le__isnull=True, debut__lte=timezone.now(), fin__gte=timezone.now()
            ).count(),
        },
    ]


def _anomalies(*, voit_comptes: bool, voit_structures: bool) -> list[dict]:
    """
    Ce qui cloche, et l'ecran ou le corriger.

    **Chaque anomalie porte son chemin.** Un tableau de bord qui signale sans
    mener au remede fait perdre le temps qu'il croit faire gagner ; c'est aussi
    ce qui distingue une anomalie d'un simple compteur.

    Le ton separe ce qui bloque de ce qui derange : `danger` pour un compte qui
    ne peut rien faire, `alerte` pour un poste vacant, qui est souvent un etat
    normal de l'institution entre deux nominations.
    """
    anomalies = []

    if voit_comptes:
        habilites = UtilisateurProfil.objects.filter(retire_le__isnull=True).values_list(
            "utilisateur_id", flat=True
        )
        sans_profil = Utilisateur.objects.filter(actif=True).exclude(pk__in=habilites).count()
        if sans_profil:
            anomalies.append(
                {
                    "libelle": "Comptes actifs sans profil",
                    "nombre": sans_profil,
                    "chemin": "/habilitations",
                    "ton": "danger",
                }
            )

        # Les comptes du portail sont ecartes des deux controles qui suivent :
        # ils n'ont ni perimetre ni rattachement **par decision** (ADR 013), et
        # les signaler ferait de cette decision une anomalie permanente.
        usagers = comptes_du_portail().values_list("pk", flat=True)

        avec_perimetre = Perimetre.objects.filter(valide_au__isnull=True).values_list(
            "utilisateur_id", flat=True
        )
        sans_perimetre = (
            Utilisateur.objects.filter(actif=True)
            .exclude(pk__in=avec_perimetre)
            .exclude(pk__in=usagers)
            .count()
        )
        if sans_perimetre:
            anomalies.append(
                {
                    "libelle": "Comptes actifs sans périmètre",
                    "nombre": sans_perimetre,
                    "chemin": "/habilitations",
                    "ton": "danger",
                }
            )

        sans_rattachement = (
            Utilisateur.objects.filter(actif=True, structure__isnull=True)
            .exclude(pk__in=usagers)
            .count()
        )
        if sans_rattachement:
            anomalies.append(
                {
                    "libelle": "Comptes sans structure de rattachement",
                    "nombre": sans_rattachement,
                    "chemin": "/habilitations",
                    "ton": "danger",
                }
            )

    if voit_structures:
        # Promise par la docstring de `organisation.lecture.referentiel_structures` :
        # le referentiel rend `parentId` brut, sans verifier que le parent est
        # en vigueur. C'est ici que l'incoherence est comptee, plutot que
        # masquee derriere un arbre qui aurait l'air juste.
        en_vigueur = set(Structure.objects.en_vigueur().values_list("pk", flat=True))
        orphelines = sum(
            1
            for parent in Structure.objects.en_vigueur()
            .exclude(parent__isnull=True)
            .values_list("parent_id", flat=True)
            if parent not in en_vigueur
        )
        if orphelines:
            anomalies.append(
                {
                    "libelle": "Structures rattachées à une structure close",
                    "nombre": orphelines,
                    "chemin": "/organisation",
                    "ton": "danger",
                }
            )

        occupes = set(
            Utilisateur.objects.filter(actif=True, poste__isnull=False).values_list(
                "poste_id", flat=True
            )
        )
        vacants = Poste.objects.en_vigueur().exclude(pk__in=occupes).count()
        if vacants:
            anomalies.append(
                {
                    "libelle": "Postes de travail vacants",
                    "nombre": vacants,
                    "chemin": "/organisation",
                    "ton": "alerte",
                }
            )

    return anomalies


# =====================================================================
#  Supervision des acces
# =====================================================================


def _acces() -> dict:
    """
    Les acces qui appellent le regard, repris du journal des acces.

    **`refuses` vaut toujours zero, et ce n'est pas un oubli.** Un acces refuse
    ne laisse pas de trace : la garde de permission rend 401 avant que la vue
    ne s'execute, et `HorsPerimetre` rend 404 (D5) sans rien inscrire. Tracer
    les refus supposerait de journaliser dans la couche d'authentification, ce
    qui remplirait la table de tentatives de navigation ordinaires.

    **`confidentiels` vaut zero tant que le pilier courrier n'existe pas** : la
    session confidentielle est declaree au socle, aucun courrier ne s'y trouve.
    Le compteur est cable sur `objet_type = 'courrier_confidentiel'`, qu'il
    suffira d'alimenter.
    """
    journal = journal_acces("Signalé", limite=50)

    confidentiels = sum(
        1 for acces in journal["acces"] if acces["objet"].startswith("courrier_confidentiel")
    )

    return {
        "signales": journal["signales"],
        "refuses": 0,
        "confidentiels": confidentiels,
        "dernieres": [
            {
                "id": acces["id"],
                "horodatage": f"{acces['date']} {acces['heure']}",
                "agent": acces["agent"],
                "action": acces["action"],
                "objet": acces["objet"],
            }
            for acces in journal["acces"][:5]
        ],
    }


def _acces_vides() -> dict:
    return {"signales": 0, "refuses": 0, "confidentiels": 0, "dernieres": []}


# =====================================================================
#  Indicateurs de tete
# =====================================================================


def _indicateurs(
    *,
    total: int,
    precedent: int,
    adoption: list[dict],
    signales: int,
    voit_journaux: bool,
    voit_comptes: bool,
    voit_structures: bool,
    libelle_periode: str,
) -> list[dict]:
    """
    Les quatre chiffres de tete, et seuls ceux que le compte a le droit de lire.

    La liste est **variable**, jamais remplie de tirets : un indicateur affiche
    a « — » se lit comme une valeur nulle, ce qui est plus faux que son
    absence.
    """
    indicateurs = []

    if voit_journaux:
        indicateurs.append(
            {
                "libelle": "Opérations enregistrées",
                "valeur": f"{total:,}".replace(",", " "),
                "variation": _variation(total, precedent),
                "ton": "accent",
                "note": f"Sur les {libelle_periode}" if libelle_periode[0].isdigit() else None,
            }
        )

    if voit_comptes:
        actifs = Utilisateur.objects.filter(actif=True).count()
        total_comptes = Utilisateur.objects.count()
        indicateurs.append(
            {
                "libelle": "Comptes actifs",
                "valeur": str(actifs),
                "variation": None,
                "ton": "accent",
                "note": f"sur {total_comptes} comptes ouverts",
            }
        )

    if voit_structures:
        actives = sum(1 for ligne in adoption if ligne["derniereActivite"] is not None)
        indicateurs.append(
            {
                "libelle": "Structures actives",
                "valeur": f"{actives} / {len(adoption)}",
                "variation": None,
                "ton": "succes" if actives == len(adoption) else "alerte",
                "note": "Au moins une opération sur la période",
            }
        )

    if voit_journaux:
        indicateurs.append(
            {
                "libelle": "Accès à examiner",
                "valeur": str(signales),
                "variation": None,
                "ton": "danger" if signales else "succes",
                "note": (
                    "Rien à signaler"
                    if not signales
                    else "Export, volume ou session confidentielle"
                ),
            }
        )

    return indicateurs

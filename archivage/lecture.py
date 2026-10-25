"""
Lectures du pilier archivage.

Le referentiel de conservation, la file des dossiers a verser, la fiche d'un
versement et la conformite du fonds.

**La file des dossiers a verser n'est pas une table.** Elle se lit : les
dossiers clos sans versement, joints a leur regle de conservation. La stocker
aurait cree une seconde liste a tenir a jour, et c'est toujours celle-la qui
oublie un dossier — celui, precisement, qu'un auditeur trouvera.

Le tri est celui de **l'echeance du sort final**, et non de la date de cloture.
Un dossier clos hier dont la DUA est d'un an passe devant un dossier clos il y
a quatre ans dont la DUA est de dix : ce qui presse n'est pas ce qui est vieux,
c'est ce qui arrive a terme.
"""

from datetime import date

from archivage.modeles import (
    ALGORITHME,
    ETAT_A_VERSER,
    ETAT_VERSE,
    SORTS,
    RegleConservation,
    Versement,
)
from dossier.modeles import ETAPE_CLOS, TYPES, Dossier
from noyau.identite.modeles import Utilisateur

LIBELLE_SORT = dict(SORTS)
LIBELLE_TYPE = dict(TYPES)

LIBELLE_ETAT_VERSEMENT = {
    ETAT_A_VERSER: "À verser",
    "en_cours": "En cours",
    ETAT_VERSE: "Versé",
    # Etat **calcule** et non stocke : un versement dont la fiche porte une
    # anomalie bloquante est en anomalie, quel que soit ce que dit sa colonne.
    "anomalie": "Anomalie",
}


# =====================================================================
#  Le referentiel de conservation
# =====================================================================


def referentiel() -> dict:
    """
    Les regles de conservation — RF-GED-06.

    `dossiersConcernes` compte les dossiers **clos** de la typologie, et non
    tous : une regle de conservation ne s'applique qu'a partir de la cloture,
    et compter les dossiers ouverts aurait fait croire a un fonds qui n'existe
    pas encore.
    """
    regles = list(RegleConservation.objects.select_related("validee_par"))
    par_typologie = _dossiers_clos_par_typologie()

    lignes = [
        {
            "id": regle.pk,
            "typologie": regle.typologie,
            "description": regle.description,
            "dua": regle.dua,
            "sortFinal": LIBELLE_SORT.get(regle.sort_final, regle.sort_final),
            "fondementJuridique": regle.fondement_juridique,
            "valideePar": _nom(regle.validee_par),
            "valideeLe": regle.validee_le.isoformat() if regle.validee_le else None,
            "actif": regle.actif,
            "dossiersConcernes": par_typologie.get(regle.typologie, 0),
        }
        for regle in regles
    ]

    en_attente = [regle for regle in regles if not regle.visee]

    return {
        "regles": lignes,
        "compteurs": _compteurs_referentiel(regles, en_attente),
        "enAttenteValidation": len(en_attente),
    }


def _dossiers_clos_par_typologie() -> dict[str, int]:
    """
    Combien de dossiers clos par typologie.

    La typologie d'une regle est comparee au **libelle** du type de dossier
    (« Autorisation »), parce que c'est ce que l'archiviste saisit. Une regle
    dont la typologie ne correspond a aucun type existe et ne s'applique a
    rien : c'est visible, et c'est ce qu'on veut — plutot qu'un rapprochement
    approximatif qui appliquerait une DUA de dix ans a la mauvaise matiere.
    """
    comptes: dict[str, int] = {}
    for type_dossier in Dossier.objects.filter(
        invalide_le__isnull=True, etape=ETAPE_CLOS
    ).values_list("type_dossier", flat=True):
        libelle = LIBELLE_TYPE.get(type_dossier, type_dossier)
        comptes[libelle] = comptes.get(libelle, 0) + 1
    return comptes


def _compteurs_referentiel(regles: list, en_attente: list) -> list[dict]:
    conservation = [regle for regle in regles if regle.sort_final == "conservation" and regle.actif]
    return [
        {
            "libelle": "Règles en attente de visa",
            "valeur": len(en_attente),
            "note": "sans visa des archives, elles ne décident de rien",
            "feu": "orange" if en_attente else "vert",
        },
        {
            "libelle": "Règles applicables",
            "valeur": len([regle for regle in regles if regle.actif and regle.visee]),
            "note": "visées par le service des archives",
            "feu": "inconnu",
        },
        {
            "libelle": "Conservation définitive",
            "valeur": len(conservation),
            "note": "typologies qui ne s'éliminent jamais",
            "feu": "inconnu",
        },
    ]


# =====================================================================
#  La file des dossiers a verser
# =====================================================================


def versements(filtre: str = "", aujourd_hui: date | None = None) -> dict:
    """
    Les dossiers clos, verses ou en attente de l'etre.

    Un dossier clos **sans regle de conservation** apparait quand meme, avec
    une anomalie bloquante. Le masquer aurait fait disparaitre de la file
    exactement les dossiers dont personne ne sait quoi faire — c'est-a-dire
    ceux qu'il faut voir.
    """
    jour = aujourd_hui or date.today()
    regles = {regle.typologie: regle for regle in RegleConservation.objects.filter(actif=True)}
    deja = {
        versement.dossier_id: versement for versement in Versement.objects.select_related("regle")
    }

    lignes = []
    for dossier in Dossier.objects.filter(
        invalide_le__isnull=True, etape=ETAPE_CLOS, clos_le__isnull=False
    ).select_related("structure"):
        lignes.append(_ligne_versement(dossier, regles, deja.get(dossier.pk), jour))

    retenues = [ligne for ligne in lignes if _retenu(ligne, filtre)]
    retenues.sort(
        key=lambda ligne: (ligne["echeanceSortFinal"] or "9999-12-31", ligne["reference"])
    )

    return {
        "versements": retenues,
        "compteurs": _compteurs_versements(lignes, jour),
    }


def _retenu(ligne: dict, filtre: str) -> bool:
    if not filtre or filtre in ("Tous", "Toutes"):
        return True
    return ligne["etat"] == filtre


def _ligne_versement(
    dossier: Dossier,
    regles: dict[str, RegleConservation],
    versement: Versement | None,
    jour: date,
) -> dict:
    """Une ligne de la file — que le versement existe ou non."""
    typologie = LIBELLE_TYPE.get(dossier.type_dossier, dossier.type_dossier)
    regle = regles.get(typologie)

    echeance: date | None
    if versement is not None:
        dua = versement.dua_appliquee
        sort = versement.sort_final_applique
        echeance = versement.echeance_sort_final
        fondement = versement.regle.fondement_juridique
    elif regle is not None:
        dua = regle.dua
        sort = regle.sort_final
        echeance = echeance_sort(dossier.clos_le, regle.dua)
        fondement = regle.fondement_juridique
    else:
        dua = 0
        sort = ""
        echeance = None
        fondement = ""

    anomalies = anomalies_de(dossier, regle, versement)
    etat = _etat_versement(versement, anomalies)

    pieces = dossier.pieces.count()
    attendues = regle.pieces_attendues if regle else 0

    return {
        "id": versement.pk if versement else -dossier.pk,
        "reference": dossier.reference,
        "objet": dossier.objet,
        "typologie": typologie,
        "structure": dossier.structure.code,
        "closLe": dossier.clos_le.isoformat() if dossier.clos_le else "",
        "dua": dua,
        "sortFinal": LIBELLE_SORT.get(sort, sort),
        "echeanceSortFinal": echeance.isoformat() if echeance else None,
        "etat": etat,
        "pieces": pieces,
        "piecesAttendues": attendues,
        "feu": _feu_versement(etat, echeance, jour),
        "fondementJuridique": fondement,
        "_dossierId": dossier.pk,
        "_anomalies": anomalies,
        "_versement": versement,
    }


def echeance_sort(clos_le: date | None, dua: int) -> date | None:
    """
    La date a laquelle la DUA expire.

    Ajoutee en annees et non en jours : une DUA de cinq ans expire le meme
    quantieme cinq ans plus tard, pas 1 826 jours apres — et c'est ce qu'un
    bordereau de versement doit pouvoir dire sans discussion.
    """
    if clos_le is None:
        return None
    try:
        return clos_le.replace(year=clos_le.year + dua)
    except ValueError:
        # Un 29 fevrier reporte au 1er mars : un jour de conservation de plus
        # ne lese personne, un jour de moins serait une elimination anticipee.
        return date(clos_le.year + dua, 3, 1)


def anomalies_de(
    dossier: Dossier, regle: RegleConservation | None, versement: Versement | None
) -> list[dict]:
    """
    Ce qui empeche ou complique le versement.

    **Bloquante** ne veut pas dire grave, cela veut dire « le versement n'a pas
    de sens tant que ce n'est pas reglé ». Verser un dossier sans regle de
    conservation reviendrait a le deposer sans dire combien de temps on le
    garde ; c'est le seul cas ou l'application refuse.
    """
    anomalies: list[dict] = []

    if regle is None and versement is None:
        anomalies.append(
            {
                "libelle": "Aucune règle de conservation pour cette typologie",
                "precision": (
                    f"« {LIBELLE_TYPE.get(dossier.type_dossier, dossier.type_dossier)} » "
                    "n'a ni durée d'utilité administrative ni sort final. Le versement "
                    "ne peut pas être fait tant que le référentiel ne le dit pas."
                ),
                "bloquante": True,
            }
        )
    elif regle is not None and not regle.visee:
        anomalies.append(
            {
                "libelle": "Règle de conservation sans visa des archives",
                "precision": (
                    "La règle existe mais n'a pas été validée par le service des "
                    "archives (RF-ADM-05) : elle ne décide encore de rien."
                ),
                "bloquante": True,
            }
        )

    if regle is not None and regle.pieces_attendues:
        presentes = dossier.pieces.count()
        if presentes < regle.pieces_attendues:
            anomalies.append(
                {
                    "libelle": "Pièces manquantes",
                    "precision": (
                        f"{presentes} pièce(s) présente(s) sur "
                        f"{regle.pieces_attendues} attendue(s) pour cette typologie. "
                        "Un dossier incomplet versé est un dossier perdu."
                    ),
                    "bloquante": False,
                }
            )

    en_attente = dossier.complements.filter(recu_le__isnull=True).count()
    if en_attente:
        anomalies.append(
            {
                "libelle": "Compléments jamais reçus",
                "precision": (
                    f"{en_attente} pièce(s) réclamée(s) au demandeur et jamais reçue(s). "
                    "Le fonds gardera la trace de la demande, pas de la réponse."
                ),
                "bloquante": False,
            }
        )

    return anomalies


def _etat_versement(versement: Versement | None, anomalies: list[dict]) -> str:
    if any(anomalie["bloquante"] for anomalie in anomalies):
        return LIBELLE_ETAT_VERSEMENT["anomalie"]
    if versement is None:
        return LIBELLE_ETAT_VERSEMENT[ETAT_A_VERSER]
    return LIBELLE_ETAT_VERSEMENT.get(versement.etat, versement.etat)


def _feu_versement(etat: str, echeance: date | None, jour: date) -> str:
    """
    Le feu porte sur **l'echeance du sort final**, pas sur l'anciennete.

    Une DUA depassee sans que le sort final ait ete applique est rouge : c'est
    la non-conformite que le §3.12 cherche a rendre visible. Un versement deja
    fait n'a plus de feu — il n'y a plus rien a surveiller.
    """
    if etat == LIBELLE_ETAT_VERSEMENT["anomalie"]:
        return "rouge"
    if etat == LIBELLE_ETAT_VERSEMENT[ETAT_VERSE]:
        return "inconnu"
    if echeance is None:
        return "inconnu"
    if echeance < jour:
        return "rouge"
    return "vert"


def _compteurs_versements(lignes: list[dict], jour: date) -> list[dict]:
    a_verser = [ligne for ligne in lignes if ligne["etat"] == LIBELLE_ETAT_VERSEMENT[ETAT_A_VERSER]]
    anomalies = [ligne for ligne in lignes if ligne["etat"] == LIBELLE_ETAT_VERSEMENT["anomalie"]]
    depassees = [
        ligne
        for ligne in lignes
        if ligne["echeanceSortFinal"] and ligne["echeanceSortFinal"] < jour.isoformat()
    ]

    return [
        {
            "libelle": "En anomalie",
            "valeur": len(anomalies),
            "note": "versement impossible en l'état",
            "feu": "rouge" if anomalies else "vert",
        },
        {
            "libelle": "DUA échue",
            "valeur": len(depassees),
            "note": "le sort final aurait dû être appliqué",
            "feu": "rouge" if depassees else "vert",
        },
        {
            "libelle": "À verser",
            "valeur": len(a_verser),
            "note": "dossiers clos non encore versés",
            "feu": "orange" if a_verser else "vert",
        },
        {
            "libelle": "Dossiers clos",
            "valeur": len(lignes),
            "note": "l'ensemble du fonds constitué",
            "feu": "inconnu",
        },
    ]


# =====================================================================
#  La fiche d'un versement
# =====================================================================


def fiche(identifiant: int, aujourd_hui: date | None = None) -> dict:
    """
    La fiche d'un versement — conformite, chaine d'empreintes, integrite.

    L'identifiant est **negatif** pour un dossier pas encore verse : la file
    porte les deux, et il fallait pouvoir ouvrir la fiche d'un dossier avant
    son versement — c'est meme la seule facon de voir ce qui l'empeche.
    """
    from noyau.erreurs import HorsPerimetre

    jour = aujourd_hui or date.today()
    regles = {regle.typologie: regle for regle in RegleConservation.objects.filter(actif=True)}

    if identifiant < 0:
        dossier = Dossier.objects.filter(pk=-identifiant, etape=ETAPE_CLOS).first()
        versement = None
    else:
        versement = (
            Versement.objects.filter(pk=identifiant)
            .select_related("dossier", "regle", "verse_par")
            .first()
        )
        dossier = versement.dossier if versement else None

    if dossier is None:
        raise HorsPerimetre("Ce versement n'existe pas.")

    ligne = _ligne_versement(dossier, regles, versement, jour)

    return {
        **{cle: valeur for cle, valeur in ligne.items() if not cle.startswith("_")},
        "verseLe": versement.verse_le.date().isoformat()
        if versement and versement.verse_le
        else None,
        "versePar": _nom(versement.verse_par) if versement else None,
        "anomalies": ligne["_anomalies"],
        "piecesJointes": _pieces(dossier, regles.get(ligne["typologie"])),
        "chaineIntegrite": _chaine(versement),
    }


def _pieces(dossier: Dossier, regle: RegleConservation | None) -> list[dict]:
    """
    Les pieces du dossier, et celles qui manquent.

    Les manquantes apparaissent en ligne avec `presente = false` plutot que
    d'etre absentes : un bordereau de versement se lit pour ce qu'il contient
    **et** pour ce qu'il ne contient pas.
    """
    lignes = []
    for piece in dossier.pieces.prefetch_related("versions"):
        derniere = max(
            (version for version in piece.versions.all()),
            key=lambda version: version.version,
            default=None,
        )
        lignes.append(
            {
                "id": piece.pk,
                "nom": piece.nom,
                "format": piece.format_fichier,
                "taille": _taille(derniere.taille_octets) if derniere else "—",
                "presente": derniere is not None,
            }
        )

    attendues = regle.pieces_attendues if regle else 0
    for rang in range(len(lignes) + 1, attendues + 1):
        lignes.append(
            {
                "id": -rang,
                "nom": f"Pièce attendue n° {rang}",
                "format": "—",
                "taille": "—",
                "presente": False,
            }
        )
    return lignes


def _chaine(versement: Versement | None) -> list[dict]:
    """
    La chaine d'empreintes — RF-GED-09.

    Vide tant que le dossier n'est pas verse, et c'est exact : il n'y a rien a
    sceller avant. Une chaine affichee par avance aurait laisse croire a une
    preuve qui n'existe pas.
    """
    if versement is None:
        return []
    return [
        {
            "etape": maillon.etape,
            "horodatage": maillon.horodatage.isoformat(),
            "empreinte": maillon.empreinte,
        }
        for maillon in versement.maillons.all()
    ]


# =====================================================================
#  La conformite du fonds
# =====================================================================


def conformite(aujourd_hui: date | None = None) -> dict:
    """
    L'application effective du referentiel de conservation — §3.12.

    Vue de controle : elle dit ce qui ne va pas, elle ne donne aucun pouvoir
    d'agir. L'auditeur constate ; c'est l'archiviste qui verse.

    **Le taux sort a `null` sur un fonds vide.** Annoncer 100 % de conformite
    quand aucun dossier n'est clos est exactement le chiffre qu'un rapport
    recopierait avant qu'on le corrige (ADR 011).
    """
    jour = aujourd_hui or date.today()
    file = versements(aujourd_hui=jour)
    lignes = file["versements"]

    depassees = [
        ligne
        for ligne in lignes
        if ligne["echeanceSortFinal"]
        and ligne["echeanceSortFinal"] < jour.isoformat()
        and ligne["etat"] != LIBELLE_ETAT_VERSEMENT[ETAT_VERSE]
    ]

    typologies_reglees = {regle.typologie for regle in RegleConservation.objects.filter(actif=True)}
    sans_regle = sorted(
        {ligne["typologie"] for ligne in lignes if ligne["typologie"] not in typologies_reglees}
    )

    conformes = [
        ligne
        for ligne in lignes
        if ligne["etat"] == LIBELLE_ETAT_VERSEMENT[ETAT_VERSE]
        or (ligne["echeanceSortFinal"] and ligne["echeanceSortFinal"] >= jour.isoformat())
    ]
    taux = round(len(conformes) / len(lignes) * 100, 1) if lignes else None

    return {
        "compteurs": [
            {
                "libelle": "Échéances dépassées",
                "valeur": len(depassees),
                "note": "DUA expirée, sort final non appliqué",
                "feu": "rouge" if depassees else ("vert" if lignes else "inconnu"),
            },
            {
                "libelle": "Typologies sans règle",
                "valeur": len(sans_regle),
                "note": "des dossiers clos qu'aucune durée ne couvre",
                "feu": "rouge" if sans_regle else ("vert" if lignes else "inconnu"),
            },
            {
                "libelle": "Dossiers versés",
                "valeur": len(
                    [
                        ligne
                        for ligne in lignes
                        if ligne["etat"] == LIBELLE_ETAT_VERSEMENT[ETAT_VERSE]
                    ]
                ),
                "note": "entrés au fonds avec leur bordereau",
                "feu": "inconnu",
            },
        ],
        "echeancesDepassees": depassees,
        "typologiesSansRegle": sans_regle,
        "tauxConformite": taux,
    }


# =====================================================================
#  Menues fonctions
# =====================================================================


def algorithme() -> str:
    return ALGORITHME


def _nom(utilisateur: Utilisateur | None) -> str | None:
    if utilisateur is None:
        return None
    return f"{utilisateur.prenom} {utilisateur.nom}".strip() or None


def _taille(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")

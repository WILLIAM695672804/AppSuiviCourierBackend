"""
Lectures du pilier dossiers.

Le registre, la fiche d'instruction et la bibliotheque des courriers-type.

**Ce que ce module ne fait jamais : renvoyer une liste non restreinte.** Le
§3.5 est explicite — un point focal ne voit pas les dossiers des autres
structures. `restreindre()` est appele sur chaque requete, avec
`champ_agent="instructeur"` : c'est ce qui distingue l'agent instructeur, qui
ne voit que ses dossiers, du chef de service qui voit ceux de sa structure.

Rien n'est stocke de ce qui se deduit. Les jours restants, l'etat affiche et
le circuit franchi se lisent de la vue `v_dossier_etat` et du journal. Un
compteur stocke a cote de sa date est une seconde verite, et c'est toujours
elle qu'on finit par afficher (ADR 010).
"""

from datetime import date

from django.db import connection

from dossier.modeles import (
    CRITICITES,
    ETAPE_CLOS,
    ETAPES,
    RANG_ETAPES,
    TYPES,
    Dossier,
    ModeleCourrier,
)
from noyau.erreurs import HorsPerimetre
from noyau.identite.modeles import Utilisateur
from noyau.parametres import service as parametres
from noyau.perimetre.portee import restreindre

#: Les libelles affiches, dans les deux sens. Le stockage est sans accent
#: (`reclamation`), l'ecran en porte (« Réclamation ») : la conversion se fait
#: ici et nulle part ailleurs, sinon deux ecrans finissent par ne plus dire la
#: meme chose du meme dossier.
LIBELLE_TYPE = dict(TYPES)
LIBELLE_ETAPE = dict(ETAPES)
LIBELLE_CRITICITE = dict(CRITICITES)

LIBELLE_ETAT = {
    "en_cours": "En cours",
    "attente_complement": "En attente de complément",
    "retourne": "Retourné",
    "hors_delai": "Hors délai",
    "clos": "Clos",
}


def seuil_alerte_jours() -> int:
    """
    A partir de combien de jours restants le dossier passe a l'orange.

    **Aucune source** : trois jours parce qu'il faut une valeur, et parce que
    c'est ce qui reste pour reclamer une piece avant l'echeance. La valeur vit
    en base, en `hypothese`, pour que la Division du Suivi et de la Relance
    puisse la corriger sans redeploiement — voir A37.

    Relu a chaque appel, mais `parametres.valeur()` a son cache : c'est une
    lecture memoire, pas une requete par ligne de registre.
    """
    return int(parametres.valeur("dossier.seuil_alerte_jours", 3))


# =====================================================================
#  Le registre
# =====================================================================


def dossiers_visibles(utilisateur: Utilisateur):
    """Les dossiers vivants du perimetre de l'agent."""
    return restreindre(
        Dossier.objects.filter(invalide_le__isnull=True),
        utilisateur,
        champ_structure="structure",
        champ_agent="instructeur",
    ).select_related("structure", "instructeur", "regle_affectation")


def registre(utilisateur: Utilisateur, *, etape: str = "", etat: str = "") -> dict:
    """
    Le registre des dossiers a instruire.

    Les filtres arrivent avec les **libelles de l'ecran** (« Hors délai »,
    « Toutes ») parce que c'est ce que porte l'URL du front. Un libelle inconnu
    ne filtre rien plutot que de ne rien rendre : un filtre mal orthographie
    qui vide l'ecran se lit comme une panne, et l'agent appelle le support pour
    un accent.
    """
    lignes = list(dossiers_visibles(utilisateur))
    etats = _etats([ligne.pk for ligne in lignes])

    dossiers = [_ligne_registre(ligne, etats.get(ligne.pk)) for ligne in lignes]

    etape_cible = _cle(LIBELLE_ETAPE, etape)
    etat_cible = _cle(LIBELLE_ETAT, etat)
    retenus = [
        ligne
        for ligne in dossiers
        if (etape_cible is None or ligne["_etape"] == etape_cible)
        and (etat_cible is None or ligne["_etat"] == etat_cible)
    ]

    return {
        "dossiers": [_sans_technique(ligne) for ligne in retenus],
        "compteurs": _compteurs(dossiers),
        "total": len(retenus),
    }


def _cle(libelles: dict[str, str], demande: str) -> str | None:
    """La cle interne d'un libelle d'ecran. `None` quand le filtre n'en est pas un."""
    if not demande or demande in ("Toutes", "Tous"):
        return None
    for cle, libelle in libelles.items():
        if libelle == demande:
            return cle
    return None


def _etats(identifiants: list[int]) -> dict[int, dict]:
    """
    L'etat affiche de chaque dossier, lu dans `v_dossier_etat`.

    Une requete pour toute la liste et non une par ligne : le registre d'une
    direction porte quelques centaines de dossiers, et autant d'allers-retours
    auraient fait de l'ecran d'accueil de l'instructeur le plus lent de
    l'application.
    """
    if not identifiants:
        return {}

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT id, etat_affiche, jours_restants, complements_en_attente
              FROM v_dossier_etat
             WHERE id = ANY(%s)
            """,
            [identifiants],
        )
        return {
            ligne[0]: {
                "etat": ligne[1],
                "jours_restants": ligne[2],
                "complements": ligne[3],
            }
            for ligne in curseur.fetchall()
        }


def _ligne_registre(dossier: Dossier, etat: dict | None) -> dict:
    """
    Une ligne du registre.

    `etat` peut manquer si le dossier vient d'etre invalide entre les deux
    requetes. On se replie sur « en cours » plutot que de lever : un registre
    qui refuse de s'afficher pour une ligne evanouie est pire que la ligne.
    """
    courant = etat or {"etat": "en_cours", "jours_restants": 0, "complements": 0}
    reste = courant["jours_restants"]
    clos = courant["etat"] == "clos"

    return {
        "id": dossier.pk,
        "reference": dossier.reference,
        "objet": dossier.objet,
        "type": LIBELLE_TYPE.get(dossier.type_dossier, dossier.type_dossier),
        "demandeur": dossier.demandeur,
        "structure": dossier.structure.code,
        "instructeur": _nom(dossier.instructeur),
        "initiales": _initiales(dossier.instructeur),
        "ouvertLe": dossier.ouvert_le.isoformat(),
        "echeance": dossier.echeance.isoformat(),
        "etape": LIBELLE_ETAPE.get(dossier.etape, dossier.etape),
        "etat": LIBELLE_ETAT.get(courant["etat"], courant["etat"]),
        "criticite": LIBELLE_CRITICITE.get(dossier.criticite, dossier.criticite),
        "feu": _feu(reste, clos),
        "joursRestants": reste,
        "courrierOrigine": dossier.courrier_origine_reference,
        "courrierOrigineId": dossier.courrier_origine_id,
        # Les deux cles techniques servent le filtre et sortent avant la
        # reponse : le front lit des libelles, pas des codes.
        "_etape": dossier.etape,
        "_etat": courant["etat"],
    }


def _sans_technique(ligne: dict) -> dict:
    return {cle: valeur for cle, valeur in ligne.items() if not cle.startswith("_")}


def _feu(jours_restants: int, clos: bool) -> str:
    """
    Le feu d'un dossier se lit du temps qui reste, pas d'un avancement.

    Un dossier clos n'est ni vert ni rouge : il est **inconnu** au sens du feu,
    parce qu'il n'y a plus rien a surveiller. Le colorer en vert aurait fait
    passer pour une reussite un dossier clos avec trois semaines de retard.
    """
    if clos:
        return "inconnu"
    if jours_restants < 0:
        return "rouge"
    if jours_restants <= seuil_alerte_jours():
        return "orange"
    return "vert"


def _compteurs(dossiers: list[dict]) -> list[dict]:
    """
    Quatre compteurs, et le premier est celui qui appelle une action.

    Les dossiers clos ne sont comptes nulle part ailleurs que dans « clos » :
    les melanger au total ferait grossir un chiffre que personne ne peut faire
    baisser.
    """
    ouverts = [ligne for ligne in dossiers if ligne["_etat"] != "clos"]
    hors_delai = [ligne for ligne in ouverts if ligne["_etat"] == "hors_delai"]
    attente = [ligne for ligne in ouverts if ligne["_etat"] == "attente_complement"]
    seuil = seuil_alerte_jours()
    proches = [ligne for ligne in ouverts if 0 <= ligne["joursRestants"] <= seuil]

    return [
        {
            "libelle": "Hors délai",
            "valeur": len(hors_delai),
            "note": "échéance d'instruction dépassée",
            "feu": "rouge" if hors_delai else "vert",
        },
        {
            "libelle": "À échéance sous 3 jours",
            "valeur": len(proches),
            "note": "encore tenable si l'on s'y met",
            "feu": "orange" if proches else "vert",
        },
        {
            "libelle": "En attente de complément",
            "valeur": len(attente),
            "note": "le délai continue de courir",
            "feu": "orange" if attente else "vert",
        },
        {
            "libelle": "En cours d'instruction",
            "valeur": len(ouverts),
            "note": "dossiers non clos du périmètre",
            "feu": "inconnu",
        },
    ]


# =====================================================================
#  La fiche d'instruction
# =====================================================================


def fiche(utilisateur: Utilisateur, identifiant: int) -> dict:
    """
    Le dossier en entier — circuit, regle d'affectation, pieces et historique.

    Un dossier hors perimetre rend **404** et non 403 : repondre « vous n'avez
    pas le droit » confirmerait son existence et celle de son demandeur a qui
    n'a pas a les connaitre (D5).
    """
    dossier = dossiers_visibles(utilisateur).filter(pk=identifiant).first()
    if dossier is None:
        raise HorsPerimetre("Ce dossier n'existe pas ou n'est pas dans votre périmètre.")

    etat = _etats([dossier.pk]).get(dossier.pk)
    ligne = _ligne_registre(dossier, etat)

    return {
        **_sans_technique(ligne),
        "contexte": dossier.contexte or "",
        "regleAffectation": dossier.regle_affectation_texte,
        "seuil": _seuil(dossier),
        "etapes": _circuit(dossier),
        "pieces": _pieces(dossier),
        "complements": _complements(dossier),
        "historique": historique(dossier.pk),
    }


def _seuil(dossier: Dossier) -> str | None:
    """
    Le seuil de montant qui a fait jouer la regle, ecrit en toutes lettres.

    `None` quand la regle appliquee n'en porte pas — et non « 0 F CFA », qui se
    lirait comme un seuil que tout dossier franchit.
    """
    regle = dossier.regle_affectation
    if regle is None or regle.montant_minimum is None:
        return None
    return f"Montant supérieur à {regle.montant_minimum:n} F CFA"


def _circuit(dossier: Dossier) -> list[dict]:
    """
    Les cinq etapes, franchies et a venir.

    L'instructeur doit savoir **qui validera apres lui** : un circuit qui ne
    montre que l'etape courante oblige a demander, et c'est la question qu'un
    outil de suivi est cense supprimer.

    La date et l'acteur d'une etape franchie se lisent au journal. Une etape
    franchie avant la mise en service du journal sort sans date : elle est
    franchie, on ne sait pas quand, et c'est ce qui s'affiche.
    """
    faits = _franchissements(dossier.pk)
    rang_courant = RANG_ETAPES.get(dossier.etape, 1)

    circuit = []
    for code, libelle in ETAPES:
        rang = RANG_ETAPES[code]
        fait = faits.get(code)
        circuit.append(
            {
                "code": libelle,
                "libelle": libelle,
                "franchie": rang < rang_courant or dossier.etape == ETAPE_CLOS,
                "date": fait["date"] if fait else None,
                "acteur": fait["acteur"] if fait else None,
            }
        )
    return circuit


def _franchissements(identifiant: int) -> dict[str, dict]:
    """Quand chaque etape a ete franchie, et par qui — lu au journal."""
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT e.donnees ->> 'etapeApres' AS etape,
                   max(e.survenu_le) AS quand,
                   max(coalesce(u.prenom || ' ', '') || coalesce(u.nom, '')) AS acteur
              FROM evenement e
              LEFT JOIN utilisateur u ON u.id = e.acteur_id
             WHERE e.objet_type = 'dossier'
               AND e.objet_id = %s
               AND e.donnees ->> 'etapeApres' IS NOT NULL
             GROUP BY e.donnees ->> 'etapeApres'
            """,
            [identifiant],
        )
        return {
            ligne[0]: {
                "date": ligne[1].date().isoformat() if ligne[1] else None,
                "acteur": (ligne[2] or "").strip() or None,
            }
            for ligne in curseur.fetchall()
        }


def _pieces(dossier: Dossier) -> list[dict]:
    """
    Les pieces et **toutes** leurs versions — RF-GED-04.

    La version courante est la derniere deposee ; les precedentes restent
    listees. Sans elles, on ne peut plus dire sur quoi la decision a ete prise,
    et c'est precisement ce qu'un contentieux demande.
    """
    lignes = []
    for piece in dossier.pieces.prefetch_related("versions__depose_par"):
        versions = sorted(piece.versions.all(), key=lambda v: v.version)
        derniere = versions[-1].version if versions else 0
        lignes.append(
            {
                "id": piece.pk,
                "nom": piece.nom,
                "format": piece.format_fichier,
                "versions": [
                    {
                        "version": version.version,
                        "deposeLe": version.depose_le.date().isoformat(),
                        "deposePar": _nom(version.depose_par),
                        "taille": _taille(version.taille_octets),
                        "courante": version.version == derniere,
                    }
                    for version in versions
                ],
            }
        )
    return lignes


def _complements(dossier: Dossier) -> list[dict]:
    return [
        {
            "id": complement.pk,
            "objet": complement.objet,
            "demandeLe": complement.demande_le.isoformat(),
            "demandePar": _nom(complement.demande_par),
            "echeance": complement.echeance.isoformat(),
            "recuLe": complement.recu_le.isoformat() if complement.recu_le else None,
        }
        for complement in dossier.complements.select_related("demande_par")
    ]


#: Ce que le journal inscrit, traduit pour l'ecran. Un type inconnu s'affiche
#: tel quel plutot que de disparaitre : un historique qui perd des lignes selon
#: la version du code ne vaut rien comme historique.
LIBELLE_EVENEMENT = {
    "dossier_ouvert": "Ouverture",
    "dossier_affecte": "Affectation",
    "dossier_complement_demande": "Demande de complément",
    "dossier_complement_recu": "Complément reçu",
    "dossier_piece_deposee": "Dépôt de pièce",
    "dossier_courrier_fusionne": "Projet de réponse",
    "dossier_retour_etape": "Retour à l'étape antérieure",
    "dossier_valide": "Validation",
    "dossier_notifie": "Notification",
    "dossier_clos": "Clôture",
}


def historique(identifiant: int) -> list[dict]:
    """
    L'histoire du dossier, lue au journal du noyau.

    **Il n'y a pas de seconde table.** Une table d'evenements propre au dossier
    aurait produit deux histoires du meme objet, et c'est toujours la moins
    complete qu'on finit par lire (ADR 012).
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT e.id, e.type_evenement, e.survenu_le, e.libelle, e.detail,
                   u.prenom, u.nom, p.libelle AS poste,
                   e.donnees ->> 'etapeAvant', e.donnees ->> 'etapeApres'
              FROM evenement e
              LEFT JOIN utilisateur u ON u.id = e.acteur_id
              LEFT JOIN poste p ON p.id = u.poste_id
             WHERE e.objet_type = 'dossier' AND e.objet_id = %s
             ORDER BY e.survenu_le DESC
            """,
            [identifiant],
        )
        lignes = curseur.fetchall()

    faits = []
    for (
        pk,
        type_evenement,
        survenu_le,
        libelle,
        detail,
        prenom,
        nom,
        poste,
        avant,
        apres,
    ) in lignes:
        auteur = f"{prenom or ''} {nom or ''}".strip()
        faits.append(
            {
                "id": pk,
                "type": LIBELLE_EVENEMENT.get(type_evenement, type_evenement),
                "date": survenu_le.isoformat(),
                "auteur": auteur or "—",
                "initiales": _initiales_de(prenom, nom),
                "poste": poste or "—",
                "texte": detail or libelle,
                "etapeAvant": LIBELLE_ETAPE.get(avant) if avant else None,
                "etapeApres": LIBELLE_ETAPE.get(apres) if apres else None,
            }
        )
    return faits


# =====================================================================
#  La bibliotheque des courriers-type
# =====================================================================


def modeles() -> dict:
    """
    Les courriers-type, **corps entier compris**.

    Le corps n'est pas tronque a l'envoi : un agent qui choisit un modele sur
    trois lignes de resume decouvre ce qu'il a envoye apres l'avoir envoye.
    C'est un courrier signe par l'institution — il se lit avant.
    """
    return {
        "modeles": [
            {
                "id": modele.pk,
                "code": modele.code,
                "libelle": modele.libelle,
                "typologie": modele.typologie,
                "description": modele.description or "",
                "variables": variables_du_corps(modele.corps),
                "corps": modele.corps,
                "misAJourLe": (modele.modifie_le or modele.cree_le).date().isoformat(),
                "misAJourPar": "—",
                "utilisations": modele.utilisations,
            }
            for modele in ModeleCourrier.objects.filter(actif=True)
        ]
    }


def variables_du_corps(corps: str) -> list[str]:
    """
    Les variables **derivees du corps**, jamais saisies a cote.

    Deux listes divergent, et la premiere fusion qui laisse un `{demandeur}` en
    clair dans un courrier signe par le Directeur general est de celles qu'on
    n'oublie pas. L'ordre est celui de l'apparition : c'est celui dans lequel
    l'agent lit son modele.
    """
    trouvees: list[str] = []
    reste = corps
    while "{" in reste:
        debut = reste.index("{")
        if "}" not in reste[debut:]:
            break
        fin = reste.index("}", debut)
        nom = reste[debut + 1 : fin].strip()
        if nom and nom not in trouvees:
            trouvees.append(nom)
        reste = reste[fin + 1 :]
    return trouvees


# =====================================================================
#  Ce qui sert ailleurs
# =====================================================================


def instruction_dans_le_delai(
    structures=None, *, a_la_date: date | None = None, depuis: date | None = None
) -> tuple[int, int]:
    """
    Le taux de dossiers clos dans le delai — la mesure que le pilotage attend.

    Rend `(dans_le_delai, clos)` et non un taux : c'est l'appelant qui decide
    ce qu'il fait d'un denominateur nul. Zero dossier clos ne fait pas zero
    pour cent, il fait « non mesuré » (ADR 011).

    Sans `depuis`, le compte est cumulatif depuis la mise en service : c'est ce
    qu'attendent les tableaux de bord, qui disent « ou en sommes-nous ». Les
    rapports periodiques passent les deux bornes, parce qu'un document date qui
    inclurait les dossiers des annees precedentes ne parlerait pas de sa
    periode.
    """
    jour = a_la_date or date.today()
    requete = Dossier.objects.filter(
        invalide_le__isnull=True, etape=ETAPE_CLOS, clos_le__isnull=False, clos_le__lte=jour
    )
    if depuis is not None:
        requete = requete.filter(clos_le__gte=depuis)
    if structures is not None:
        identifiants = [structure.pk for structure in structures]
        if not identifiants:
            return (0, 0)
        requete = requete.filter(structure_id__in=identifiants)

    clos = 0
    dans_le_delai = 0
    for clos_le, echeance in requete.values_list("clos_le", "echeance"):
        clos += 1
        # `clos_le__isnull=False` est dans le filtre ; mypy ne lit pas les
        # querysets, la garde le lui dit.
        if clos_le is not None and clos_le <= echeance:
            dans_le_delai += 1
    return (dans_le_delai, clos)


# =====================================================================
#  Menues fonctions d'affichage
# =====================================================================


def _nom(utilisateur: Utilisateur | None) -> str:
    if utilisateur is None:
        return "—"
    return f"{utilisateur.prenom} {utilisateur.nom}".strip() or "—"


def _initiales(utilisateur: Utilisateur | None) -> str:
    if utilisateur is None:
        return "—"
    return _initiales_de(utilisateur.prenom, utilisateur.nom)


def _initiales_de(prenom: str | None, nom: str | None) -> str:
    lettres = f"{(prenom or '')[:1]}{(nom or '')[:1]}".upper()
    return lettres or "—"


def _taille(octets: int) -> str:
    """
    La taille, dans l'unite ou elle se lit.

    Un fichier de 2 400 000 octets se dit « 2,3 Mo », pas « 2400000 » : le
    chiffre exact n'apprend rien a l'agent qui verifie qu'il a bien depose le
    bon fichier.
    """
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")


def dossiers_de_l_agent(
    utilisateur: Utilisateur, *, a_la_date: date | None = None
) -> tuple[int, int]:
    """
    Ce qu'un agent a sur les bras : `(hors delai, ouverts)`.

    Le tableau de bord en perimetre personnel demandait cette mesure et n'avait
    rien pour la rendre. Elle porte sur les dossiers dont l'agent est
    **instructeur nomme**, et non sur ceux de sa structure : c'est la difference
    entre « votre service en a trente » et « vous en avez quatre », et c'est la
    seconde qui appelle un geste.

    Rend un couple et non un taux, pour la raison d'`instruction_dans_le_delai` :
    zero dossier n'est pas zero pour cent (ADR 011).
    """
    jour = a_la_date or date.today()
    ouverts = Dossier.objects.filter(invalide_le__isnull=True, instructeur=utilisateur).exclude(
        etape=ETAPE_CLOS
    )
    return (ouverts.filter(echeance__lt=jour).count(), ouverts.count())

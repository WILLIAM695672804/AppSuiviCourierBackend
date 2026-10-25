"""
Ce que l'ecran de parametrage affiche — H-01 a H-06.

Neuf onglets, une seule route. C'est un choix : les referentiels sont petits —
quelques dizaines de lignes chacun — et l'administrateur passe de l'un a
l'autre en permanence. Neuf appels auraient fait clignoter l'ecran a chaque
onglet pour economiser quelques kilo-octets.

**Les libelles sont traduits ici, une fois.** Le front affiche « Escalade au
supérieur » et « Tout courrier (règle de repli) » ; la base porte
`escalade_vers_poste_id` et quatre colonnes nulles. Deporter la traduction au
front l'aurait rendu dependant du schema, et deux ecrans auraient fini par
nommer differemment la meme chose.

**Ce qui sort a zero, et pourquoi.** `usage`, `declenchements`,
`nombreCourriers`, `respect90j`, `documents`, `declenchements30j` comptent tous
des courriers ou des documents. Le pilier courrier et la GED ne sont pas
commences : ces compteurs valent zero, et c'est exact. Les remplir de valeurs
plausibles serait la seule facon de rendre l'ecran faux.
"""

from collections import defaultdict
from unicodedata import combining, normalize

from noyau.organisation.modeles import NiveauHierarchique
from noyau.parametrage.modeles import (
    Circuit,
    CircuitEtape,
    CircuitRegle,
    CircuitVersion,
    Correspondant,
    MentionType,
    Nature,
    RubriqueClassement,
    SeuilAlerte,
)
from noyau.parametres import services as parametres

#: Ce que le front attend dans la colonne « Escalade ». Trois valeurs, pas une
#: de plus : le contrat de `EtapeCircuit` les enumere.
ESCALADE_SUPERIEUR = "Escalade au supérieur"
ESCALADE_RELANCE = "Relance automatique"
ESCALADE_AUCUNE = "Aucune"

#: Le libelle du sens tel qu'il se lit dans une phrase de condition.
SENS = {"arrive": "à l'arrivée", "depart": "au départ", "interne": "en interne"}

CATEGORIES_CORRESPONDANT = {
    "externe": "Externe",
    "interne": "Interne",
    "usager": "Usager",
    "administration": "Administration",
}

OPERATEURS = {"superieur": "supérieur à", "inferieur": "inférieur à"}
CANAUX = {
    "notification": "Notification interne",
    "courriel": "Courriel",
    "les_deux": "Les deux",
}


def parametrage() -> dict:
    """Les neuf referentiels, dans l'ordre des onglets."""
    versions = _dernieres_versions()
    etapes = _etapes(versions)

    return {
        "circuits": _circuits(versions, etapes),
        "etapes": etapes,
        "regles": _regles(),
        "mentions": _mentions(),
        "correspondants": _correspondants(),
        "engagements": _engagements(),
        "classement": _classement(),
        "seuils": _seuils(),
        # Les regles de gestion vivent dans un autre pilier — `noyau.parametres`
        # porte la table et son cache. La lecture est deleguee, pas recopiee :
        # l'ordre « hypotheses en tete » est une decision du service, et deux
        # tris divergents feraient d'un arbitrage en attente une ligne perdue au
        # milieu des autres.
        "reglesMetier": parametres.regles(),
    }


# =====================================================================
#  Circuits et etapes
# =====================================================================


def _dernieres_versions() -> dict[int, CircuitVersion]:
    """
    La version la plus recente de chaque circuit.

    **La plus recente et non la plus recemment publiee** : un circuit en cours
    de refonte a une version non publiee, et c'est celle que l'administrateur
    modifie. La lui cacher lui ferait croire que ses etapes n'ont pas ete
    enregistrees.
    """
    dernieres: dict[int, CircuitVersion] = {}
    for version in CircuitVersion.objects.select_related("niveau_max").order_by(
        "circuit_id", "version"
    ):
        dernieres[version.circuit_id] = version
    return dernieres


def _etapes(versions: dict[int, CircuitVersion]) -> list[dict]:
    """
    Les etapes des versions courantes, a plat.

    Elles sortent **toutes ensemble** et non par circuit : l'onglet « Étapes et
    escalades » les presente en une seule liste, `circuitId` servant a les
    regrouper. C'est aussi ce qui permet de reperer d'un coup d'oeil un circuit
    dont aucune etape ne porte de delai.
    """
    par_version = {version.pk: circuit_id for circuit_id, version in versions.items()}
    if not par_version:
        return []

    lignes = []
    for etape in (
        CircuitEtape.objects.filter(circuit_version_id__in=par_version)
        .select_related("poste", "escalade_vers_poste")
        .order_by("circuit_version_id", "rang")
    ):
        lignes.append(
            {
                "id": etape.pk,
                "circuitId": par_version[etape.circuit_version_id],
                "rang": etape.rang,
                "libelle": etape.libelle,
                "acteur": _acteur(etape),
                "delaiJours": etape.delai_jours or 0,
                "escalade": _escalade(etape),
                "alerteAvant": etape.alerte_avant_jours,
                "bloquante": etape.bloquante,
            }
        )
    return lignes


def _acteur(etape: CircuitEtape) -> str:
    """
    Qui agit a cette etape, du plus precis au plus general.

    Trois colonnes peuvent le dire et elles ne sont pas redondantes : un poste
    nomme (le DG signe), un profil (un agent d'enregistrement quelconque) ou
    une permission (quiconque peut valider). La plus precise renseignee gagne.
    """
    if etape.poste is not None:
        return etape.poste.libelle

    from noyau.habilitation.modeles import Permission, Profil

    if etape.profil_id:
        profil = Profil.objects.filter(pk=etape.profil_id).first()
        if profil:
            return profil.libelle
    if etape.permission_requise_id:
        permission = Permission.objects.filter(pk=etape.permission_requise_id).first()
        if permission:
            return f"Toute personne portant « {permission.libelle} »"

    # Jamais une chaine vide : une cellule vide se lit comme une donnee
    # manquante a l'affichage, pas comme une etape ouverte a tous.
    return "Non défini"


def _escalade(etape: CircuitEtape) -> str:
    """
    Ce qui se produit a l'echeance.

    Un poste d'escalade renseigne l'emporte sur tout : c'est le cas le plus
    fort, l'affaire change de main. Sinon, un delai sans escalade produit une
    relance — quelqu'un est prevenu, personne n'est dessaisi. Sans delai, rien
    ne peut se declencher.
    """
    if etape.escalade_vers_poste_id:
        return ESCALADE_SUPERIEUR
    if etape.delai_jours:
        return ESCALADE_RELANCE
    return ESCALADE_AUCUNE


def _circuits(versions: dict[int, CircuitVersion], etapes: list[dict]) -> list[dict]:
    """
    Les modeles de circuit, avec le poids de chacun.

    `delaiCible` est la **somme des delais d'etape**, et non un delai propre au
    circuit : il n'en existe pas en base, et en creer un aurait ouvert la porte
    a un circuit dont le total des etapes contredit son delai affiche.
    """
    nombre: dict[int, int] = defaultdict(int)
    delai: dict[int, int] = defaultdict(int)
    for etape in etapes:
        nombre[etape["circuitId"]] += 1
        delai[etape["circuitId"]] += etape["delaiJours"]

    applique = _s_applique_a()

    lignes = []
    for circuit in Circuit.objects.filter(invalide_le__isnull=True):
        version = versions.get(circuit.pk)
        lignes.append(
            {
                "id": circuit.pk,
                "libelle": circuit.libelle,
                "sappliqueA": applique.get(circuit.pk, "Aucune règle de sélection"),
                "nombreEtapes": nombre.get(circuit.pk, 0),
                "delaiCible": delai.get(circuit.pk, 0),
                # Le pilier courrier n'existe pas : aucun courrier n'a encore
                # emprunte de circuit. Zero est exact.
                "usage": 0,
                "actif": circuit.actif and version is not None,
            }
        )
    return lignes


def _s_applique_a() -> dict[int, str]:
    """
    A quoi chaque circuit s'applique, en une phrase.

    Construite depuis ses regles de selection, parce que c'est la seule verite :
    un libelle saisi a la main aurait cesse d'etre juste des la premiere regle
    ajoutee.
    """
    phrases: dict[int, list[str]] = defaultdict(list)
    for regle in CircuitRegle.objects.filter(actif=True).select_related("structure", "nature"):
        phrases[regle.circuit_id].append(_condition(regle))
    return {circuit_id: " ; ".join(liste) for circuit_id, liste in phrases.items()}


# =====================================================================
#  Regles de selection
# =====================================================================


def _regles() -> list[dict]:
    """
    Dans l'ordre ou elles sont evaluees.

    L'ordre est celui de la priorite, la plus petite d'abord, et il n'est pas
    cosmetique : **la premiere regle qui correspond gagne**. Afficher ces
    lignes triees autrement — par circuit, par nom — donnerait une lecture
    fausse de ce qui va se passer.
    """
    lignes = []
    for ordre, regle in enumerate(
        CircuitRegle.objects.filter(actif=True)
        .select_related("circuit", "structure", "nature")
        .order_by("priorite", "id"),
        start=1,
    ):
        lignes.append(
            {
                "id": regle.pk,
                "ordre": ordre,
                "condition": _condition(regle),
                "circuit": regle.circuit.libelle,
                "declenchements": 0,
                "repli": regle.repli,
            }
        )
    return lignes


def _condition(regle: CircuitRegle) -> str:
    """
    La regle, en francais.

    Une regle sans aucun critere est le **repli** : elle s'applique a ce que
    rien d'autre n'a pris. Le dire explicitement importe — un tableau ou la
    derniere ligne aurait une condition vide se lirait comme une regle
    inachevee, alors que c'est le filet.
    """
    morceaux = []
    if regle.sens:
        morceaux.append(f"courrier {SENS.get(regle.sens, regle.sens)}")
    if regle.nature is not None:
        morceaux.append(f"de nature « {regle.nature.libelle} »")
    if regle.structure is not None:
        morceaux.append(f"pour {regle.structure.code}")
    if regle.confidentiel is True:
        morceaux.append("confidentiel")
    elif regle.confidentiel is False:
        morceaux.append("non confidentiel")

    if not morceaux:
        return "Tout courrier (règle de repli)"
    return "Tout " + " ".join(morceaux)


# =====================================================================
#  Mentions
# =====================================================================


def _mentions() -> list[dict]:
    """
    Les mentions portees a la cotation.

    `comportement` et `niveauxAutorises` sont administres et pour l'instant
    vides : ce que chaque mention declenche relevera du pilier courrier, et
    l'ecrire d'avance reviendrait a decider a sa place. Voir A25.
    """
    connus = dict(NiveauHierarchique.objects.values_list("code", "libelle"))

    lignes = []
    for mention in MentionType.objects.filter(invalide_le__isnull=True):
        codes = mention.niveaux_autorises or []
        lignes.append(
            {
                "id": mention.pk,
                "libelle": mention.libelle,
                "delaiAssocie": mention.delai_jours,
                "comportement": mention.comportement or "Non défini",
                # Le code inconnu est rendu tel quel plutot qu'ecarte : un
                # niveau supprime doit rester visible, sinon la mention parait
                # ouverte a tous.
                "niveauxAutorises": [connus.get(code, code) for code in codes],
                "active": mention.actif,
            }
        )
    return lignes


# =====================================================================
#  Correspondants
# =====================================================================


def _correspondants() -> list[dict]:
    """
    Le carnet d'adresses, doublons signales.

    Le signalement est un **soupcon**, jamais une fusion : deux directions
    departementales du meme ministere portent legitimement le meme nom
    normalise. C'est a l'administrateur de trancher, et l'ecran le lui montre
    plutot que de choisir a sa place.
    """
    correspondants = list(Correspondant.objects.filter(invalide_le__isnull=True))

    empreintes: dict[str, int] = defaultdict(int)
    for correspondant in correspondants:
        empreintes[_normaliser(correspondant.designation)] += 1

    return [
        {
            "id": correspondant.pk,
            "libelle": correspondant.designation,
            "categorie": CATEGORIES_CORRESPONDANT.get(correspondant.type, correspondant.type),
            "ville": correspondant.ville or "—",
            "nombreCourriers": 0,
            "doublonPresume": empreintes[_normaliser(correspondant.designation)] > 1,
        }
        for correspondant in correspondants
    ]


def _normaliser(texte: str) -> str:
    """
    Sans accents, sans casse, sans espaces multiples.

    « Direction Générale des Impôts » et « DIRECTION GENERALE DES IMPOTS » sont
    le meme correspondant saisi deux fois ; sans normalisation, aucun doublon
    ne serait jamais detecte.
    """
    sans_accent = "".join(c for c in normalize("NFD", texte.lower()) if not combining(c))
    return " ".join(sans_accent.split())


# =====================================================================
#  Delais et engagements
# =====================================================================


def _engagements() -> list[dict]:
    """
    Le delai cible par nature de courrier.

    **Il n'y a pas de referentiel d'engagement separe.** Le delai vit sur la
    nature, ou le socle l'a mis ; en creer un second, attache a autre chose,
    aurait garanti qu'un jour les deux se contredisent.
    """
    return [
        {
            "id": nature.pk,
            "libelle": nature.libelle,
            "delaiCible": nature.delai_defaut_jours or 0,
            "premiereAlerte": nature.alerte_avant_jours or 0,
            # Le taux de respect se mesure sur des courriers traites. Il n'y en
            # a aucun : zero est exact, et un chiffre plausible serait recopie.
            "respect90j": 0,
        }
        for nature in Nature.objects.filter(invalide_le__isnull=True, actif=True)
    ]


# =====================================================================
#  Plan de classement
# =====================================================================


def _classement() -> list[dict]:
    """
    L'arborescence de rangement — RF-GED-07.

    La profondeur est calculee au serveur, comme pour l'organigramme, et pour
    la meme raison : le front indente avec, et une profondeur qu'il
    recalculerait lui-meme dependrait de l'ordre dans lequel il recoit les
    lignes.

    Une rubrique dont le parent a disparu remonte a la racine. On ne fabrique
    pas de rattachement.
    """
    rubriques = {
        rubrique.pk: rubrique for rubrique in RubriqueClassement.objects.filter(actif=True)
    }

    def profondeur(rubrique) -> int:
        niveau = 0
        courant = rubrique
        visitees = {courant.pk}
        while courant.parent_id and courant.parent_id in rubriques:
            courant = rubriques[courant.parent_id]
            if courant.pk in visitees:
                break
            visitees.add(courant.pk)
            niveau += 1
        return niveau

    return [
        {
            "id": rubrique.pk,
            "code": rubrique.code,
            "libelle": rubrique.libelle,
            "niveau": profondeur(rubrique),
            "parentId": rubrique.parent_id if rubrique.parent_id in rubriques else None,
            "documents": 0,
            "typologiesAssociees": rubrique.typologies or [],
        }
        for rubrique in rubriques.values()
    ]


# =====================================================================
#  Seuils d'alerte
# =====================================================================


def _seuils() -> list[dict]:
    """
    Les alertes automatiques — RF-BI-05, RF-ADM-04.

    Le destinataire est rendu en clair, poste ou libelle libre. Sans lui, une
    alerte n'est qu'une couleur a l'ecran : quelqu'un doit etre prevenu, et
    c'est ce qui distingue un seuil d'un affichage conditionnel.
    """
    lignes = []
    for seuil in SeuilAlerte.objects.select_related("destinataire"):
        lignes.append(
            {
                "id": seuil.pk,
                "indicateur": seuil.indicateur,
                "perimetre": seuil.perimetre,
                "operateur": OPERATEURS.get(seuil.operateur, seuil.operateur),
                # Le front affiche le nombre tel quel : un seuil de 48 heures ne
                # doit pas s'afficher « 48,00 ».
                "valeur": float(seuil.valeur),
                "unite": seuil.unite,
                "destinataire": (
                    seuil.destinataire.libelle
                    if seuil.destinataire is not None
                    else (seuil.destinataire_libelle or "Non défini")
                ),
                "canal": CANAUX.get(seuil.canal, seuil.canal),
                "actif": seuil.actif,
                "declenchements30j": 0,
            }
        )
    return lignes

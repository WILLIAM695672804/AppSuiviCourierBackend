"""
Ce que le pilier courrier rend a lire.

**Toute fonction de ce module part de `visibilite.visibles()`.** Aucune ne pose
son filtre elle-meme : c'est la regle 2 de `noyau/perimetre/portee.py`, et
l'oubli ne produit aucune erreur — juste une fuite. Voir l'ADR 022 pour les
quatre portes.

Deux principes de calcul, repris du pilier activites :

 1. **L'etape est deduite, jamais stockee.** Les neuf etapes que le front affiche
    resultent de l'existence d'une cotation, d'une affectation, d'un traitement et
    de `statut_courrier`. Une colonne `etape` aurait impose de la reecrire partout
    ou l'une de ses sources change, et garanti qu'un jour les deux se
    contrediraient. C'est l'arbitrage n° 2 du pilier activites.

 2. **Ce qui n'a pas de source sort nomme, pas invente.** `modeCotation` est
    `None` et `variation` dit « Non mesuré » : ADR 011. Une valeur plausible est
    recopiee ; une valeur absente se voit.

**Les vocabulaires se traduisent ici, une seule fois**, dans les tables
`*_VERS_FRONT`. La base dit `arrive`, le front dit `ARRIVEE` ; la base a quatre
priorites, le front en a trois. Le piege est sournois — un `str` en face d'un
`str` passe toutes les revues de schemas — et il a deja coute quatre registres
vides le 16 aout. Voir `docs/pieges.md`.
"""

from collections import defaultdict
from datetime import date, datetime

from django.contrib.postgres.search import SearchQuery
from django.db import connection, models
from django.utils import timezone

from courrier.cloisonnement import lit_le_dossier_de, structures_lisibles
from courrier.modeles import (
    REPONSE_EN_SIGNATURE,
    REPONSE_SIGNEE,
    SENS_ARRIVE,
    SENS_DEPART,
    SENS_INTERNE,
    STATUT_CLOTURE,
    Affectation,
    Cotation,
    Courrier,
    Observation,
    SignalementEcart,
    Traitement,
)
from courrier.visibilite import session_en_cours, visibles
from noyau.calendrier import jours_ouvres_entre
from noyau.erreurs import HorsPerimetre
from noyau.habilitation.dependances import PERM
from noyau.habilitation.resolution import possede
from noyau.identite.modeles import Utilisateur
from noyau.parametres import service as parametres
from noyau.perimetre.portee import structures_visibles
from noyau.pieces.modeles import PieceJointe

# =====================================================================
#  Vocabulaires — la seule traduction du pilier
# =====================================================================

#: `courrier.sens` -> `SensCourrier` du front. La base ecrit sans accent et sans
#: e final, le front avec : deux mots pour la meme chose, et la comparaison de
#: schemas ne le voit pas.
SENS_VERS_FRONT = {
    SENS_ARRIVE: "ARRIVEE",
    SENS_DEPART: "DEPART",
    SENS_INTERNE: "INTERNE",
}
SENS_DEPUIS_FRONT = {valeur: cle for cle, valeur in SENS_VERS_FRONT.items()}

#: `session.code` -> `courrier.sens`. La session confidentielle porte `sens =
#: 'arrive'` au socle : un courrier confidentiel entrant est **a la fois** arrive
#: et confidentiel. Deux colonnes, deux questions.
SENS_DEPUIS_SESSION = {
    "arrive": SENS_ARRIVE,
    "depart": SENS_DEPART,
    "interne": SENS_INTERNE,
    "confidentiel": SENS_ARRIVE,
}

#: `typeSession` de l'ecran A-01 -> `session.code`.
SESSION_DEPUIS_FRONT = {
    "ARRIVE": "arrive",
    "DEPART": "depart",
    "INTERNE": "interne",
    "CONFIDENTIEL": "confidentiel",
}

#: `priorite.code` -> `PrioriteCourrier` du front. Quatre valeurs en base, trois
#: au front : la traduction est **volontairement lossy**, et le sens des mots est
#: preserve — `URGENT` (« Urgent ») devient `URGENTE` (« Urgent »), et non
#: `TRES_URGENTE`, sans quoi l'agent qui coche « Urgent » relirait « Très
#: urgent ».
#:
#: Consequence assumee : `TRES_URGENTE` n'est **jamais emis**. Aucun ecran ne
#: permet de poser ce niveau, et emettre une valeur qu'aucune saisie ne produit
#: est exactement le defaut releve le 16 aout — six libelles de filtre contre
#: trois codes jamais emis. Voir `docs/ecarts-front-backend.md`.
PRIORITE_VERS_FRONT = {
    "URGENT": "URGENTE",
    "ELEVEE": "URGENTE",
    "NORMALE": "NORMALE",
    "BASSE": "NORMALE",
}
PRIORITE_PAR_DEFAUT = "NORMALE"

#: Le code de priorite ecrit quand l'agent coche « Urgent » a l'enregistrement.
CODE_PRIORITE_URGENT = "URGENT"
CODE_PRIORITE_NORMALE = "NORMALE"

#: Les sept etapes du trajet d'un courrier arrive, telles que le Port l'a decrit
#: le 26 aout 2026 et telles que `frontend/src/types/courrier.ts` les enumere.
#: Elles sont **toutes emises** — voir `etape()` et l'ADR 034.
ETAPE_ENREGISTRE = "ENREGISTRE"
ETAPE_COTE = "COTE"
ETAPE_AFFECTE = "AFFECTE"
ETAPE_ACCEPTE = "ACCEPTE"
ETAPE_EN_TRAITEMENT = "EN_TRAITEMENT"
ETAPE_RESTITUE = "RESTITUE"
ETAPE_CLOTURE = "CLOTURE"

#: Combien de lignes une page du registre porte. Le front ne l'impose pas : il
#: lit `taillePage` et calcule le nombre de pages avec.
TAILLE_PAGE = 25

#: Ce que la fiche montre du journal, en plus de la chronologie.
DERNIERS_EVENEMENTS = 3


# =====================================================================
#  Registre
# =====================================================================


def registre(
    utilisateur: Utilisateur,
    *,
    sens: str = "ARRIVEE",
    vue: str = "tous",
    recherche: str = "",
    page: int = 1,
) -> dict:
    """
    Le registre des courriers — A-02.

    `totalRegistre` compte le registre **du sens demande**, tous autres filtres
    leves : c'est le nombre affiche a cote du titre de l'ecran. `total` compte ce
    que le filtre courant retient et sert la pagination. Les confondre ferait dire
    « 12 courriers » a un registre qui en contient huit cents.

    Une vue inconnue ne filtre rien plutot que de vider la liste : un filtre mal
    orthographie qui vide l'ecran se lit comme une panne, et c'est la convention
    du pilier dossiers.
    """
    base, filtree = _requetes_du_registre(utilisateur, sens=sens, vue=vue, recherche=recherche)

    total_registre = base.count()
    total = filtree.count()
    page = max(1, page)
    debut = (page - 1) * TAILLE_PAGE

    lignes = list(
        filtree.select_related("nature", "priorite")[debut : debut + TAILLE_PAGE],
    )

    return {
        "lignes": _resumes(lignes),
        "total": total,
        "totalRegistre": total_registre,
        "page": page,
        "taillePage": TAILLE_PAGE,
    }


def _requetes_du_registre(
    utilisateur: Utilisateur, *, sens: str, vue: str, recherche: str
) -> tuple[models.QuerySet, models.QuerySet]:
    """
    Le registre du sens demande, et ce que le filtre en retient.

    Extraite de `registre()` pour que l'export produise **exactement** la meme
    liste que l'ecran : deux filtrages ecrits deux fois auraient fini par
    diverger sur une vue, et un registre imprime qui ne correspond pas a
    l'ecran d'ou on l'a tire ne se defend pas devant un controle.
    """
    base = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)

    code_sens = SENS_DEPUIS_FRONT.get(sens)
    if code_sens is not None:
        base = base.filter(sens=code_sens)

    filtree = _appliquer_vue(base, vue, utilisateur)
    filtree = _appliquer_recherche(filtree, recherche)
    return base, filtree


#: Combien de lignes un registre imprime porte au plus.
#:
#: Ce n'est pas une regle metier — aucun document n'en fixe : c'est la borne
#: au-dela de laquelle le document cesse d'etre lisible et devient un fichier
#: que personne n'ouvre. Le document **dit** qu'il a ete arrete, et comment
#: reduire la selection : un tableau tronque en silence se lit comme un registre
#: de 500 courriers.
PLAFOND_EXPORT = 500


def registre_pour_export(
    utilisateur: Utilisateur, *, sens: str = "ARRIVEE", vue: str = "tous", recherche: str = ""
) -> dict:
    """
    Le registre en entier — sans pagination, pour l'edition d'un document.

    Rend `tronque` plutot que de lever : un agent qui demande le registre de
    l'annee doit obtenir les 500 premieres lignes et la phrase qui dit qu'il y
    en a d'autres, pas une erreur.
    """
    _, filtree = _requetes_du_registre(utilisateur, sens=sens, vue=vue, recherche=recherche)

    total = filtree.count()
    lignes = list(filtree.select_related("nature", "priorite")[:PLAFOND_EXPORT])

    return {
        "lignes": _resumes(lignes),
        "total": total,
        "tronque": total > PLAFOND_EXPORT,
    }


def _appliquer_vue(requete: models.QuerySet, vue: str, utilisateur: Utilisateur) -> models.QuerySet:
    """
    Les sept onglets du registre. **Ce sont des filtres, pas des etapes.**

    Le front le dit dans son propre commentaire, et la nuance compte : « Non
    cotes » et « Hors delai » peuvent designer le meme courrier, ce qu'une suite
    d'etapes interdirait.

    Chaque onglet est ecrit en termes de ce que la base porte, jamais de l'etape
    deduite : filtrer sur une valeur calculee en Python obligerait a lire le
    registre entier pour en compter une page.
    """
    if vue == "nonCotes":
        return requete.filter(cotations__isnull=True)
    if vue == "affectes":
        return requete.filter(
            cotations__structures__affectations__utilisateur=utilisateur,
            cotations__structures__affectations__retire_le__isnull=True,
        )
    if vue == "aAffecter":
        return _a_affecter(requete, utilisateur)
    if vue == "horsDelai":
        return requete.filter(
            date_limite__lt=date.today(),
            statut_courrier__in=["cree", "en_cours", "traite"],
        )
    if vue == "urgents":
        return requete.filter(priorite__rang__lte=2)
    if vue == "clotures":
        return requete.filter(statut_courrier=STATUT_CLOTURE)
    return requete


def _a_affecter(requete: models.QuerySet, utilisateur: Utilisateur) -> models.QuerySet:
    """
    Ce que ma structure a recu et que personne n'a encore pris en charge.

    **Coter et affecter ne sont pas le meme geste.** La cotation designe une
    *structure* ; l'affectation designe une *personne*. Le client l'a redit le
    28 aout 2026 : « lorsque l'on cote a une structure, c'est au directeur de la
    structure ou son secretariat que l'on cote, puis il affecte a un agent de sa
    structure ». Cet onglet est la file d'attente de ce second geste, qui
    n'existait sur aucun ecran : le courrier cote a la DSR se lisait dans « Tous »
    parmi cinquante autres, et le directeur n'avait aucun endroit ou lire ce qu'il
    lui restait a distribuer.

    Les structures retenues sont celles que la portee rend visibles, et non la
    seule structure de rattachement : un secretariat de direction en portee
    `sous_arbre` doit voir arriver ce qui est cote a sa direction — c'est
    precisement lui qui distribue. En portee `toutes` le perimetre ne borne plus
    rien, et « tout ce qui traine au Port » n'est la file de personne : on retombe
    alors sur le sous-arbre de la structure de rattachement.

    L'absence d'affectation est cherchee **depuis `Affectation`** et jamais par un
    `__isnull=True` porte par la relation : Django en ferait une jointure externe
    ou « aucune affectation » satisfait « aucune affectation retiree », et tout
    courrier serait a affecter des son enregistrement. Meme piege que `_etapes()`,
    voir docs/pieges.md.

    Une affectation faite par une autre direction cotee ne vide pas ma file : le
    filtre porte sur les affectations prises **dans mes structures**. Un courrier
    cote a la DAF et a la DSR, que la DAF a distribue, reste a distribuer a la DSR.
    """
    structures = structures_visibles(utilisateur)
    if structures is None:
        # Portee `toutes`. Voir la docstring : on borne au sous-arbre de
        # rattachement, faute de quoi la file n'aurait pas de proprietaire.
        if utilisateur.structure is None:
            return requete.none()
        structures = utilisateur.structure.descendants()

    deja_affectes = Affectation.objects.filter(
        cotation_structure__cotation__invalide_le__isnull=True,
        cotation_structure__structure__in=structures,
        retire_le__isnull=True,
    ).values("cotation_structure__cotation__courrier_id")

    return (
        requete.filter(
            cotations__invalide_le__isnull=True,
            cotations__structures__structure__in=structures,
        )
        .exclude(statut_courrier=STATUT_CLOTURE)
        .exclude(pk__in=deja_affectes)
        .distinct()
    )


def _appliquer_recherche(requete: models.QuerySet, recherche: str) -> models.QuerySet:
    """
    La recherche du registre — numero, expediteur, objet.

    Elle passe par le vecteur plein texte `courrier.recherche` et son index GIN,
    alimentes par le declencheur du socle avec la configuration `fr_unaccent` :
    « delegation » trouve « délégation ». Le vecteur pondere l'objet en A,
    l'expediteur et le numero en B, les observations en D.

    **Le numero est cherche a part**, par egalite de prefixe : `to_tsvector`
    decoupe `0042/2026` en jetons et une recherche plein texte sur « 0042 » ne le
    retrouve pas de facon fiable. Or c'est la premiere chose qu'un agent tape.
    """
    terme = recherche.strip()
    if not terme:
        return requete

    par_numero = models.Q(numero__istartswith=terme)
    par_texte = models.Q(
        recherche=SearchQuery(terme, config="fr_unaccent", search_type="websearch")
    )
    return requete.filter(par_numero | par_texte)


def _resumes(courriers: list[Courrier]) -> list[dict]:
    """
    Met en forme une page du registre.

    Les cotations et les etats de traitement sont charges **en une requete pour
    toute la page** et non un par courrier : vingt-cinq lignes auraient produit
    cent requetes, et le registre est l'ecran le plus ouvert de l'application.
    """
    identifiants = [courrier.pk for courrier in courriers]
    structures = _structures_cotees(identifiants)
    etapes = _etapes(identifiants, courriers)

    return [
        {
            "id": courrier.pk,
            "numero": courrier.numero,
            "sens": SENS_VERS_FRONT.get(courrier.sens, courrier.sens),
            "objet": courrier.objet,
            "correspondant": courrier.expediteur_libelle,
            "nature": courrier.nature.libelle if courrier.nature else "Non qualifié",
            "dateReception": courrier.date_reception,
            "etape": etapes[courrier.pk],
            "priorite": _priorite(courrier),
            "confidentiel": courrier.confidentiel,
            "echeance": courrier.date_limite,
            "delai": _delai(courrier),
            "structuresCotees": structures.get(courrier.pk, []),
        }
        for courrier in courriers
    ]


def _priorite(courrier: Courrier) -> str:
    """La priorite en vocabulaire du front. Voir `PRIORITE_VERS_FRONT`."""
    if courrier.priorite is None:
        return PRIORITE_PAR_DEFAUT
    return PRIORITE_VERS_FRONT.get(courrier.priorite.code, PRIORITE_PAR_DEFAUT)


def _delai(courrier: Courrier) -> dict | None:
    """
    La consommation du delai, en jours ouvres.

    `None` quand aucun delai n'a ete fixe : le front affiche alors une jauge vide
    plutot qu'un delai a zero, qui se lirait « echu ».

    Le compte s'arrete a la cloture : un courrier clos il y a six mois n'accumule
    pas de retard depuis. Sans cela, le registre des clotures se serait couvert de
    rouge avec le temps.
    """
    if courrier.date_limite is None or courrier.delai_reglementaire_jours is None:
        return None

    fin = courrier.cloture_le.date() if courrier.cloture_le else date.today()
    ecoules = jours_ouvres_entre(courrier.date_reception, fin)
    depassement = jours_ouvres_entre(courrier.date_limite, fin)

    return {
        "joursEcoules": ecoules,
        "joursAlloues": courrier.delai_reglementaire_jours,
        # Jamais negatif : « moins trois jours de depassement » ne veut rien dire,
        # et le front lit `> 0` pour decider du rouge.
        "joursDepassement": max(0, depassement),
    }


def _structures_cotees(identifiants: list[int]) -> dict[int, list[str]]:
    """
    Les sigles des structures cotees, par courrier, **dans l'ordre des rangs**.

    L'ordre n'est pas cosmetique : le front lit `structuresCotees[0]` comme chef
    de file (`chefDeFile()`). Un tri par nom aurait designe le mauvais.

    Toutes les cotations du courrier sont fondues, la plus recente d'abord : en
    cascade, la direction cotee par le DG et le service cote par la direction
    figurent tous deux au registre — c'est le chemin du courrier, pas son dernier
    detenteur.
    """
    if not identifiants:
        return {}

    lignes = (
        Courrier.objects.filter(pk__in=identifiants, cotations__invalide_le__isnull=True)
        .values_list(
            "pk",
            "cotations__niveau_cotation",
            "cotations__structures__rang",
            "cotations__structures__structure__code",
        )
        .order_by("cotations__niveau_cotation", "cotations__structures__rang")
    )

    par_courrier: dict[int, list[str]] = defaultdict(list)
    for identifiant, _niveau, _rang, sigle in lignes:
        if sigle and sigle not in par_courrier[identifiant]:
            par_courrier[identifiant].append(sigle)
    return dict(par_courrier)


# =====================================================================
#  L'etape, deduite
# =====================================================================


def _etapes(identifiants: list[int], courriers: list[Courrier]) -> dict[int, str]:
    """
    L'etape de chaque courrier de la page, en trois requetes d'ensemble.

    Trois et non une par courrier : c'est la meme raison que `_structures_cotees`.
    """
    if not identifiants:
        return {}

    # Meme precaution que pour les affectations ci-dessous : on part de
    # `Cotation`, ou l'existence de la ligne est acquise.
    cotes = set(
        Cotation.objects.filter(courrier_id__in=identifiants, invalide_le__isnull=True).values_list(
            "courrier_id", flat=True
        )
    )
    # Interroge depuis `Affectation` et non depuis `Courrier` : un
    # `__isnull=True` porte par une relation multivaluee fait produire a Django
    # une jointure externe, et « aucune affectation » satisfait alors
    # « aucune affectation retiree ». Tout courrier serait AFFECTE des son
    # enregistrement. Voir docs/pieges.md.
    affectes = set(
        Affectation.objects.filter(
            cotation_structure__cotation__courrier_id__in=identifiants,
            cotation_structure__cotation__invalide_le__isnull=True,
            retire_le__isnull=True,
        ).values_list("cotation_structure__cotation__courrier_id", flat=True)
    )
    # La decharge, meme precaution : on part d'`Affectation`, ou la ligne existe.
    # Un seul agent qui a signe suffit a faire franchir l'etape — le courrier est
    # arrive quelque part, et c'est ce que l'etape dit.
    acceptes = set(
        Affectation.objects.filter(
            cotation_structure__cotation__courrier_id__in=identifiants,
            cotation_structure__cotation__invalide_le__isnull=True,
            retire_le__isnull=True,
            accepte_le__isnull=False,
        ).values_list("cotation_structure__cotation__courrier_id", flat=True)
    )
    traitements = dict(
        Traitement.objects.filter(courrier_id__in=identifiants, invalide_le__isnull=True)
        .values_list("courrier_id", "statut")
        .order_by("courrier_id", "-cree_le")
    )

    return {
        courrier.pk: etape(
            courrier,
            cote=courrier.pk in cotes,
            affecte=courrier.pk in affectes,
            accepte=courrier.pk in acceptes,
            statut_traitement=traitements.get(courrier.pk),
        )
        for courrier in courriers
    }


def etape(
    courrier: Courrier,
    *,
    cote: bool,
    affecte: bool,
    accepte: bool,
    statut_traitement: str | None,
) -> str:
    """
    L'etape du courrier, **deduite de ses faits**.

    L'ordre des tests va du plus decisif au moins : une cloture est une cloture,
    quoi qu'il se soit passe avant.

    **Les sept etapes sont toutes atteignables**, ce qui n'a pas toujours ete le
    cas. Jusqu'au 26 aout 2026 le front en declarait neuf dont quatre que rien ne
    produisait, faute de connaitre le trajet reel d'un courrier au Port. Ce
    trajet a ete decrit ce jour-la, et il tient en sept :

        enregistre -> cote -> affecte -> accepte -> en traitement
                   -> restitue -> cloture

    `TRANSMIS`, `SIGNE` et `PARTI` ont donc ete **retires** plutot que laisses en
    place : ils relevent du pilier depart, pas du courrier arrive. Voir
    l'ADR 034.

    `ACCEPTE` est la **decharge** : l'agent cote a signe le cahier. Elle se
    distingue de `AFFECTE` parce que l'ecart entre les deux est le temps de
    remise du pli, la seule chose que le cahier mesure.

    `RESTITUE` remplace `EN_VALIDATION`. Un traitement soumis n'attend pas une
    validation hierarchique — il attend que le responsable de structure le lise
    et cloture. Le mot precedent decrivait un circuit qui n'existe pas.
    """
    if courrier.statut_courrier == STATUT_CLOTURE:
        return ETAPE_CLOTURE
    if courrier.statut_reponse in (REPONSE_EN_SIGNATURE, REPONSE_SIGNEE):
        return ETAPE_RESTITUE
    if statut_traitement == Traitement.STATUT_SOUMIS:
        return ETAPE_RESTITUE
    if statut_traitement is not None:
        return ETAPE_EN_TRAITEMENT
    if accepte:
        return ETAPE_ACCEPTE
    if affecte:
        return ETAPE_AFFECTE
    if cote:
        return ETAPE_COTE
    return ETAPE_ENREGISTRE


def etape_de(courrier: Courrier) -> str:
    """
    L'etape d'un courrier seul.

    Trois requetes pour une ligne : acceptable sur la fiche, qui charge un
    courrier a la fois. Le registre passe par `_etapes()`, qui interroge une fois
    pour toute la page.
    """
    etapes = _etapes([courrier.pk], [courrier])
    return etapes[courrier.pk]


# =====================================================================
#  Fiche
# =====================================================================


def fiche(utilisateur: Utilisateur, identifiant: int) -> dict:
    """
    La fiche d'un courrier — A-03.

    Un courrier hors perimetre leve `HorsPerimetre`, qui sort en **404** et non
    en 403 : repondre « vous n'avez pas le droit » confirmerait l'existence du
    courrier et celle de son expediteur a qui n'a pas a les connaitre. C'est la
    decision de cadrage D5, et elle vaut d'abord ici — sur un courrier
    confidentiel, cette confirmation est deja la fuite.
    """
    courrier = (
        visibles(Courrier.objects.filter(pk=identifiant, invalide_le__isnull=True), utilisateur)
        .select_related("nature", "priorite", "session", "expediteur")
        .first()
    )
    if courrier is None:
        raise HorsPerimetre("Ce courrier n'existe pas ou ne relève pas de votre périmètre.")

    resume = _resumes([courrier])[0]
    pieces = _pieces(courrier)

    return {
        **resume,
        "sessionLibelle": courrier.session.libelle,
        "referenceExpediteur": courrier.numero_origine,
        "enregistrePar": _nom_agent(courrier.cree_par),
        "nombrePages": courrier.nombre_pieces,
        "nombreAnnexes": len(pieces),
        "delaiJours": courrier.delai_reglementaire_jours or 0,
        "modeCotation": mode_cotation(courrier),
        "cotations": _cotations(courrier, utilisateur),
        "chronologie": _chronologie(courrier, utilisateur),
        "observations": _observations(courrier),
        "monAffectation": mon_affectation(courrier, utilisateur),
        "monTraitement": mon_traitement(courrier, utilisateur),
        "traitements": traitements(courrier, utilisateur),
        "signalements": signalements(utilisateur, courrier),
        "piecesJointes": pieces,
        "reponses": _reponses(courrier),
        "derniersEvenements": _derniers_evenements(courrier, utilisateur),
        "actionsPossibles": actions_possibles(utilisateur, courrier, resume["etape"]),
    }


def mode_cotation(courrier: Courrier) -> str | None:
    """
    `CASCADE` ou `PARALLELE` — **toujours `None` aujourd'hui.**

    Le mode se lit sur la version de circuit figee au courrier
    (`circuit_version.mode_cotation`), et aucun circuit ne se deroule : ses
    etapes n'ont jamais ete communiquees (A24). Il n'y a donc pas d'instance de
    circuit a interroger.

    **Et les deux vocabulaires ne parlent pas de la meme chose.** La base oppose
    `directe` — le DG cote a la structure qui traite — a `cascade`, qui descend
    niveau par niveau : c'est une question de *hauteur*. Le front oppose
    `CASCADE` — une structure apres l'autre — a `PARALLELE`, toutes en meme
    temps : c'est une question de *simultaneite*. Traduire l'un dans l'autre
    reviendrait a inventer une regle. Le `None` est honnete ; le front l'accepte.
    """
    return None


def _filtre_cloisonnement(utilisateur: Utilisateur) -> tuple[str, list]:
    """
    Le fragment de `WHERE` qui ecarte les gestes internes des autres structures.

    Rendu sous forme de couple `(sql, parametres)` plutot que d'une chaine prete
    a coller : les trois requetes qui l'emploient sont ecrites en SQL direct
    — le journal est partitionne et l'ORM ne sait pas s'y joindre proprement —
    et une interpolation de liste d'identifiants dans une chaine SQL est
    exactement la faute qu'on ne veut pas voir passer une seule fois.

    `structure_id IS NULL` est le jalon public, toujours retenu. Voir
    `courrier/cloisonnement.py` pour ce que la frontiere separe.
    """
    lisibles = structures_lisibles(utilisateur)
    if lisibles is None:
        return "", []
    if not lisibles:
        return " AND e.structure_id IS NULL", []
    return " AND (e.structure_id IS NULL OR e.structure_id = ANY(%s))", [sorted(lisibles)]


def _cotations(courrier: Courrier, utilisateur: Utilisateur) -> list[dict]:
    """
    Les cotations du courrier, de la plus recente a la plus ancienne.

    **L'annotation d'une cotation en cascade est cloisonnée.** Une cotation de
    niveau 1 est la decision du Directeur general : elle regarde toutes les
    structures visees, et l'instruction qui l'accompagne fait partie du dossier.
    Une cotation de niveau superieur est la cascade interne d'une direction vers
    ses services — « voyez cela avec le service juridique avant de repondre »
    n'est pas destine a la direction voisine, cotee au meme rang.

    Ce qui reste visible dans les deux cas est **le fait de la cotation** : qui a
    cote qui, et quand. C'est le trajet du courrier, et le bureau d'ordre d'une
    structure en a besoin. Seule l'instruction se retire, remplacee par `None` et
    non par un texte de substitution : « (masqué) » aurait fait croire a un
    secret la ou il n'y a le plus souvent aucune annotation.
    """
    lignes = (
        courrier.cotations.filter(invalide_le__isnull=True)
        .select_related("mention_type", "decide_par", "saisi_par")
        .prefetch_related("structures__structure")
        .order_by("niveau_cotation", "-decide_le")
    )

    return [
        {
            "id": cotation.pk,
            "mention": cotation.mention_type.libelle if cotation.mention_type else None,
            "annotation": (
                cotation.annotation
                if cotation.niveau_cotation <= 1
                or lit_le_dossier_de(utilisateur, cotation.decide_par.structure_id)
                else None
            ),
            "delaiFixe": cotation.delai_fixe,
            "decidePar": _agent(cotation.decide_par),
            "decideLe": cotation.decide_le,
            "saisiPar": _agent(cotation.saisi_par),
            "saisiLe": cotation.saisi_le,
            "structures": [
                {
                    "structureId": visee.structure_id,
                    "libelle": visee.structure.libelle,
                    "rang": visee.rang,
                    "chefDeFile": visee.chef_de_file,
                }
                for visee in cotation.structures.all()
            ],
        }
        for cotation in lignes
    ]


def _chronologie(courrier: Courrier, utilisateur: Utilisateur) -> list[dict]:
    """
    La chronologie de la fiche, construite **depuis le journal**.

    Cloisonnee : une structure cotee y lit les jalons du courrier et ses propres
    gestes, jamais ceux de sa voisine. La DSR et le Directeur general la lisent
    entiere — c'est la mission de suivi que l'exigence leur reconnait.

    Le journal est l'histoire du courrier (ADR 012) : une seconde table d'etapes
    aurait produit deux recits du meme courrier, et c'est toujours le moins
    complet qu'on finit par lire.

    La derniere etape est marquee `courante`, les precedentes `faite`. **Aucune
    n'est `attendue`** : les etapes a venir se lisent dans `circuit_etape`, qui est
    vide (A24). Le front sait afficher une chronologie sans suite ; il ne saurait
    pas distinguer une suite inventee d'une suite reelle.
    """
    cloison, arguments = _filtre_cloisonnement(utilisateur)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT e.id, e.libelle, e.detail, e.survenu_le,
                   e.donnees ->> 'instruction',
                   u.prenom, u.nom, s.code
              FROM evenement e
              LEFT JOIN utilisateur u ON u.id = e.acteur_id
              LEFT JOIN structure   s ON s.id = u.structure_id
             WHERE e.objet_type = 'courrier' AND e.objet_id = %s
            """
            + cloison
            + """
             ORDER BY e.survenu_le, e.id
            """,
            [courrier.pk, *arguments],
        )
        lignes = curseur.fetchall()

    etapes = []
    for index, (
        identifiant,
        libelle,
        detail,
        horodatage,
        instruction,
        prenom,
        nom,
        sigle,
    ) in enumerate(lignes):
        auteur = f"{prenom} {nom}" + (f" — {sigle}" if sigle else "") if prenom else None
        etapes.append(
            {
                "id": identifiant,
                "libelle": libelle,
                "horodatage": horodatage,
                "auteur": auteur,
                "precision": detail,
                # L'instruction portee a l'etape, quand le service l'a inscrite.
                # Citee telle quelle : une consigne reformulee n'engage plus son
                # auteur. Extraite **en SQL** (`->>`) et non en Python : Django
                # laisse psycopg rendre un JSONB brut sous forme de chaine, la
                # desserialisation etant le travail de `JSONField`. Un `.get()`
                # sur ce resultat leve `AttributeError` — voir docs/pieges.md.
                "instruction": instruction,
                "etat": "courante" if index == len(lignes) - 1 else "faite",
            }
        )
    return etapes


def _observations(courrier: Courrier) -> list[dict]:
    """
    Le fil d'observations de la fiche.

    **Le fil n'est pas cloisonne**, a la difference du journal : tout lecteur du
    courrier le lit en entier, quelle que soit la structure de l'auteur. C'est
    l'arbitrage du Port du 26 aout 2026, et l'ADR 034 dit pourquoi — un fil
    cloisonne aurait produit cinq fils paralleles au lieu d'une conversation.

    A ne pas confondre avec `courrier.observations`, qui reste la zone de saisie
    du formulaire d'enregistrement : un texte unique, sans auteur ni date. Elle
    n'est pas rendue ici, car la rendre lui attribuerait l'agent et l'heure du
    dernier enregistrement, ce qui est faux.
    """
    lignes = (
        Observation.objects.filter(courrier=courrier)
        .select_related("auteur", "auteur__poste", "auteur__structure")
        .order_by("publie_le", "id")
    )

    return [
        {
            "id": observation.pk,
            "auteur": f"{observation.auteur.prenom} {observation.auteur.nom}".strip(),
            "initiales": _initiales(observation.auteur),
            # La fonction **d'aujourd'hui**, et non celle du jour de l'ecriture :
            # le socle ne garde pas l'historique des postes, et afficher un poste
            # perime serait pire que d'afficher le poste courant. Le nom, lui,
            # ne bouge pas.
            "fonction": _fonction(observation.auteur),
            "horodatage": observation.publie_le,
            "texte": observation.texte,
        }
        for observation in lignes
    ]


def _initiales(agent: Utilisateur) -> str:
    """Les deux lettres de l'avatar. Le front n'en calcule aucune lui-meme."""
    return f"{(agent.prenom or ' ')[0]}{(agent.nom or ' ')[0]}".strip().upper() or "?"


def _fonction(agent: Utilisateur) -> str:
    """
    Ce qui s'affiche a cote du nom : l'intitule du poste, sinon la structure.

    Ni l'un ni l'autre n'est garanti — un compte peut n'avoir aucun poste actif.
    « — » plutot que la chaine vide, pour la meme raison que `_nom_agent()`.
    """
    poste = getattr(agent, "poste", None)
    if poste is not None and poste.libelle:
        return poste.libelle
    structure = agent.structure
    if structure is not None and structure.libelle:
        return structure.libelle
    return "—"


def _pieces(courrier: Courrier) -> list[dict]:
    """
    Les pieces rattachees au courrier.

    Lues par le rattachement **generique** (`objet_type` / `objet_id`), qui est
    celui que `POST /pieces` ecrit depuis l'ADR 017. `courrier_id` existe encore
    et sert les index du socle ; s'en servir ici aurait manque les pieces deposees
    par la route generique.
    """
    lignes = PieceJointe.objects.filter(
        objet_type="courrier", objet_id=courrier.pk, invalide_le__isnull=True
    ).order_by("cree_le")

    return [
        {
            "id": piece.pk,
            "nom": piece.nom_original,
            "format": (piece.extension or "").lstrip(".").upper() or "—",
            "taille": _taille(piece.taille_octets),
            "precision": piece.categorie.capitalize() if piece.categorie else None,
        }
        for piece in lignes
    ]


def _taille(octets: int) -> str:
    """
    « 1,2 Mo » — mise en forme au serveur.

    Le separateur decimal francais est une regle de presentation, et la porter au
    serveur evite que deux ecrans affichent « 1.2 MB » et « 1,2 Mo » pour le meme
    fichier.
    """
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")


def _reponses(courrier: Courrier) -> list[dict]:
    """
    Les courriers rattaches a celui-ci — les reponses qu'il a suscitees.

    Le lien est `courrier_lie_id`, pose par le courrier de depart vers le courrier
    d'arrivee auquel il repond. Le sens du lien compte : c'est la reponse qui
    designe la demande, jamais l'inverse — au moment ou la demande arrive, la
    reponse n'existe pas.
    """
    lignes = Courrier.objects.filter(courrier_lie=courrier, invalide_le__isnull=True).order_by(
        "date_reception"
    )

    return [
        {
            "id": reponse.pk,
            "numero": reponse.numero,
            "objet": reponse.objet,
            # `version` vaut 1 tant que la redaction versionnee du pilier depart
            # n'existe pas : `traitement.version` porte les versions d'un projet
            # de reponse, pas celles d'un courrier enregistre.
            "version": 1,
            "redigePar": _nom_agent(reponse.cree_par),
            "etape": etape_de(reponse),
        }
        for reponse in lignes
    ]


def _derniers_evenements(courrier: Courrier, utilisateur: Utilisateur) -> list[dict]:
    """
    Les trois derniers faits du journal. Le journal complet est dans la tracabilite.

    Cloisonne comme la chronologie, et pour une raison qui n'a rien de
    theorique : c'est le bloc le plus visible de la fiche, et sans le filtre il
    aurait affiche en tete « Affecté à Untel — DAF » a une structure qui n'a pas
    a savoir qui la DAF met sur ses dossiers.
    """
    cloison, arguments = _filtre_cloisonnement(utilisateur)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT e.id, e.libelle, e.survenu_le
              FROM evenement e
             WHERE e.objet_type = 'courrier' AND e.objet_id = %s
            """
            + cloison
            + """
             ORDER BY e.survenu_le DESC, e.id DESC
             LIMIT %s
            """,
            [courrier.pk, *arguments, DERNIERS_EVENEMENTS],
        )
        return [
            {"id": identifiant, "libelle": libelle, "horodatage": horodatage}
            for identifiant, libelle, horodatage in curseur.fetchall()
        ]


# =====================================================================
#  Ce que l'agent peut faire sur ce courrier
# =====================================================================

#: Les actions que le front connait, et la permission qui les ouvre. Miroir de
#: `frontend/src/features/courrier/actionsDisponibles.ts` : le front croise sa
#: propre table avec celle-ci et n'affiche que l'intersection. **Le serveur reste
#: seul juge** — le front n'est qu'un filtre d'affichage.
PERMISSION_PAR_ACTION = {
    "coter": (PERM.COT, PERM.COT_DEL),
    "affecter": (PERM.AFF,),
    # Signer la decharge et signaler un ecart s'ouvrent sous `LEC` : ce sont des
    # gestes de l'agent qui recoit le pli, pas de celui qui le traite. Exiger
    # `TRA` pour accuser reception aurait empeche d'accuser un courrier mal
    # dirige — c'est-a-dire exactement le cas ou le cahier sert.
    "accepter": (PERM.LEC,),
    "signaler": (PERM.LEC,),
    "traiter": (PERM.TRA,),
    "restituer": (PERM.TRA,),
    # Retourner et cloturer sont **le meme role** : celui du responsable de
    # structure a qui l'agent rend le courrier. `VAL` et `TRANS` ne figurent
    # plus ici — il n'y a ni visa ni transmission sur le courrier arrive
    # (ADR 034), et une action declaree sans route se lit comme une promesse.
    "retourner": (PERM.CLO,),
    "cloturer": (PERM.CLO,),
    "relancer": (PERM.REL,),
    "imprimer": (PERM.IMP,),
}

#: A quelles etapes chaque action a un sens. Meme table que le front, sur les
#: sept etapes que le serveur rend reellement.
#:
#: `traiter` demande la **decharge** : un courrier affecte mais non accepte ne se
#: traite pas (ADR 035). C'est la seule action dont l'etape d'entree a change le
#: 26 aout 2026.
ETAPES_PAR_ACTION = {
    "coter": (ETAPE_ENREGISTRE, ETAPE_COTE),
    "affecter": (ETAPE_COTE,),
    "accepter": (ETAPE_AFFECTE,),
    "traiter": (ETAPE_ACCEPTE, ETAPE_EN_TRAITEMENT),
    "restituer": (ETAPE_EN_TRAITEMENT,),
    "retourner": (ETAPE_RESTITUE,),
    # La cloture n'attend pas un traitement : beaucoup de courriers arrivent
    # pour information et se referment sans que personne n'ecrive. Elle
    # s'ouvre des que le courrier est cote — avant, c'est au bureau d'ordre
    # central de le classer, et il le fait par la meme route.
    "cloturer": (ETAPE_COTE, ETAPE_AFFECTE, ETAPE_ACCEPTE, ETAPE_EN_TRAITEMENT, ETAPE_RESTITUE),
    "relancer": (ETAPE_AFFECTE, ETAPE_ACCEPTE, ETAPE_EN_TRAITEMENT, ETAPE_RESTITUE),
    "signaler": (
        ETAPE_ENREGISTRE,
        ETAPE_COTE,
        ETAPE_AFFECTE,
        ETAPE_ACCEPTE,
        ETAPE_EN_TRAITEMENT,
        ETAPE_RESTITUE,
    ),
    "imprimer": (
        ETAPE_ENREGISTRE,
        ETAPE_COTE,
        ETAPE_AFFECTE,
        ETAPE_ACCEPTE,
        ETAPE_EN_TRAITEMENT,
        ETAPE_RESTITUE,
        ETAPE_CLOTURE,
    ),
}


def actions_possibles(
    utilisateur: Utilisateur, courrier: Courrier, etape_courante: str
) -> list[str]:
    """
    Ce que **cet** agent peut faire sur **ce** courrier.

    Deux conditions, toutes deux necessaires : porter la permission, et se trouver
    a une etape ou l'action a un sens. Le front applique la meme regle pour
    n'afficher que des boutons pressables ; le serveur la reapplique a l'ecriture,
    parce qu'une liste d'actions rendue en lecture n'est pas une autorisation.

    **Un courrier clos ne se rouvre pas.** Seule l'impression reste, et c'est
    voulu : le registre d'une annee close doit encore s'imprimer.
    """
    if etape_courante == ETAPE_CLOTURE:
        return ["imprimer"] if possede(utilisateur, PERM.IMP) else []

    return [
        action
        for action, permissions in PERMISSION_PAR_ACTION.items()
        if etape_courante in ETAPES_PAR_ACTION[action] and possede(utilisateur, *permissions)
    ]


# =====================================================================
#  Fiche de vie — A-06
# =====================================================================

#: Les types d'evenement qui **engagent l'institution**. Le filtre « Jalons » de
#: l'ecran ne retient que ceux-la. La liste est explicite et non deduite d'un
#: prefixe : « ce qui engage » est une question metier, pas une convention de
#: nommage, et un jour un evenement nomme `courrier.quelque_chose` ne l'engagera
#: pas.
TYPES_JALON = {
    "courrier.enregistre",
    "courrier.cote",
    "courrier.cloture",
    "courrier.transmis",
    "courrier.signe",
}

#: Les types d'evenement qui signalent un incident. `conforme = false` les colore
#: en rouge sur la fiche de vie.
TYPES_INCIDENT = {
    "courrier.ecart",
    "courrier.retard",
    "courrier.relance",
    "courrier.suspendu",
    "courrier.retourne",
}


def fiche_de_vie(utilisateur: Utilisateur, identifiant: int) -> dict:
    """
    La fiche de vie d'un courrier — A-06. **Le journal, redige pour etre lu.**

    Elle ne rend rien que le journal ne porte deja : c'est le meme recit que la
    chronologie de la fiche, avec ce que l'impression exige — le temps ecoule
    entre deux etapes, et qui detenait le courrier pendant ce temps.

    `marge` est la piece maitresse : c'est elle qui **revele ou le courrier a
    attendu**. Une liste d'horodatages laisse ce calcul a l'oeil du lecteur, et
    trois jours de silence entre deux lignes ne se remarquent pas.

    **Elle est cloisonnee**, comme la chronologie de la fiche : une structure y
    lit les jalons du courrier — enregistre, cote, entre chez elle, sorti,
    cloture — et ses propres gestes, jamais l'interieur du dossier de sa
    voisine. La DSR la lit entiere.

    Consequence a connaitre : deux structures cotees sur le meme courrier
    n'obtiennent pas la meme fiche de vie, et les `marge` different — celui qui
    voit moins d'etapes voit des marges plus longues. C'est exact dans les deux
    cas : chacun mesure le temps entre les faits qui le concernent. Une fiche
    imprimee porte donc le nom de qui l'a tiree.
    """
    courrier = (
        visibles(Courrier.objects.filter(pk=identifiant, invalide_le__isnull=True), utilisateur)
        .select_related("nature", "priorite")
        .first()
    )
    if courrier is None:
        raise HorsPerimetre("Ce courrier n'existe pas ou ne relève pas de votre périmètre.")

    cloison, arguments = _filtre_cloisonnement(utilisateur)
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT e.id, e.type_evenement, e.libelle, e.detail, e.survenu_le,
                   u.prenom, u.nom, s.code
              FROM evenement e
              LEFT JOIN utilisateur u ON u.id = e.acteur_id
              LEFT JOIN structure   s ON s.id = u.structure_id
             WHERE e.objet_type = 'courrier' AND e.objet_id = %s
            """
            + cloison
            + """
             ORDER BY e.survenu_le, e.id
            """,
            [courrier.pk, *arguments],
        )
        lignes = curseur.fetchall()

    etapes = []
    precedent = None
    for identifiant_ev, type_ev, libelle, detail, survenu_le, prenom, nom, sigle in lignes:
        etapes.append(
            {
                "id": identifiant_ev,
                "heure": timezone.localtime(survenu_le).strftime("%H:%M"),
                "date": timezone.localtime(survenu_le).strftime("%d/%m/%Y"),
                "titre": libelle,
                "detail": detail or "",
                "acteur": (f"{prenom} {nom}" + (f" — {sigle}" if sigle else "")) if prenom else "—",
                "marge": _marge(precedent, survenu_le),
                "conforme": type_ev not in TYPES_INCIDENT,
                "jalon": type_ev in TYPES_JALON,
            }
        )
        precedent = survenu_le

    return {
        "numero": courrier.numero,
        "objet": courrier.objet,
        "etapes": etapes,
        "resume": _resume_de_vie(courrier),
        "detenteurs": _detenteurs(courrier, utilisateur),
        "lies": _lies(courrier),
    }


def _marge(precedent: datetime | None, courant: datetime) -> str:
    """
    Le temps ecoule depuis l'etape precedente, en clair.

    « — » pour la premiere etape, et non « 0 min » : zero se lirait « traite
    instantanement », alors qu'il n'y a rien avant a quoi se comparer.

    En heures et en jours calendaires, pas en jours ouvres : la fiche de vie
    raconte le temps reel — un courrier arrive un vendredi soir a bien attendu
    tout le week-end, meme si le delai reglementaire, lui, ne court pas.
    """
    if precedent is None:
        return "—"

    minutes = int((courant - precedent).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 60 * 24:
        return f"{minutes // 60} h"
    jours = minutes // (60 * 24)
    return f"{jours} j" if jours > 1 else "1 j"


def _resume_de_vie(courrier: Courrier) -> list[dict]:
    """
    Les trois chiffres de l'entete de la fiche de vie.

    Le ton n'est pas decoratif : c'est lui qui dit, sans lire les dates, si le
    courrier est tenu ou en retard.
    """
    delai = _delai(courrier)
    if delai is None:
        duree = {"libelle": "Délai", "valeur": "Non fixé", "ton": "neutre"}
    elif delai["joursDepassement"] > 0:
        duree = {
            "libelle": "Dépassement",
            "valeur": f"{delai['joursDepassement']} j ouvrés",
            "ton": "alerte",
        }
    else:
        restant = delai["joursAlloues"] - delai["joursEcoules"]
        duree = {
            "libelle": "Délai restant",
            "valeur": f"{max(0, restant)} j ouvrés",
            "ton": "succes" if restant > 1 else "alerte",
        }

    etape_courante = etape_de(courrier)
    return [
        {"libelle": "Étape", "valeur": etape_courante, "ton": "neutre"},
        duree,
        {
            "libelle": "Clôturé le",
            "valeur": (
                timezone.localtime(courrier.cloture_le).strftime("%d/%m/%Y")
                if courrier.cloture_le
                else "Non clôturé"
            ),
            "ton": "succes" if courrier.cloture_le else "neutre",
        },
    ]


def _detenteurs(courrier: Courrier, utilisateur: Utilisateur) -> list[dict]:
    """
    Qui a tenu le courrier, et combien de temps.

    Les detenteurs sont les **agents affectes** : la cotation designe une
    structure, et une structure ne detient pas un dossier — elle le confie a
    quelqu'un. Lister les structures cotees ici aurait fait dire « la DAF a
    detenu le courrier onze jours », ce qui ne permet ni de relancer ni de
    comprendre.

    La duree court jusqu'au retrait de l'affectation, ou jusqu'a maintenant pour
    une affectation ouverte : c'est le temps de detention **en cours**, celui qui
    justifie une relance.

    **Cloisonne, mais autrement que le journal.** Une structure voisine garde la
    ligne — le courrier a bien passe onze jours a la DAF, et le taire aurait
    fausse la lecture du trajet — et perd le **nom** de l'agent, remplace par la
    structure. Qui la DAF met sur ses dossiers est son affaire ; combien de
    temps le courrier y est reste ne l'est pas.
    """
    lignes = (
        Affectation.objects.filter(cotation_structure__cotation__courrier=courrier)
        .select_related("utilisateur", "cotation_structure__structure")
        .order_by("affecte_le")
    )

    maintenant = timezone.now()
    detenteurs = []
    for affectation in lignes:
        fin = affectation.retire_le or maintenant
        agent = affectation.utilisateur
        structure = affectation.cotation_structure.structure
        nomme = lit_le_dossier_de(utilisateur, structure.pk)
        detenteurs.append(
            {
                "nom": f"{agent.prenom} {agent.nom}" if nomme else structure.libelle,
                "structure": structure.code,
                "initiales": (
                    f"{agent.prenom[:1]}{agent.nom[:1]}".upper() if nomme else structure.code[:2]
                ),
                "duree": _marge(affectation.affecte_le, fin),
            }
        )
    return detenteurs


def _lies(courrier: Courrier) -> list[dict]:
    """
    Les courriers rattaches, dans les **deux** sens.

    Le courrier auquel celui-ci repond et les reponses qu'il a suscitees : la
    fiche de vie d'une reponse doit citer la demande, et celle d'une demande doit
    citer ses reponses. Un seul sens aurait laisse la moitie des fiches sans
    contexte.
    """
    lies = []
    if courrier.courrier_lie_id:
        amont = Courrier.objects.filter(pk=courrier.courrier_lie_id).only("numero", "objet").first()
        if amont:
            lies.append(
                {
                    "reference": amont.numero,
                    "titre": amont.objet,
                    "chemin": f"/courriers/{amont.pk}",
                }
            )

    for aval in Courrier.objects.filter(courrier_lie=courrier, invalide_le__isnull=True).only(
        "numero", "objet"
    ):
        lies.append(
            {"reference": aval.numero, "titre": aval.objet, "chemin": f"/courriers/{aval.pk}"}
        )
    return lies


# =====================================================================
#  Indicateurs du registre
# =====================================================================


def indicateurs(utilisateur: Utilisateur, sens: str = "ARRIVEE") -> dict:
    """
    Les quatre indicateurs du bandeau du registre — A-02.

    Tous bornes au perimetre de l'agent : un compteur calcule hors perimetre est
    une fuite discrete — le nombre dit quelque chose meme quand la liste est
    fermee.

    **`variation` et `serie` sortent vides, nommes.** La variation suppose une
    periode de reference — « +12 % par rapport a quoi ? » — et la serie suppose un
    historique de comptes journaliers que rien n'archive. Les deux se calculeront
    quand le registre aura une profondeur ; les inventer aujourd'hui aurait mis
    une courbe montante sous un chiffre de trois. ADR 011.
    """
    base = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)
    code_sens = SENS_DEPUIS_FRONT.get(sens)
    if code_sens is not None:
        base = base.filter(sens=code_sens)

    aujourd_hui = date.today()

    arrives = base.filter(date_reception=aujourd_hui).count()
    a_coter = base.filter(cotations__isnull=True).count()
    hors_delai = base.filter(
        date_limite__lt=aujourd_hui, statut_courrier__in=["cree", "en_cours", "traite"]
    ).count()

    return {
        "arrivesAujourdHui": _mesure(arrives),
        "enAttenteCotation": _mesure(a_coter),
        "delaiMoyenCotation": _delai_moyen_cotation(base),
        "horsDelai": _mesure(hors_delai),
    }


def _mesure(valeur: int | str) -> dict:
    """Un indicateur sans variation ni serie. Voir la docstring d'`indicateurs`."""
    return {"valeur": valeur, "variation": "Non mesuré", "serie": []}


def _delai_moyen_cotation(base: models.QuerySet) -> dict:
    """
    Le temps moyen entre l'arrivee d'un courrier et sa cotation.

    Mesure sur les courriers **effectivement cotes** : inclure les non cotes
    aurait fait baisser la moyenne a chaque courrier en attente, soit l'inverse de
    ce que l'indicateur doit dire.

    « Non mesuré » quand aucun courrier n'est cote. Ce n'est pas « 0 h » : zero se
    lirait « cotation instantanee », qui est la meilleure valeur possible la ou il
    n'y a aucune valeur.
    """
    lignes = base.filter(cotations__invalide_le__isnull=True).values_list(
        "date_reception", "cotations__decide_le"
    )

    ecarts = [
        (decide_le.date() - reception).days
        for reception, decide_le in lignes
        if decide_le is not None and reception is not None
    ]
    if not ecarts:
        return {"valeur": "Non mesuré", "variation": "Non mesuré", "serie": []}

    moyenne = sum(ecarts) / len(ecarts)
    if moyenne < 1:
        return {"valeur": "moins d'un jour", "variation": "Non mesuré", "serie": []}
    return {"valeur": f"{moyenne:.1f} j".replace(".", ","), "variation": "Non mesuré", "serie": []}


# =====================================================================
#  Compteurs de la navigation
# =====================================================================


def compteurs(utilisateur: Utilisateur) -> dict:
    """
    Les trois pastilles de la barre laterale.

    Elles portent sur ce que l'agent voit, jamais sur le registre entier.

    `relances` compte les courriers **dont l'echeance est passee et qui ne sont
    pas clos** — ce qui reste a relancer, et non les relances deja emises. La
    nuance est celle du menu : « Relances » y designe un travail a faire.

    **Trois zeros pour qui ne porte pas `LEC`.** La route est ouverte a toute
    session — la barre laterale se monte pour tout compte connecte — et la garde
    est donc portee ici. Un compte sans droit de lecture qui recevrait des nombres
    justes apprendrait quelque chose du registre sans pouvoir l'ouvrir : un
    compteur est une fuite discrete.
    """
    if not possede(utilisateur, PERM.LEC):
        return {"courriers": 0, "cotations": 0, "relances": 0}

    base = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)
    aujourd_hui = date.today()

    return {
        "courriers": base.exclude(statut_courrier=STATUT_CLOTURE).count(),
        "cotations": base.filter(cotations__isnull=True).count(),
        "relances": base.filter(
            date_limite__lt=aujourd_hui, statut_courrier__in=["cree", "en_cours", "traite"]
        ).count(),
    }


# =====================================================================
#  Contexte d'enregistrement
# =====================================================================


def contexte_enregistrement(utilisateur: Utilisateur) -> dict:
    """
    Ce que l'ecran A-01 affiche avant toute saisie.

    Le numero est **predit**, jamais reserve : il est lu dans
    `sequence_numerotation` sans l'incrementer, et le declencheur `courrier_numero`
    seul le compose a l'insertion. Reserver un numero a l'ouverture d'un
    formulaire aurait troue la sequence des le premier abandon de saisie — et un
    registre a trous est un registre qu'on ne peut plus certifier.
    """
    from courrier.modeles import SequenceNumerotation

    session = session_en_cours(utilisateur)
    if session is None:
        raise HorsPerimetre(
            "Votre compte n'est rattaché à aucun registre : l'enregistrement d'un "
            "courrier n'aurait pas de numéro."
        )

    annee = date.today().year
    sequence = SequenceNumerotation.objects.filter(session=session, annee=annee).first()
    prochain = (sequence.dernier_numero if sequence else 0) + 1

    return {
        "numeroPrevu": f"{prochain:04d}/{annee}",
        "dateArrivee": timezone.now(),
        "sessionLibelle": session.libelle,
    }


# =====================================================================
#  Utilitaires
# =====================================================================


def _agent(utilisateur: Utilisateur) -> dict:
    return {"id": utilisateur.pk, "nomComplet": f"{utilisateur.prenom} {utilisateur.nom}"}


def _nom_agent(identifiant: int | None) -> str:
    """
    Le nom d'un agent designe par une colonne `*_par` sans cle etrangere.

    `courrier.cree_par` est un `BIGINT` nu au socle, sans contrainte : le compte
    peut avoir ete supprime. « Compte supprimé » plutot qu'une chaine vide — une
    case vide se lit comme un defaut d'affichage, pas comme un fait.
    """
    if identifiant is None:
        return "—"
    agent = Utilisateur.objects.filter(pk=identifiant).only("prenom", "nom").first()
    return f"{agent.prenom} {agent.nom}" if agent else "Compte supprimé"


def _nom_du_signataire(agent: Utilisateur | None) -> str:
    """Le nom porte par une cle etrangere facultative : `affectation.accepte_par`."""
    if agent is None:
        return "—"
    return f"{agent.prenom} {agent.nom}".strip() or "—"


# =====================================================================
#  Le cahier de decharge — A-11
# =====================================================================

#: Au-dela de ce delai, une decharge manquante cesse d'etre une attente. La
#: valeur s'administre : `courrier.decharge_delai_alerte_jours`, **hypothese**
#: (A73) — le Port a decrit le cahier, jamais le moment ou son absence devient
#: anormale.
CLE_DELAI_DECHARGE = "courrier.decharge_delai_alerte_jours"

ETAT_DECHARGE_SIGNEE = "Signé"
ETAT_DECHARGE_ATTENTE = "En attente"
ETAT_DECHARGE_PERDUE = "Non retourné"


def decharges(utilisateur: Utilisateur, vue: str = "tous") -> list[dict]:
    """
    Le cahier de decharge — A-11.

    Une ligne par **affectation ouverte**, et non par courrier : le cahier suit
    des plis remis a des personnes, et un courrier cote a deux structures produit
    deux remises distinctes.

    **Ce que l'agent voit.** Ses propres remises, plus celles de sa structure —
    c'est elle qui tient le cahier. Le tout intersecte avec les courriers qu'il a
    le droit de lire : le cahier n'ouvre aucune porte que `visibles()` fermerait.

    Trois vues, qui sont les trois questions qu'on pose a un cahier : tout,
    ce qui n'est pas signe, et ce qui ne l'est pas depuis trop longtemps.
    """
    lisibles = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)

    lignes = (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier__in=lisibles,
            cotation_structure__cotation__invalide_le__isnull=True,
            retire_le__isnull=True,
        )
        .filter(
            models.Q(utilisateur=utilisateur)
            | models.Q(cotation_structure__structure_id=utilisateur.structure_id)
        )
        .select_related(
            "utilisateur",
            "accepte_par",
            "cotation_structure__structure",
            "cotation_structure__cotation__courrier",
        )
        .order_by("-affecte_le", "-id")
    )

    seuil = parametres.valeur(CLE_DELAI_DECHARGE, 3)
    aujourd_hui = date.today()

    rendues = [_ligne_decharge(affectation, seuil, aujourd_hui) for affectation in lignes]

    if vue == "attente":
        return [ligne for ligne in rendues if ligne["etat"] != ETAT_DECHARGE_SIGNEE]
    if vue == "nonRetourne":
        return [ligne for ligne in rendues if ligne["etat"] == ETAT_DECHARGE_PERDUE]
    return rendues


def _ligne_decharge(affectation: Affectation, seuil: int, aujourd_hui: date) -> dict:
    """
    Une ligne du cahier.

    L'etat se **deduit**, il ne se stocke pas : une colonne `etat` aurait cesse
    d'etre vraie le lendemain, faute d'un traitement nocturne pour la reecrire.
    """
    courrier = affectation.cotation_structure.cotation.courrier
    agent = affectation.utilisateur

    if affectation.accepte_le is not None:
        etat = ETAT_DECHARGE_SIGNEE
    elif jours_ouvres_entre(affectation.affecte_le.date(), aujourd_hui) > seuil:
        etat = ETAT_DECHARGE_PERDUE
    else:
        etat = ETAT_DECHARGE_ATTENTE

    return {
        "id": affectation.pk,
        "courrierId": courrier.pk,
        "reference": courrier.numero,
        "objet": courrier.objet,
        "destinataire": f"{agent.prenom} {agent.nom}".strip(),
        "structure": affectation.cotation_structure.structure.code,
        "remise": affectation.affecte_le.date().isoformat(),
        # Le coursier, quand la structure le note. « — » plutot que vide : une
        # case vide se lit comme un defaut d'affichage, pas comme un fait.
        "coursier": affectation.remis_par or "—",
        "recepteur": _nom_du_signataire(affectation.accepte_par),
        "decharge": (
            affectation.accepte_le.date().isoformat()
            if affectation.accepte_le
            else (affectation.reference_cahier or "—")
        ),
        "etat": etat,
    }


def mon_affectation(courrier: Courrier, utilisateur: Utilisateur) -> dict | None:
    """
    L'affectation de **cet** agent sur ce courrier, s'il en a une.

    C'est ce qui permet a la fiche d'afficher le bouton « J'ai reçu ce courrier »
    a la bonne personne, et a elle seule. `None` pour tous les autres : un
    courrier qu'on lit sans l'avoir recu ne se decharge pas.

    Le point focal, lui, signe pour un absent depuis le cahier (A-11) : la fiche
    n'a pas a porter ce cas, qui n'est pas celui de son lecteur.
    """
    affectation = (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier=courrier,
            cotation_structure__cotation__invalide_le__isnull=True,
            utilisateur=utilisateur,
            retire_le__isnull=True,
        )
        .select_related("accepte_par")
        .order_by("-affecte_le")
        .first()
    )
    if affectation is None:
        return None

    return {
        "id": affectation.pk,
        "affecteLe": affectation.affecte_le.isoformat(),
        "consigne": affectation.orientations,
        "accepteLe": (affectation.accepte_le.isoformat() if affectation.accepte_le else None),
    }


# =====================================================================
#  Les ecarts signales — A-12
# =====================================================================


def signalements(utilisateur: Utilisateur, courrier: Courrier | None = None) -> list[dict]:
    """
    Les ecarts qu'un agent a le droit de suivre.

    **Deux titres a voir un signalement** : l'avoir emis, ou appartenir a la
    structure visee. Les autres n'ont pas a savoir qu'une direction s'est plainte
    d'une autre — un registre d'ecarts lisible de tous devient un registre ou
    plus personne ne signale.

    La restriction aux courriers visibles s'ajoute par-dessus : un ecart ne doit
    pas reveler l'existence d'un courrier confidentiel a qui ne le voit pas.
    """
    lisibles = visibles(Courrier.objects.filter(invalide_le__isnull=True), utilisateur)

    lignes = SignalementEcart.objects.filter(courrier__in=lisibles).filter(
        models.Q(emis_par=utilisateur)
        | models.Q(destinataire_structure_id=utilisateur.structure_id)
    )
    if courrier is not None:
        lignes = lignes.filter(courrier=courrier)

    lignes = lignes.select_related(
        "courrier", "destinataire_structure", "emis_par", "emetteur_structure"
    ).order_by("-emis_le", "-id")

    libelles = dict(SignalementEcart.TYPES)
    etats = dict(SignalementEcart.ETATS)

    return [
        {
            "id": signalement.pk,
            "courrierId": signalement.courrier_id,
            "reference": signalement.courrier.numero,
            "type": libelles.get(signalement.type_ecart, signalement.type_ecart),
            "typeCode": signalement.type_ecart,
            "gravite": signalement.gravite,
            "detail": signalement.description,
            "destinataire": signalement.destinataire_structure.code,
            "emisPar": f"{signalement.emis_par.prenom} {signalement.emis_par.nom}".strip(),
            "emisLe": signalement.emis_le.isoformat(),
            "etat": etats.get(signalement.etat, signalement.etat),
            "etatCode": signalement.etat,
            "suiteDonnee": signalement.suite_donnee,
            # Ce que **ce** lecteur peut faire : seule la structure visee fait
            # avancer l'ecart. Le calculer ici evite au front de reimplementer la
            # regle, et au serveur de la voir contournee.
            "peutAvancer": (
                utilisateur.structure_id == signalement.destinataire_structure_id
                and signalement.etat != SignalementEcart.ETAT_CLOS
            ),
        }
        for signalement in lignes
    ]


# =====================================================================
#  Les traitements — ce que les agents ont ecrit
# =====================================================================


#: Ce que le front affiche a la place d'un statut brut. Le vocabulaire suit le
#: trajet decrit par le Port : on « rend » un traitement, on ne le « soumet »
#: pas a un visa (ADR 034).
LIBELLE_STATUT_TRAITEMENT = {
    Traitement.STATUT_BROUILLON: "En cours de rédaction",
    Traitement.STATUT_SOUMIS: "Restitué, en attente du responsable",
    Traitement.STATUT_RETOURNE: "Retourné pour reprise",
    Traitement.STATUT_VALIDE: "Retenu à la clôture",
}


def traitements(courrier: Courrier, utilisateur: Utilisateur) -> list[dict]:
    """
    Les traitements du courrier que ce lecteur a le droit de lire.

    **Le meme cloisonnement que les gestes internes** (ADR 032) : ce qu'un agent
    de la DAF a ecrit ne regarde pas la DSI cotee sur le meme courrier. La
    frontiere est celle de `structures_lisibles()`, qui rend `None` pour les
    portees larges — direction generale et suivi lisent tout, c'est leur
    mission.

    Un brouillon n'est visible que de **son auteur**. Un responsable qui lirait
    par-dessus l'epaule verrait un texte que l'agent n'a pas fini d'ecrire, et
    le jugerait sur lui.
    """
    lisibles = structures_lisibles(utilisateur)
    lignes = (
        Traitement.objects.filter(courrier=courrier, invalide_le__isnull=True)
        .select_related("redacteur", "cotation_structure__structure")
        .order_by("-cree_le")
    )
    if lisibles is not None:
        lignes = lignes.filter(cotation_structure__structure_id__in=sorted(lisibles))

    return [
        _ligne_traitement(traitement)
        for traitement in lignes
        if traitement.statut != Traitement.STATUT_BROUILLON
        or traitement.redacteur_id == utilisateur.pk
    ]


def _ligne_traitement(traitement: Traitement) -> dict:
    return {
        "id": traitement.pk,
        "redacteur": f"{traitement.redacteur.prenom} {traitement.redacteur.nom}",
        "redacteurId": traitement.redacteur_id,
        "structure": traitement.cotation_structure.structure.libelle,
        "version": traitement.version,
        "contenu": traitement.contenu or "",
        "statut": traitement.statut,
        "statutLibelle": LIBELLE_STATUT_TRAITEMENT.get(traitement.statut, traitement.statut),
        "restitueLe": (traitement.soumis_le.isoformat() if traitement.soumis_le else None),
        "modifieLe": (
            traitement.modifie_le.isoformat()
            if traitement.modifie_le
            else traitement.cree_le.isoformat()
        ),
    }


def mon_traitement(courrier: Courrier, utilisateur: Utilisateur) -> dict | None:
    """
    Le traitement de **ce** lecteur, s'il en a ouvert un.

    Sert a l'ecran de redaction : c'est ce qu'il recharge dans la zone de saisie.
    Distinct de `traitements()`, qui sert a lire ceux des autres.
    """
    traitement = (
        Traitement.objects.filter(
            courrier=courrier, redacteur=utilisateur, invalide_le__isnull=True
        )
        .select_related("redacteur", "cotation_structure__structure")
        .order_by("-cree_le")
        .first()
    )
    return _ligne_traitement(traitement) if traitement else None

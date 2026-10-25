"""
Le tableau de relance — C-02, premiere partie du pilier suivi.

    « Division du Suivi et de la Relance » (§3.3)

**L'ecran du responsable, pas celui de l'agent.** Le registre repond « qu'ai-je
a faire » ; celui-ci repond « qu'est-ce qui ne se fait pas ». La difference se
voit dans le tri : ici, ce qui deborde le plus est en tete, et le reste ne se
lit jamais.

La relance est une **action de masse** — on relance les quatorze retards du
lundi matin, pas un dossier a la fois. Les lignes portent donc de quoi decider
en lot : le delai consomme, la derniere relance, le niveau d'escalade deja
atteint. Relancer une troisieme fois un dossier deja escalade ne sert a rien, et
c'est ce que la colonne « Escalade » evite.

**Ce que ce module ne fait pas.** Il ne relance pas : l'emission d'une relance
de courrier viendra avec la suite du pilier, comme `POST /suivi/relances`. Ici
tout est en lecture, et la table `relance` du socle n'est interrogee que pour
dire ce qui a deja ete fait.

**Trois valeurs sans source**, posees en `hypothese` dans `parametre` par la
migration `noyau/0022`, et documentees en A76, A77 et A78 :

    suivi.retard_grave_jours            au-dela de combien un retard est grave
    suivi.relances_par_niveau_escalade  ce qu'est un « niveau » d'escalade
    suivi.fenetre_taux_respect_jours    sur quelle profondeur se calcule le taux

Elles sont lues a chaque appel — le cache de `noyau.parametres.service` les rend
gratuites — pour qu'une correction en base prenne effet sans redeploiement.

La visibilite passe par `visibles()`, comme toute lecture du pilier. Un tableau
de relance calcule hors perimetre serait une fuite doublement discrete : les
totaux disent quelque chose meme quand les lignes sont fermees.
"""

from datetime import date, timedelta

from django.db import models
from django.utils import timezone

from courrier.lecture import _delai
from courrier.modeles import STATUT_CLOTURE, Affectation, Courrier, Relance
from courrier.visibilite import visibles
from noyau.calendrier import jours_ouvres_entre
from noyau.identite.modeles import Utilisateur
from noyau.organisation.tete import responsable_a_relancer
from noyau.parametres import service as parametres

#: Le plafond de lignes rendues. Comme la supervision : un tableau trie par
#: retard decroissant se lit du haut, et la deux-centieme ligne n'a jamais
#: decide d'une relance.
PLAFOND = 200

#: Les cinq onglets de l'ecran. Une vue inconnue ne filtre rien plutot que de
#: vider la liste — meme convention que le registre : un filtre mal orthographie
#: qui vide l'ecran se lit comme une panne.
VUES = ("horsDelai", "sous48h", "sansAccuse", "dejaRelances", "tous")

#: « Sous 48 h » est dit par le libelle de l'onglet, pas invente ici. Deux jours
#: **calendaires** et non ouvres : l'agent qui lit « echeance sous 48 heures »
#: pense a son vendredi soir, pas au calendrier des feries.
HORIZON_PROCHE_JOURS = 2


def tableau(utilisateur: Utilisateur, *, vue: str = "horsDelai") -> dict:
    """
    Le tableau de relance et ses quatre indicateurs.

    Les indicateurs sont calcules sur **l'ensemble des dossiers en cours** et non
    sur la vue affichee : ils ne bougent pas quand on change d'onglet, parce
    qu'ils repondent a « ou en est le Port », pas a « que montre cet onglet ».
    Les faire suivre le filtre aurait donne quatre cartes qui disent la meme
    chose que la liste juste en dessous.
    """
    en_cours = _en_cours(utilisateur)

    courriers = list(en_cours.select_related("nature", "priorite", "structure_chef_file__tete"))
    identifiants = [courrier.pk for courrier in courriers]

    affectations = _affectations_courantes(identifiants)
    relances = _relances(identifiants)
    interlocuteurs = _interlocuteurs(courriers)

    lignes = [_ligne(courrier, affectations, relances, interlocuteurs) for courrier in courriers]
    retenues = [ligne for ligne in lignes if _retient(ligne, vue, relances)]

    # Le tri est en Python : `delai` est calcule en jours ouvres par
    # `noyau.calendrier`, qui connait les feries camerounais — un `ORDER BY` ne
    # saurait pas les compter.
    retenues.sort(key=_rang, reverse=True)

    return {
        "lignes": [_sans_interne(ligne) for ligne in retenues[:PLAFOND]],
        "indicateurs": _indicateurs(utilisateur, lignes),
    }


def _en_cours(utilisateur: Utilisateur) -> models.QuerySet:
    """
    Les dossiers que la relance regarde : ce qui est ouvert, et rien d'autre.

    Un courrier clos ne se relance pas, quel qu'ait ete son retard. Il compte en
    revanche dans le taux de respect, qui se calcule sur des dossiers fermes —
    c'est la seule mesure de ce module qui regarde le passe.
    """
    return visibles(
        Courrier.objects.filter(invalide_le__isnull=True).exclude(statut_courrier=STATUT_CLOTURE),
        utilisateur,
    )


def _affectations_courantes(identifiants: list[int]) -> dict[int, dict]:
    """
    L'agent qui detient chaque courrier, et s'il a signe sa decharge.

    Une requete d'ensemble, jamais une par ligne. Le tri par `affecte_le`
    croissant suivi de l'ecrasement retient la plus recente : c'est le detenteur
    actuel, et non le premier a qui le dossier est passe.
    """
    if not identifiants:
        return {}

    par_courrier: dict[int, dict] = {}
    for affectation in (
        Affectation.objects.filter(
            cotation_structure__cotation__courrier_id__in=identifiants,
            cotation_structure__cotation__invalide_le__isnull=True,
            retire_le__isnull=True,
        )
        .select_related(
            "utilisateur", "cotation_structure__structure", "cotation_structure__cotation"
        )
        .order_by("affecte_le")
    ):
        agent = affectation.utilisateur
        par_courrier[affectation.cotation_structure.cotation.courrier_id] = {
            "agent": f"{agent.prenom} {agent.nom}".strip(),
            "structure": affectation.cotation_structure.structure.code,
            "accuse": affectation.accepte_le is not None,
        }
    return par_courrier


def _relances(identifiants: list[int]) -> dict[int, dict]:
    """
    Ce qui a deja ete relance.

    Lu en SQL direct jusqu'au 28 aout 2026, faute de modele : deux colonnes
    agregees ne justifiaient pas d'en ouvrir un. Servir le **geste** de relance
    l'a justifie — une ecriture metier passe par `acteur()` et le journal — et la
    lecture suit desormais le meme chemin que l'ecriture. Deux acces a la meme
    table, l'un par l'ORM et l'autre au curseur, finissent par diverger sur un
    filtre.

    La colonne `courrier_id` existe depuis `0001` et peut etre nulle : la table
    sert aussi les relances d'activite. Le filtre sur les identifiants suffit
    donc a n'en compter aucune ici.
    """
    if not identifiants:
        return {}

    return {
        ligne["courrier_id"]: {"nombre": ligne["nombre"], "derniere": ligne["derniere"]}
        for ligne in Relance.objects.filter(courrier_id__in=identifiants)
        .values("courrier_id")
        .annotate(nombre=models.Count("id"), derniere=models.Max("emise_le"))
    }


def _ligne(
    courrier: Courrier, affectations: dict, relances: dict, interlocuteurs: dict[int, str]
) -> dict:
    """
    Une ligne du tableau, plus deux champs internes au tri et au filtrage.

    `_interne` porte ce que le front n'a pas a connaitre — la structure a compter,
    l'accuse signe ou non. Il est retire avant l'envoi par `_sans_interne()` :
    un champ rendu est un champ que quelqu'un finira par afficher.
    """
    detention = affectations.get(courrier.pk)
    relance = relances.get(courrier.pk)
    delai = _delai(courrier)
    chef_de_file = courrier.structure_chef_file_id

    structure = None
    if detention is not None:
        structure = detention["structure"]
    elif courrier.structure_chef_file is not None:
        structure = courrier.structure_chef_file.code

    return {
        "id": courrier.pk,
        "numero": courrier.numero,
        "objet": courrier.objet,
        # **A qui la relance s'adresse.** Le tableau C-02 est une action de
        # masse : sans le nom du directeur, l'agent de la DSR doit ouvrir
        # quatorze fiches pour savoir a qui ecrire.
        "interlocuteur": (interlocuteurs.get(chef_de_file) if chef_de_file else None) or "—",
        # « Non cotée » et non une chaine vide : la colonne dit alors quelque
        # chose — le courrier n'est chez personne, et c'est un motif de relance
        # a lui seul.
        "structure": structure or "Non cotée",
        "agent": detention["agent"] if detention else None,
        "delai": delai,
        "derniereRelance": relance["derniere"] if relance else None,
        "niveauEscalade": _niveau_escalade(relance["nombre"] if relance else 0),
        "_interne": {
            "structure": structure,
            "accuse": detention["accuse"] if detention else False,
            "affecte": detention is not None,
            "depassement": delai["joursDepassement"] if delai else 0,
            "echeance": courrier.date_limite,
        },
    }


def _interlocuteurs(courriers: list[Courrier]) -> dict[int, str]:
    """
    Le directeur a relancer, par structure chef de file.

    Memorise avant la boucle et non calcule ligne a ligne : `responsable_a_relancer`
    remonte l'arbre poste par poste, et deux cents lignes auraient produit deux
    cents remontees. Les dossiers se concentrent de toute facon sur une
    quinzaine de directions.
    """
    par_structure: dict[int, str] = {}
    for courrier in courriers:
        structure = courrier.structure_chef_file
        if structure is None or structure.pk in par_structure:
            continue
        directeur = responsable_a_relancer(structure)
        if directeur is not None:
            par_structure[structure.pk] = directeur.nom_complet
    return par_structure


def _niveau_escalade(relances_emises: int) -> int:
    """
    De 0 a 3, deduit du nombre de relances deja emises.

    **Hypothese** (A77) : une relance vaut un niveau, reglable par
    `suivi.relances_par_niveau_escalade`. Rien ne definit ce qu'est un niveau ;
    l'ecran, lui, en affiche trois depuis la maquette. Le plafond a 3 n'est pas
    un choix : c'est le sommet de la hierarchie du Port — chef de service,
    directeur, Directeur general.
    """
    par_niveau = max(1, parametres.valeur("suivi.relances_par_niveau_escalade", 1))
    return min(3, relances_emises // par_niveau)


def _retient(ligne: dict, vue: str, relances: dict) -> bool:
    """
    L'onglet, applique a une ligne deja construite.

    En Python et non en base, contrairement au registre : le depassement se
    compte en jours ouvres et « sans accuse » se lit sur l'affectation la plus
    recente. Les deux ont deja ete calcules ci-dessus ; les recalculer en SQL
    aurait fait deux definitions du meme mot.
    """
    interne = ligne["_interne"]

    if vue == "horsDelai":
        return interne["depassement"] > 0
    if vue == "sous48h":
        echeance = interne["echeance"]
        if echeance is None or interne["depassement"] > 0:
            return False
        return echeance <= date.today() + timedelta(days=HORIZON_PROCHE_JOURS)
    if vue == "sansAccuse":
        # Affecte et non signe. Un courrier que personne ne detient n'est pas
        # « sans accuse » : il est sans destinataire, ce qui est un autre defaut
        # et se lit dans la colonne « Agent ».
        return interne["affecte"] and not interne["accuse"]
    if vue == "dejaRelances":
        return ligne["id"] in relances
    return True


def _rang(ligne: dict) -> tuple:
    """
    L'ordre de lecture : le plus en retard d'abord, puis le plus proche d'echoir.

    Une echeance absente passe en dernier — un courrier sans delai ne se relance
    pas au nom d'un delai. `date.max` plutot qu'un `None` que le tri refuserait
    de comparer.
    """
    interne = ligne["_interne"]
    jours_restants = (interne["echeance"] - date.today()).days if interne["echeance"] else 10_000
    return (interne["depassement"], -jours_restants)


def _sans_interne(ligne: dict) -> dict:
    return {cle: valeur for cle, valeur in ligne.items() if cle != "_interne"}


def _indicateurs(utilisateur: Utilisateur, lignes: list[dict]) -> dict:
    """
    Les quatre cartes du bandeau.

    Toutes bornees au perimetre de l'appelant, comme les lignes : un compteur
    calcule hors perimetre est une fuite discrete — le nombre dit quelque chose
    meme quand la liste est fermee.
    """
    grave = parametres.valeur("suivi.retard_grave_jours", 5)

    hors_delai = [ligne for ligne in lignes if ligne["_interne"]["depassement"] > 0]
    proches = [ligne for ligne in lignes if _retient(ligne, "sous48h", {})]

    return {
        "horsDelai": len(hors_delai),
        "horsDelaiGrave": sum(
            1 for ligne in hors_delai if ligne["_interne"]["depassement"] > grave
        ),
        "sous48h": len(proches),
        # Les structures que le retard concerne, et non toutes celles qui ont un
        # dossier : la carte accompagne « echeance sous 48 h » et repond a « chez
        # combien de portes faut-il aller frapper ».
        "structuresConcernees": len(
            {
                ligne["_interne"]["structure"]
                for ligne in hors_delai + proches
                if ligne["_interne"]["structure"]
            }
        ),
        "relancesMois": _relances_du_mois(),
        "escalades": sum(1 for ligne in lignes if ligne["niveauEscalade"] > 0),
        "tauxRespect": _taux_de_respect(utilisateur),
    }


def _relances_du_mois() -> int:
    """
    Les relances de courrier emises depuis le premier du mois.

    Le mois civil et non trente jours glissants : la carte dit « ce mois », et
    c'est ainsi qu'un rapport mensuel se lit. Les relances d'activite ne sont pas
    comptees — `courrier_id IS NOT NULL` — bien qu'elles partagent la table :
    l'ecran est celui du courrier.
    """
    debut = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Relance.objects.filter(courrier_id__isnull=False, emise_le__gte=debut).count()


def _taux_de_respect(utilisateur: Utilisateur) -> int:
    """
    La part des courriers clos **dans leur delai**, en pourcentage entier.

    C'est la seule mesure du module qui regarde des dossiers fermes : un taux de
    respect se constate a la cloture, jamais en cours de route.

    **Hypothese** (A78) : la fenetre est de douze mois glissants,
    `suivi.fenetre_taux_respect_jours`. Rien ne la fixe, et elle change tout — une
    fenetre courte fait bondir le taux a chaque semaine creuse.

    Rend 0 quand rien n'a ete clos sur la periode, et c'est defendable ici :
    l'ADR 011 interdit d'afficher un zero qui se lirait comme une mesure, mais le
    front rend `tauxRespect` en pourcentage sans etat « non mesure ». Le jour ou
    la carte saura dire « non mesure », ce zero deviendra `None`. C'est note en
    A78.
    """
    fenetre = parametres.valeur("suivi.fenetre_taux_respect_jours", 365)
    depuis = timezone.now() - timedelta(days=fenetre)

    clos = visibles(
        Courrier.objects.filter(
            invalide_le__isnull=True,
            statut_courrier=STATUT_CLOTURE,
            cloture_le__gte=depuis,
            date_limite__isnull=False,
        ),
        utilisateur,
    ).values_list("date_limite", "cloture_le")

    total = 0
    tenus = 0
    for date_limite, cloture_le in clos:
        total += 1
        # Le jour de l'echeance compte comme tenu : un courrier clos le jour de
        # sa date limite n'est pas en retard.
        if jours_ouvres_entre(date_limite, cloture_le.date()) == 0:
            tenus += 1

    if total == 0:
        return 0
    return round(tenus * 100 / total)

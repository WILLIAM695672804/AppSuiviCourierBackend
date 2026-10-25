"""
Les traitements que personne ne declenche, pour la gouvernance.

**Ce n'est pas de l'optimisation.** L'etat d'un engagement change avec le seul
passage du temps : une decision devient « en retard » a minuit, sans qu'aucune
ecriture ne survienne. Sans ces taches, seules les decisions que quelqu'un a
touchees paraissent en retard — et la structure qui ne fait rien n'est jamais
signalee, soit exactement l'inverse du but.

Trois traitements :

 1. **Les agregats** (`agregat_gouvernance_jour`) — le tableau de bord du CODIR
    n'agrege jamais la table des engagements a la volee. Il sert l'historique
    et les courbes ; l'ecran du jour, lui, agrege en direct.
 2. **Les relances** des engagements en retard — l'escalade du §16 appliquee au
    registre des decisions. Le seuil et l'intervalle n'ont **aucune source** :
    ils sont en `parametre`, statut `hypothese` (A16).
 3. **L'alerte des depots en souffrance** — un compte rendu attendu depuis trois
    semaines n'interesse plus personne, et c'est precisement pour cela qu'il
    faut le dire pendant qu'il compte encore.

**Aucune de ces taches n'a d'acteur.** Elles declarent donc leur contexte par
`traitement_automatique(<nom>)`, faute de quoi le declencheur d'historisation
les refuse.

**Elles sont idempotentes.** Relancees deux fois le meme jour, elles ne doublent
rien : c'est la condition pour qu'on puisse les rejouer apres un incident sans
se demander ce qu'elles ont deja fait.
"""

from datetime import date, timedelta

from celery import shared_task
from django.db.models import Max, Q

from gouvernance.modeles import (
    AgregatGouvernanceJour,
    Disponibilite,
    Engagement,
    EngagementObservation,
    Seance,
    VueEngagementEtat,
)
from noyau.journal.contexte import traitement_automatique
from noyau.journal.service import inscrire
from noyau.parametres.service import valeur

# =====================================================================
#  1. Agregats
# =====================================================================


@shared_task(name="gouvernance.recalculer_agregats")
def recalculer_agregats(jour: str | None = None) -> int:
    """
    Recalcule `agregat_gouvernance_jour`, une ligne par couple origine/instance.

    L'etat de chaque engagement est lu dans **`v_engagement_etat`**, et non
    recalcule ici : c'est la vue qui fait foi cote SQL, et deux calculs d'une
    meme regle divergent toujours un jour.

    Les depots en souffrance et les absences sans interim sont portes sur
    **toutes** les lignes du jour et non reparties : ils ne se rattachent a
    aucune instance, et les diviser aurait produit des chiffres faux qu'un
    tableau de bord aurait sommes.

    Renvoie le nombre de lignes ecrites — un zero inattendu se voit tout de
    suite dans le journal.
    """
    cible = date.fromisoformat(jour) if jour else date.today()
    etats = list(VueEngagementEtat.objects.all())
    depots = _depots_en_souffrance(cible)
    sans_interim = _absences_sans_interim(cible)
    ecrites = 0

    with traitement_automatique("recalcul_agregats_gouvernance"):
        for (origine, instance), lignes in _par_origine(etats).items():
            AgregatGouvernanceJour.objects.update_or_create(
                jour=cible,
                origine=origine,
                instance=instance,
                defaults={
                    "nb_total": len(lignes),
                    "nb_a_lancer": sum(1 for e in lignes if e.etat_affiche == "a_lancer"),
                    "nb_en_cours": sum(1 for e in lignes if e.etat_affiche == "en_cours"),
                    "nb_executes": sum(1 for e in lignes if e.etat_affiche == "execute"),
                    "nb_en_retard": sum(1 for e in lignes if e.etat_affiche == "en_retard"),
                    "nb_suspendus": sum(1 for e in lignes if e.etat_affiche == "suspendu"),
                    "depots_en_souffrance": depots,
                    "absences_sans_interim": sans_interim,
                },
            )
            ecrites += 1

        inscrire(
            objet_type="agregat_gouvernance",
            objet_id=0,
            type_evenement="agregats_recalcules",
            libelle=f"Agregats de gouvernance recalcules pour le {cible.isoformat()}",
            donnees={"jour": cible.isoformat(), "lignes": ecrites},
        )
    return ecrites


def _par_origine(etats: list[VueEngagementEtat]) -> dict[tuple[str, str], list[VueEngagementEtat]]:
    """
    Regroupe par origine et par instance.

    `instance` vaut la **chaine vide** et non `None` pour les prescriptions et
    recommandations : la colonne appartient a la clef primaire, et une clef
    primaire ne se compare pas a `NULL`.
    """
    groupes: dict[tuple[str, str], list[VueEngagementEtat]] = {}
    for etat in etats:
        groupes.setdefault((etat.origine, etat.instance or ""), []).append(etat)
    return groupes


def _depots_en_souffrance(jour: date) -> int:
    """
    Les seances dont l'echeance de depot est passee sans compte rendu.

    Le proces-verbal vaut compte rendu : une session du CA rend un PV, pas un
    compte rendu, et les distinguer ici ferait paraitre en souffrance toutes les
    sessions du conseil.
    """
    return (
        Seance.objects.filter(invalide_le__isnull=True, echeance_depot__lt=jour)
        .exclude(
            documents__nature__in=("compte_rendu", "proces_verbal"),
            documents__depose_le__isnull=False,
        )
        .count()
    )


def _absences_sans_interim(jour: date) -> int:
    return Disponibilite.objects.filter(
        invalide_le__isnull=True,
        interimaire__isnull=True,
        du__lte=jour,
        au__gte=jour,
    ).count()


# =====================================================================
#  2. Relances
# =====================================================================


@shared_task(name="gouvernance.relancer_les_engagements")
def relancer_les_engagements(aujourd_hui: str | None = None) -> int:
    """
    Relance les structures pilotes des engagements en retard — §16.

    **Le seuil et l'intervalle n'ont aucune source.** Ils sont en `parametre`,
    statut `hypothese` (A16) : sept jours de retard avant la premiere relance,
    quatorze jours avant la suivante. Relancer des le premier jour ferait du
    signal un bruit ; ne jamais relancer viderait le §16 de son objet.

    La relance s'inscrit comme une **observation portant le drapeau `relance`**,
    sans auteur : personne ne l'a signee, et lui attribuer un agent serait faux.
    C'est le meme choix que `relance.emetteur_id` nul pour les courriers. Elle
    va dans le meme fil que les relances de la DSR — les distinguer par une
    table separee aurait casse la lecture chronologique du suivi.
    """
    jour = date.fromisoformat(aujourd_hui) if aujourd_hui else date.today()
    seuil = valeur("gouvernance.relance_auto_apres_jours", 7)
    intervalle = valeur("gouvernance.relance_auto_intervalle_jours", 14)
    envoyees = 0

    with traitement_automatique("relances_gouvernance"):
        candidats = (
            Engagement.objects.filter(
                invalide_le__isnull=True,
                echeance__isnull=False,
                echeance__lt=jour - timedelta(days=seuil),
                # L'arbitrage n° 2 : ni execute, ni suspendu. Relancer une
                # structure a qui une autorite a interdit d'avancer serait faux.
                execute_le__isnull=True,
                suspendu_le__isnull=True,
            )
            .annotate(
                _derniere_relance=Max("observations__cree_le", filter=Q(observations__relance=True))
            )
            .prefetch_related("structures__structure")
        )

        for engagement in candidats:
            if not _relance_due(engagement, jour, intervalle):
                continue
            pilote = next((c for c in engagement.structures.all() if c.pilote), None)
            if pilote is None:
                # Sans structure pilote, il n'y a personne a relancer. Le cas ne
                # devrait pas exister — `creer_engagement()` en exige une — mais
                # une reprise de donnees peut en produire, et une tache nocturne
                # ne doit pas tomber sur une ligne bancale.
                continue

            EngagementObservation.objects.create(
                engagement=engagement,
                texte=(
                    f"Relance automatique : echeance depassee depuis le "
                    f"{engagement.echeance.isoformat() if engagement.echeance else '?'}, "
                    f"avancement {engagement.avancement} %."
                ),
                relance=True,
                auteur=None,
            )
            inscrire(
                objet_type="engagement",
                objet_id=engagement.pk,
                type_evenement="relance_emise",
                libelle=f"Relance automatique adressee a {pilote.structure.code}",
                detail=f"Decision {engagement.reference}, avancement {engagement.avancement} %.",
                donnees={"automatique": True, "structure": pilote.structure.code},
            )
            envoyees += 1
    return envoyees


def _relance_due(engagement: Engagement, jour: date, intervalle: int) -> bool:
    """
    Jamais deux relances coup sur coup.

    Sans cet intervalle, la tache relancerait chaque nuit la meme decision : la
    structure cesserait de lire, et l'escalade ne servirait plus a rien.
    """
    derniere = getattr(engagement, "_derniere_relance", None)
    if derniere is None:
        return True
    return (jour - derniere.date()).days >= intervalle


# =====================================================================
#  3. Depots en souffrance
# =====================================================================


@shared_task(name="gouvernance.signaler_les_depots")
def signaler_les_depots(aujourd_hui: str | None = None) -> int:
    """
    Inscrit un evenement par seance dont le compte rendu manque au-dela du delai.

    **Une fois, pas chaque nuit.** Un evenement par seance et par jour ferait de
    la fiche de vie un journal de la tache plutot que de la seance ; on ne
    signale donc qu'a la premiere constatation, ce que l'absence d'evenement
    anterieur suffit a savoir.

    Renvoie le nombre de seances nouvellement signalees.
    """
    from noyau.journal.modeles import Evenement

    jour = date.fromisoformat(aujourd_hui) if aujourd_hui else date.today()
    signalees = 0

    with traitement_automatique("depots_en_souffrance"):
        en_retard = (
            Seance.objects.filter(invalide_le__isnull=True, echeance_depot__lt=jour)
            .exclude(
                documents__nature__in=("compte_rendu", "proces_verbal"),
                documents__depose_le__isnull=False,
            )
            .select_related("structure")
        )
        deja = set(
            Evenement.objects.filter(
                objet_type="seance", type_evenement="depot_en_souffrance"
            ).values_list("objet_id", flat=True)
        )

        for seance in en_retard:
            if seance.pk in deja:
                continue
            inscrire(
                objet_type="seance",
                objet_id=seance.pk,
                type_evenement="depot_en_souffrance",
                libelle=f"Compte rendu de {seance.reference} attendu depuis le "
                f"{seance.echeance_depot.isoformat()}",
                detail=f"Secretariat : {seance.structure.code}.",
                donnees={"jours": (jour - seance.echeance_depot).days},
            )
            signalees += 1
    return signalees

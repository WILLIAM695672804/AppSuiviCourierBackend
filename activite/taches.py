"""
Les traitements que personne ne declenche.

**Ce n'est pas de l'optimisation.** Le retard, la criticite et le taux
d'execution changent avec le seul passage du temps, sans qu'aucune ecriture ne
survienne. Sans ces taches, seules les activites que quelqu'un a touchees
paraissent en retard, et une structure qui ne saisit rien n'est jamais signalee
— soit exactement l'inverse du but.

Trois traitements, et chacun repond a une phrase du cahier des charges :

 1. **Les agregats** (`agregat_activite_jour`) — le tableau de bord du Directeur
    general (§20) n'agrege jamais la table des activites a la volee.
 2. **Les obligations** — le calendrier de production (§3.3) decide « qui
    alimente quoi, a quelle frequence ». Une obligation qu'une structure devrait
    creer elle-meme ne serait jamais creee, et cette structure ne serait jamais
    en retard.
 3. **Les relances automatiques** — l'escalade du §16. Elles s'adressent au
    **directeur de la structure chargee**, pas au responsable nomme : c'est lui
    qui peut arbitrer, et lui qui redescend en interne. Le seuil et
    l'intervalle n'ont **aucune source** : ils sont en `parametre`, statut
    `hypothese` (A16).

**Aucune de ces taches n'a d'acteur.** Elles declarent donc leur contexte par
`traitement_automatique(<nom>)`, faute de quoi le declencheur d'historisation
les refuse. Nommer le traitement plutot qu'ecrire « batch » partout est le seul
moyen de savoir, six mois plus tard, lequel a touche la ligne.

**Elles sont idempotentes.** Relancees deux fois le meme jour, elles ne
doublent rien : c'est la condition pour qu'on puisse les rejouer apres un
incident sans se demander ce qu'elles ont deja fait.
"""

from datetime import date, timedelta
from decimal import Decimal

from celery import shared_task
from django.db import connection

from activite.lecture import est_critique
from activite.modeles import (
    Activite,
    AgregatActiviteJour,
    CalendrierProduction,
    Exercice,
    Obligation,
    PlanActions,
)
from noyau.journal.contexte import traitement_automatique
from noyau.journal.service import inscrire
from noyau.organisation.tete import responsable_a_relancer
from noyau.parametres.service import valeur

#: Mois couverts par une periode, selon la periodicite du calendrier.
MOIS_PAR_PERIODICITE = {
    "mensuelle": 1,
    "trimestrielle": 3,
    "semestrielle": 6,
    "annuelle": 12,
}


# =====================================================================
#  1. Agregats
# =====================================================================


@shared_task(name="activite.recalculer_agregats")
def recalculer_agregats(jour: str | None = None) -> int:
    """
    Recalcule `agregat_activite_jour` pour toutes les structures portant un plan.

    L'etat de chaque activite est lu dans **`v_activite_etat`**, et non recalcule
    ici : c'est la vue qui fait foi cote SQL, et deux calculs d'une meme regle
    divergent toujours un jour.

    Renvoie le nombre de lignes ecrites — le journal en garde trace, et un zero
    inattendu se voit tout de suite.
    """
    cible = date.fromisoformat(jour) if jour else date.today()
    ecrites = 0

    with traitement_automatique("recalcul_agregats"):
        for plan in (
            PlanActions.objects.filter(invalide_le__isnull=True)
            .select_related("structure", "exercice")
            .order_by("structure__code")
        ):
            _agreger(plan, cible)
            ecrites += 1

        inscrire(
            objet_type="agregat_activite",
            objet_id=0,
            type_evenement="agregats_recalcules",
            libelle=f"Agregats d'activites recalcules pour le {cible.isoformat()}",
            donnees={"jour": cible.isoformat(), "lignes": ecrites},
        )
    return ecrites


def _agreger(plan: PlanActions, jour: date) -> None:
    etats = _etats_affiches(plan)
    activites = list(
        plan.activites.filter(invalide_le__isnull=True).prefetch_related("taches", "instructions")
    )

    nb_critiques = sum(1 for a in activites if est_critique(a, aujourd_hui=jour))
    total = len(activites)
    realisees = sum(1 for e in etats.values() if e == "realisee")

    budgets_valides = [a.budget_valide for a in activites if a.budget_valide is not None]
    budgets_consommes = [a.budget_consomme for a in activites if a.budget_consomme is not None]

    AgregatActiviteJour.objects.update_or_create(
        structure=plan.structure,
        exercice=plan.exercice,
        jour=jour,
        defaults={
            "nb_total": total,
            "nb_realisees": realisees,
            "nb_en_cours": sum(1 for e in etats.values() if e in ("en_cours", "programmee")),
            "nb_en_retard": sum(1 for e in etats.values() if e == "en_retard"),
            "nb_suspendues": sum(1 for e in etats.values() if e == "suspendue"),
            "nb_critiques": nb_critiques,
            # Taux d'execution : part des activites realisees. `None` et non
            # zero quand le plan est vide — zero se lirait comme une contre-
            # performance, alors qu'il n'y a rien a executer.
            "taux_execution": (round(Decimal(100) * realisees / total, 2) if total else None),
            "budget_valide": sum(budgets_valides) if budgets_valides else None,
            "budget_consomme": sum(budgets_consommes) if budgets_consommes else None,
        },
    )


def _etats_affiches(plan: PlanActions) -> dict[int, str]:
    """
    L'etat affiche de chaque activite du plan, tel que la vue le calcule.

    Requete directe : `VueActiviteEtat` n'est pas geree par l'ORM et la filtrer
    par plan tient en une ligne de SQL.
    """
    with connection.cursor() as curseur:
        curseur.execute("SELECT id, etat_affiche FROM v_activite_etat WHERE paa_id = %s", [plan.pk])
        return dict(curseur.fetchall())


# =====================================================================
#  2. Obligations
# =====================================================================


@shared_task(name="activite.engendrer_obligations")
def engendrer_obligations(aujourd_hui: str | None = None) -> int:
    """
    Cree les obligations dues, depuis le calendrier de production — §3.3.

    **Jamais saisies a la main.** Une structure qui ne creerait pas son
    obligation ne serait jamais en retard, ce qui est l'inverse du but.

    Idempotente par la contrainte `obligation_unique_par_periode` : relancee
    deux fois, elle ne cree rien de plus.
    """
    jour = date.fromisoformat(aujourd_hui) if aujourd_hui else date.today()
    creees = 0

    with traitement_automatique("engendrement_obligations"):
        for ligne in CalendrierProduction.objects.filter(
            actif=True, valide_au__isnull=True
        ).select_related("structure"):
            for debut, fin, libelle in _periodes_dues(ligne, jour):
                _, cree = Obligation.objects.get_or_create(
                    calendrier_production=ligne,
                    periode_debut=debut,
                    defaults={
                        "structure": ligne.structure,
                        "intitule": ligne.intitule,
                        "periode_libelle": libelle,
                        "periode_fin": fin,
                        "echeance": _echeance(fin, ligne.jour_echeance),
                    },
                )
                creees += 1 if cree else 0

        if creees:
            inscrire(
                objet_type="obligation",
                objet_id=0,
                type_evenement="obligations_engendrees",
                libelle=f"{creees} obligation(s) engendree(s) depuis le calendrier",
                donnees={"jour": jour.isoformat(), "creees": creees},
            )
    return creees


def _periodes_dues(ligne: CalendrierProduction, jour: date) -> list[tuple[date, date, str]]:
    """
    Les periodes closes dont le depot est attendu, sur les douze derniers mois.

    On regarde en arriere plutot que d'engendrer « la periode suivante » : une
    tache qui n'a pas tourne pendant trois jours doit rattraper son retard, pas
    laisser un trou que personne ne verra.

    Une periode n'est due qu'une fois **close** : le rapport de juillet ne
    s'attend pas le 15 juillet.
    """
    pas = MOIS_PAR_PERIODICITE[ligne.periodicite]
    dues = []

    debut = _debut_de_periode(jour, pas)
    for _ in range(12 // pas + 1):
        debut = _reculer(debut, pas)
        if debut < ligne.valide_du:
            break
        fin = _reculer(_ajouter_mois(debut, pas), 0) - timedelta(days=1)
        dues.append((debut, fin, _libelle_periode(debut, fin, ligne.periodicite)))
    return dues


def _debut_de_periode(jour: date, pas: int) -> date:
    """Le premier jour de la periode qui contient `jour`."""
    mois = ((jour.month - 1) // pas) * pas + 1
    return date(jour.year, mois, 1)


def _ajouter_mois(depart: date, mois: int) -> date:
    total = depart.month - 1 + mois
    return date(depart.year + total // 12, total % 12 + 1, 1)


def _reculer(depart: date, mois: int) -> date:
    return _ajouter_mois(depart, -mois)


def _libelle_periode(debut: date, fin: date, periodicite: str) -> str:
    """Ce que l'agent lit dans son registre : « Juillet 2026 », « T3 2026 »."""
    mois = [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ]
    if periodicite == "mensuelle":
        return f"{mois[debut.month - 1].capitalize()} {debut.year}"
    if periodicite == "trimestrielle":
        return f"T{(debut.month - 1) // 3 + 1} {debut.year}"
    if periodicite == "semestrielle":
        return f"S{(debut.month - 1) // 6 + 1} {debut.year}"
    return str(debut.year)


def _echeance(fin_de_periode: date, jour_echeance: int) -> date:
    """
    Le depot est attendu le `jour_echeance` de la periode **suivante** : le
    rapport de juillet est du le 5 aout.
    """
    lendemain = fin_de_periode + timedelta(days=1)
    return date(lendemain.year, lendemain.month, jour_echeance)


# =====================================================================
#  3. Relances automatiques
# =====================================================================


@shared_task(name="activite.relancer_les_retards")
def relancer_les_retards(aujourd_hui: str | None = None) -> int:
    """
    Relance les responsables des activites en retard — §16.

    **Le seuil et l'intervalle n'ont aucune source.** Ils sont en `parametre`,
    statut `hypothese` (A16) : sept jours de retard avant la premiere relance,
    quatorze jours avant la suivante. Relancer des le premier jour ferait du
    signal un bruit ; ne jamais relancer viderait le §16 de son objet.

    La relance automatique porte `nature = 'automatique'` et **aucun emetteur** :
    personne ne l'a signee, et lui attribuer un agent serait faux.
    """
    jour = date.fromisoformat(aujourd_hui) if aujourd_hui else date.today()
    seuil = valeur("activite.relance_auto_apres_jours", 7)
    intervalle = valeur("activite.relance_auto_intervalle_jours", 14)
    envoyees = 0

    with traitement_automatique("relances_automatiques"):
        candidates = (
            Activite.objects.filter(
                invalide_le__isnull=True,
                date_fin__lt=jour - timedelta(days=seuil),
            )
            # L'arbitrage n° 2 : ni realisee, ni suspendue. Relancer une
            # structure a qui une autorite a interdit d'avancer serait faux.
            .exclude(etat__in=(Activite.REALISEE, Activite.SUSPENDUE))
            .select_related("responsable", "plan__structure")
        )

        for activite in candidates:
            if not _relance_due(activite, jour, intervalle):
                continue

            # **Le destinataire est le directeur, pas le responsable nomme.**
            # L'escalade du §16 remonte a qui peut arbitrer, et un chef de
            # departement relance ne debloque rien qu'il ne pouvait deja faire.
            destinataire = responsable_a_relancer(activite.plan.structure)
            if destinataire is None:
                # On n'emet pas dans le vide (A81) : une relance sans
                # destinataire ferait croire que l'escalade a eu lieu. Le
                # journal garde la trace de ce qui n'est pas parti.
                inscrire(
                    objet_type="activite",
                    objet_id=activite.pk,
                    type_evenement="relance_sans_destinataire",
                    libelle=(
                        f"Relance non emise : aucun poste de tete pourvu au-dessus de "
                        f"{activite.plan.structure.code}."
                    ),
                    detail=(
                        f"Echeance depassee depuis le {activite.date_fin.isoformat()}, "
                        f"avancement {activite.avancement_retenu} %."
                    ),
                    donnees={"automatique": True},
                )
                continue

            _inscrire_relance_automatique(activite, destinataire, jour)
            Activite.objects.filter(pk=activite.pk).update(derniere_relance_le=_horodatage(jour))
            inscrire(
                objet_type="activite",
                objet_id=activite.pk,
                type_evenement="relance_emise",
                libelle=f"Relance automatique adressee a {destinataire.nom_complet}",
                detail=(
                    f"Echeance depassee depuis le {activite.date_fin.isoformat()}, "
                    f"avancement {activite.avancement_retenu} %."
                ),
                donnees={"automatique": True},
            )
            envoyees += 1
    return envoyees


def _relance_due(activite: Activite, jour: date, intervalle: int) -> bool:
    """
    Jamais deux relances coup sur coup.

    Sans cet intervalle, la tache relancerait chaque nuit la meme activite : le
    responsable cesserait de lire, et l'escalade ne servirait plus a rien.
    """
    if activite.derniere_relance_le is None:
        return True
    return (jour - activite.derniere_relance_le.date()).days >= intervalle


def _inscrire_relance_automatique(activite: Activite, destinataire, jour: date) -> None:
    """
    La table `relance` du socle, en SQL direct — aucun modele Django ne la
    couvre : elle sert l'activite comme le courrier, et ni l'un ni l'autre n'a
    eu besoin de la relire.

    `emetteur_id` reste nul : c'est ce qui distingue une relance automatique
    d'une relance signee par la DSR. `destinataire_id` est le directeur de la
    tete de structure, et non le responsable nomme de l'activite.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO relance (activite_id, nature, destinataire_id, motif, emise_le)
            VALUES (%s, 'automatique', %s, %s, %s)
            """,
            [
                activite.pk,
                destinataire.pk,
                f"Activite {activite.code} : echeance depassee depuis le "
                f"{activite.date_fin.isoformat()}.",
                _horodatage(jour),
            ],
        )


def _horodatage(jour: date):
    """
    Midi, heure locale, et non `now()`.

    Les taches acceptent un jour en parametre pour pouvoir etre rejouees ; y
    poser l'heure courante ferait porter a un rattrapage la date d'aujourd'hui
    et non celle du traitement.
    """
    from datetime import datetime, time

    from django.utils import timezone

    return timezone.make_aware(datetime.combine(jour, time(12, 0)))


# =====================================================================
#  Ouverture d'exercice
# =====================================================================


@shared_task(name="activite.ouvrir_exercice_suivant")
def ouvrir_exercice_suivant(aujourd_hui: str | None = None) -> bool:
    """
    Ouvre l'exercice de l'annee suivante en decembre.

    **Ne cloture pas le precedent.** Clore un exercice interdit toute saisie
    retroactive, et rien ne dit quand cela doit arriver — un plan se rend
    parfois en janvier pour l'annee ecoulee. La cloture reste un geste
    d'administration, volontaire et date.
    """
    jour = date.fromisoformat(aujourd_hui) if aujourd_hui else date.today()
    if jour.month != 12:
        return False

    suivant = jour.year + 1
    if Exercice.objects.filter(annee=suivant).exists():
        return False

    with traitement_automatique("ouverture_exercice"):
        Exercice.objects.create(annee=suivant, ouvert=True)
        inscrire(
            objet_type="exercice",
            objet_id=suivant,
            type_evenement="exercice_ouvert",
            libelle=f"Exercice {suivant} ouvert",
        )
    return True

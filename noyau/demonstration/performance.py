"""
Le calendrier de production et les obligations qui en decoulent — §3.3.

« Qui alimente quoi, a quelle frequence. » Une ligne de calendrier par
structure classee, et une obligation par periode close : c'est la tache
`activite.engendrer_obligations` qui les fabrique, jamais une saisie. Le semis
l'appelle telle quelle plutot que d'inserer des obligations a la main — une
structure qui ne creerait pas la sienne ne serait jamais en retard, ce qui est
exactement l'inverse du but.

Les depots sont ensuite poses par `activite.deposer_obligation`, pour une part
seulement : un calendrier ou tout serait depose n'aurait pas de retard a
montrer, et le taux de ponctualite du §3.3 vaudrait cent pour cent partout.

**La grille de cotation des risques reste vide.** Elle est ouverte en A26, et
la question dit precisement pourquoi : une grille inventee serait appliquee
telle quelle, conduite a tenir comprise. Un ecran vide est ici la reponse
juste — le semis ne la remplit pas, meme pour faire joli.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace

from django.db import connection

from activite import services as services_activite
from activite.modeles import CalendrierProduction, Obligation
from activite.taches import engendrer_obligations
from noyau.identite.modeles import Utilisateur
from performance import services

GRAINE = 20260819

#: Les productions inscrites au calendrier officiel :
#: (intitule, nature, periodicite, echeance en toutes lettres, mois
#: d'anciennete de la ligne).
#:
#: L'anciennete compte : `engendrer_obligations` ne remonte pas avant
#: `valide_du`. Une ligne creee aujourd'hui n'aurait engendre aucune obligation,
#: et l'ecran se serait ouvert sur un calendrier sans aucune echeance.
PRODUCTIONS = [
    (
        "Rapport mensuel d'activité",
        "Rapport mensuel d'activité",
        "Mensuelle",
        "le 5 du mois suivant",
        5,
    ),
    (
        "Procès-verbal de réunion de service",
        "Procès-verbal de réunion",
        "Trimestrielle",
        "le 10 du trimestre suivant",
        7,
    ),
]

#: La part des obligations echues qui sont deposees, en pourcentage.
#:
#: Ni cent — le retard doit se voir — ni la moitie : une institution ou une
#: production sur deux manque n'est pas credible, et le tableau entierement
#: rouge n'apprend rien. Le retard se concentre sur les periodes recentes,
#: comme pour le registre des courriers.
TAUX_DEPOT = 78

#: Ce que la structure ecrit en deposant. Un commentaire vide fait une colonne
#: vide, et l'ecran en porte une.
COMMENTAIRES = [
    "Rapport transmis dans les délais, données consolidées au 30 du mois.",
    "Dépôt effectué après consolidation des chiffres de l'exploitation.",
    "Transmis avec retard : le service attendait les données financières.",
    "Rapport déposé, annexes statistiques comprises.",
    "",
]


def semer(annuaire: dict[str, Utilisateur], ecrire) -> int:
    """Inscrit le calendrier, engendre les obligations, en depose une part."""
    if CalendrierProduction.objects.exists():
        ecrire(f"  {CalendrierProduction.objects.count()} lignes de calendrier — passe")
        return 0

    dsr = annuaire["dsr"]
    lignes = 0
    for production, nature, periodicite, echeance, anciennete in PRODUCTIONS:
        services.ajouter_production(
            dsr,
            production=production,
            nature=nature,
            periodicite=periodicite,
            echeance=echeance,
            relance_automatique=True,
            jours_avant_relance=3,
        )
        # `valide_du` vaut le jour de la creation : recule pour que les periodes
        # closes des mois precedents soient dues.
        CalendrierProduction.objects.filter(intitule=production).update(
            valide_du=date.today() - timedelta(days=30 * anciennete)
        )
        lignes += CalendrierProduction.objects.filter(intitule=production).count()

    creees = engendrer_obligations()
    deposees = _deposer(annuaire, ecrire)

    ecrire(f"  {lignes} lignes de calendrier, {creees} obligations, {deposees} deposees")
    return creees


def _deposer(annuaire: dict, ecrire) -> int:
    """
    Depose une part des obligations echues.

    L'acteur est le compte de la structure quand il en existe un — trente
    comptes pour soixante-dix-sept structures —, l'attachee de la DSR sinon.
    C'est ce qui se passe reellement : la DSR enregistre pour les services qui
    n'ont pas encore de compte, et la colonne « deposé par » le dit.
    """
    tirage = random.Random(GRAINE)
    par_structure = {agent.structure_id: agent for agent in annuaire.values() if agent.structure_id}
    att = annuaire["att.dsr"]
    deposees = 0

    for obligation in Obligation.objects.filter(
        depose_le__isnull=True, echeance__lt=date.today()
    ).order_by("echeance"):
        if tirage.randrange(100) >= TAUX_DEPOT:
            continue
        agent = par_structure.get(obligation.structure_id, att)
        services_activite.deposer_obligation(
            agent,
            obligation.pk,
            SimpleNamespace(
                nomFichier=f"{obligation.intitule} — {obligation.periode_libelle}.pdf",
                poids="2.1 Mo",
                commentaire=tirage.choice(COMMENTAIRES),
            ),
        )
        _dater(obligation, _jour_de_depot(obligation.echeance, tirage))
        deposees += 1

    ecrire(f"  {deposees} obligations deposees")
    return deposees


def _dater(obligation: Obligation, jour: date) -> None:
    """
    Recule le depot au jour ou il a eu lieu.

    `deposer_obligation` date du jour — c'est sa regle. Sans ce recul, les
    quatre cents depots des cinq derniers mois seraient tous tombes
    aujourd'hui, et la ponctualite se lirait a l'envers : tout en retard, et
    tout depose le meme jour.
    """
    with connection.cursor() as curseur:
        curseur.execute("UPDATE obligation SET depose_le = %s WHERE id = %s", [jour, obligation.pk])


def _jour_de_depot(echeance: date, tirage: random.Random) -> date:
    """
    Le jour du depot : le plus souvent avant l'echeance, parfois apres.

    Un depot toujours a l'heure ferait un taux de ponctualite de cent pour
    cent ; un depot toujours en retard, de zero. Ni l'un ni l'autre ne montre
    ce que la colonne « à l'heure » sert a distinguer.
    """
    ecart = tirage.choice([-6, -4, -3, -2, -1, -1, 0, 0, 2, 5, 9])
    jour = echeance + timedelta(days=ecart)
    return min(jour, date.today())

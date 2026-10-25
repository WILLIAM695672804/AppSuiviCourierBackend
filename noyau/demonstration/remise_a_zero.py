"""
La remise a zero des donnees de demonstration.

**Elle ne touche ni l'organigramme, ni les referentiels, ni les comptes.** Ce
qu'elle efface, ce sont les *faits* semes : courriers, cotations, activites,
dossiers, seances, mesures, et les evenements qui les racontent. Recharger
l'organigramme reel a chaque essai aurait coute une minute a chaque fois, et
surtout aurait reattribue des identifiants de structure — cassant toute capture
d'ecran prise avant.

Elle existe parce qu'un jeu de demonstration se **regle** : on change la
repartition des etats, on relance, on regarde. Sans elle, chaque essai
demandait un `TRUNCATE` a la main, c'est-a-dire la porte ouverte a un
`TRUNCATE` de trop.

L'ordre des tables suit les dependances, des filles vers les meres. `TRUNCATE
… CASCADE` s'en passerait, mais emporterait aussi les tables qu'on veut garder :
il suffit qu'une reference y pointe.
"""

from __future__ import annotations

from django.db import connection

#: Les tables videes, dans l'ordre. Une table absente de cette liste est une
#: table **conservee** : c'est le cas de `structure`, `poste`, `utilisateur`,
#: `profil`, `parametre`, et de tous les referentiels semes par les migrations.
TABLES = [
    # Courrier
    "traitement_version",
    "traitement",
    "relance",
    "transmission",
    "validation",
    "instance_etape",
    "instance_circuit",
    "affectation",
    "cotation_suivi",
    "cotation_structure",
    "cotation",
    # Portail — les demandes citent les courriers
    "piece_echange",
    "echange_dematerialise",
    "message_portail",
    "complement_demande",
    "piece_demande",
    "demande_usager",
    # Dossiers
    "version_piece_dossier",
    "piece_dossier",
    "complement_dossier",
    "dossier",
    # Archivage — les maillons d'integrite pendent aux versements
    "maillon_integrite",
    "versement",
    # Activites et plans
    "activite_suspension",
    "activite_indicateur",
    "tache",
    "instruction_activite",
    "activite",
    "paa_version",
    "paa",
    "obligation",
    # Engagements et gouvernance
    "engagement_observation",
    "engagement_jalon",
    "engagement_structure",
    "engagement",
    "decision_effet",
    "seance_document",
    "seance_participant",
    "seance_point",
    "seance",
    "disponibilite",
    "conge_periode",
    # Performance et pilotage
    "relance_production",
    "calendrier_production",
    "indicateur_mesure",
    "mesure_programme",
    "mesure_requete",
    "agregat_activite_jour",
    "agregat_structure_jour",
    "agregat_gouvernance_jour",
    # Exploitation
    "releve_chenal",
    "recouvrement",
    # Le courrier en dernier : tout ce qui precede le cite
    "piece_jointe",
    "courrier",
    # Notifications et journaux des faits semes
    "envoi_notification",
    "notification",
]


def vider(ecrire) -> None:
    """
    Efface les faits, garde le socle.

    `TRUNCATE` et non `DELETE` : les tables sont vides ensuite, les sequences
    reparties de zero, et les numeros de courrier de la demonstration
    recommencent a `0001/2026` — ce qu'un `DELETE` n'aurait pas fait, laissant
    un registre qui commence a `0061/2026` sans que rien ne l'explique.

    `evenement` et `journal_acces` sont traites a part : ce sont des tables
    partitionnees, et elles portent aussi les evenements du socle — la creation
    du compte d'administration, le chargement de l'organigramme. Seules les
    lignes qui citent un objet seme sont retirees.
    """
    with connection.cursor() as curseur:
        curseur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")

        # Les evenements des faits semes. Ceux du socle — organigramme, compte
        # d'administration — n'ont pas de `courrier_id` et ne citent pas ces
        # objets : ils survivent, et c'est voulu. Le journal de l'installation
        # n'est pas une donnee de demonstration.
        curseur.execute(
            """
            DELETE FROM evenement
             WHERE courrier_id IS NOT NULL
                OR objet_type IN ('activite', 'tache', 'dossier', 'seance', 'decision',
                                  'demande', 'paa', 'engagement', 'versement', 'releve')
            """
        )

        # La numerotation des registres repart, sans quoi le premier courrier
        # du prochain semis porterait le numero suivant celui d'un courrier
        # qui n'existe plus.
        curseur.execute("UPDATE sequence_numerotation SET dernier_numero = 0")

    ecrire("  donnees de demonstration effacees (socle et comptes conserves)")

"""
La definition du retard, tranchee.

Deux regles coexistaient et ne designaient pas les memes activites :
l'**arbitrage n° 2** (echeance depassee, etat non realisee), rendu par
l'institution et cite par le MODELE DE DONNEES v2, et l'**ecart a un avancement
attendu** (seuil de dix points), invente par la conception faute de reponse.

C'est l'arbitrage n° 2 qui l'emporte, pour une raison qui n'est pas de gout : il
a une source, l'autre n'en a pas. Le parametre inscrit ce choix en base plutot
qu'en dur, de sorte que le jour ou la DSR trancherait autrement, la correction
soit une ligne et non un redeploiement.

Les deux parametres de l'ecart a l'attendu — `activite.mode_avancement_attendu`
et `activite.seuil_retard_points` — **restent en hypothese et ne sont pas
modifies** : ils ne decident plus de l'etat, mais l'ecart reste affichable comme
indication. Voir docs/questions-ouvertes.md, A2.
"""

from django.db import migrations

CLE = "activite.definition_retard"


def poser(apps, schema_editor) -> None:
    Parametre = apps.get_model("noyau", "Parametre")
    Parametre.objects.update_or_create(
        cle=CLE,
        defaults={
            "libelle": "Regle qui determine qu'une activite est en retard",
            "valeur": "echeance_depassee",
            "type_valeur": "texte",
            "domaine": "activite",
            "statut": "acte",
            "source": "Arbitrage n° 2, cite par le MODELE DE DONNEES v2",
            "a_trancher_par": None,
        },
    )


def retirer(apps, schema_editor) -> None:
    apps.get_model("noyau", "Parametre").objects.filter(cle=CLE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(poser, retirer),
    ]

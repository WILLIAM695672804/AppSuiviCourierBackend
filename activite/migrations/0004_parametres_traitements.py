"""
Les deux reglages des traitements nocturnes.

Aucun des deux n'a de source. Le cahier des charges veut qu'une structure en
retard soit relancee (§16, descriptif §3.3) sans dire **au bout de combien de
jours**, ni **combien de fois**. Les coder en dur aurait fait passer une
invention pour une decision, et rendu leur correction impossible sans
redeploiement.

Ils sont donc en `hypothese`, avec l'interlocuteur qui doit trancher, et
inscrits en [A16](../../../docs/questions-ouvertes.md).
"""

from django.db import migrations

PARAMETRES = [
    (
        "activite.relance_auto_apres_jours",
        "Jours de retard au-dela desquels une relance automatique part",
        "7",
        "entier",
        "DSR",
    ),
    (
        "activite.relance_auto_intervalle_jours",
        "Jours a attendre avant de relancer a nouveau la meme activite",
        "14",
        "entier",
        "DSR",
    ),
]


def poser(apps, schema_editor) -> None:
    Parametre = apps.get_model("noyau", "Parametre")
    for cle, libelle, valeur, type_valeur, arbitre in PARAMETRES:
        Parametre.objects.update_or_create(
            cle=cle,
            defaults={
                "libelle": libelle,
                "valeur": valeur,
                "type_valeur": type_valeur,
                "domaine": "activite",
                "statut": "hypothese",
                "source": None,
                "a_trancher_par": arbitre,
            },
        )


def retirer(apps, schema_editor) -> None:
    apps.get_model("noyau", "Parametre").objects.filter(
        cle__in=[cle for cle, *_ in PARAMETRES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0003_accents_des_axes"),
    ]

    operations = [
        migrations.RunPython(poser, retirer),
    ]

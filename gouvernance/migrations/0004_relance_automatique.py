"""
Une relance automatique n'a pas d'auteur, et deux reglages n'ont pas de source.

**Le changement de schema.** `engagement_observation.auteur_id` etait `NOT NULL`.
C'est vrai des observations humaines et faux des relances que la tache nocturne
emet : personne ne les a signees. Le socle avait deja tranche pareil pour le
courrier — `relance.emetteur_id` est nullable, et c'est precisement ce qui
distingue une relance automatique d'une relance signee par la DSR.

Une contrainte remplace le `NOT NULL` : une observation sans auteur est
necessairement une relance. Une remarque anonyme dans le fil de suivi n'aurait
aucun sens.

**Les deux parametres.** Le cahier des charges veut qu'une structure en retard
soit relancee (§16) sans dire au bout de combien de jours ni combien de fois.
Les coder en dur aurait fait passer une invention pour une decision. Ils sont
donc en `hypothese`, et inscrits en
[A16](../../../docs/questions-ouvertes.md) — la meme question que pour les
activites, avec des valeurs propres : rien ne dit qu'on relance une direction
sur une decision du conseil au meme rythme que sur une activite de son plan.
"""

from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"

PARAMETRES = [
    (
        "gouvernance.relance_auto_apres_jours",
        "Jours de retard au-dela desquels un engagement est relance",
        "7",
        "entier",
        "DSR",
    ),
    (
        "gouvernance.relance_auto_intervalle_jours",
        "Jours a attendre avant de relancer a nouveau le meme engagement",
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
                "domaine": "gouvernance",
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
        ("gouvernance", "0003_pilote_typage"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0004_relance_automatique.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Le SQL a tout fait : Django n'a qu'a l'apprendre.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="engagementobservation",
                    name="auteur",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="auteur_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="noyau.utilisateur",
                    ),
                ),
            ]
        ),
        migrations.RunPython(poser, retirer),
    ]

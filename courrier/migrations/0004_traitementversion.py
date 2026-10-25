"""
Etat Django de `traitement_version`.

**Cette migration ne cree rien.** La table nait de
`noyau/migrations/sql/0001_socle.sql` — elle y est depuis le premier jour, sans
modele Django parce qu'aucun ecran ne l'ecrivait. L'ecran de redaction du
traitement l'ecrit desormais (27 aout 2026), d'ou le modele.

Une seule source de verite pour le schema : c'est l'[ADR 003]. Le contenu
ci-dessous a ete ecrit a la main, puis enveloppe dans
`SeparateDatabaseAndState` ; un `makemigrations courrier` relance seul tenterait
de creer la table une seconde fois.

[ADR 003]: ../../docs/architecture/003-django-proprietaire-du-schema.md
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courrier", "0003_decharge_observations_signalements"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TraitementVersion",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("version", models.SmallIntegerField()),
                        ("contenu", models.TextField(blank=True, null=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        (
                            "redacteur",
                            models.ForeignKey(
                                db_column="redacteur_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="versions_de_traitement",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "traitement",
                            models.ForeignKey(
                                db_column="traitement_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="versions",
                                to="courrier.traitement",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "version de traitement",
                        "verbose_name_plural": "versions de traitement",
                        "db_table": "traitement_version",
                        "ordering": ["-version"],
                    },
                ),
                migrations.AddConstraint(
                    model_name="traitementversion",
                    constraint=models.UniqueConstraint(
                        fields=("traitement", "version"),
                        name="traitement_version_traitement_id_version_key",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]

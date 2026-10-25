"""
Declare l'etat Django de la table `relance`, qui existe depuis `noyau/0001`.

**Aucune operation en base**, et c'est tout le propos : PostgreSQL est
proprietaire du schema, Django enregistre l'etat ([ADR 003]). La table, son
`CHECK relance_nature_valide` et son index `relance_courrier` sont poses par
`noyau/migrations/sql/0001_socle.sql` depuis l'origine. Ce que cette migration
ajoute, c'est la connaissance qu'en a l'ORM — le jour ou il a fallu **ecrire**
une relance et non plus seulement la compter.

D'ou `SeparateDatabaseAndState` avec `database_operations=[]` : laisser Django
generer son `CREATE TABLE` aurait echoue au premier deploiement et diverge du
schema reel au suivant.

[ADR 003]: ../../docs/architecture/003-django-proprietaire-du-schema.md
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courrier", "0005_pilier_suivi"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Relance",
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
                        ("instance_etape_id", models.BigIntegerField(blank=True, null=True)),
                        ("nature", models.TextField(default="manuelle")),
                        ("motif", models.TextField(blank=True, null=True)),
                        ("emise_le", models.DateTimeField(auto_now_add=True)),
                        ("reponse_le", models.DateTimeField(blank=True, null=True)),
                        (
                            "courrier",
                            models.ForeignKey(
                                blank=True,
                                db_column="courrier_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="relances",
                                to="courrier.courrier",
                            ),
                        ),
                        (
                            "destinataire",
                            models.ForeignKey(
                                db_column="destinataire_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="relances_recues",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "emetteur",
                            models.ForeignKey(
                                blank=True,
                                db_column="emetteur_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="relances_emises",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "relance",
                        "verbose_name_plural": "relances",
                        "db_table": "relance",
                        "ordering": ["-emise_le", "-id"],
                    },
                ),
            ],
        ),
    ]

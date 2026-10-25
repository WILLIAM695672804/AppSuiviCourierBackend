"""
Etat Django des quatre tables du pilier suivi.

**Cette migration ne cree rien.** Les tables naissent de
`noyau/migrations/sql/0023_pilier_suivi.sql`, comme celles du 0003. Une seule
source de verite pour le schema, c'est l'[ADR 003].

Le corps a ete genere par `makemigrations courrier`, puis **enveloppe a la main**
dans `SeparateDatabaseAndState` : sans l'enveloppe, Django tenterait de creer les
tables une seconde fois. Un `makemigrations` relance seul reecrirait un fichier
plat — c'est le meme piege qu'en 0003.

[ADR 003]: ../../docs/architecture/003-django-proprietaire-du-schema.md
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courrier", "0004_traitementversion"),
        ("noyau", "0023_pilier_suivi"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="DemandeDelai",
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
                        ("jours_demandes", models.SmallIntegerField()),
                        ("motif", models.TextField()),
                        ("demandee_le", models.DateTimeField(auto_now_add=True)),
                        ("etat", models.TextField(default="en_attente")),
                        ("decidee_le", models.DateTimeField(blank=True, null=True)),
                        ("reponse", models.TextField(blank=True, null=True)),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="demandes_de_delai",
                                to="courrier.courrier",
                            ),
                        ),
                        (
                            "decidee_par",
                            models.ForeignKey(
                                blank=True,
                                db_column="decidee_par",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="demandes_de_delai_decidees",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "demandeur",
                            models.ForeignKey(
                                db_column="demandeur_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="demandes_de_delai",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "demande de delai",
                        "verbose_name_plural": "demandes de delai",
                        "db_table": "demande_delai",
                        "ordering": ["-demandee_le", "-id"],
                    },
                ),
                migrations.CreateModel(
                    name="NoteTraitement",
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
                        ("texte", models.TextField()),
                        ("privee", models.BooleanField(default=True)),
                        ("publiee_le", models.DateTimeField(auto_now_add=True)),
                        (
                            "auteur",
                            models.ForeignKey(
                                db_column="auteur_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="notes_de_courrier",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="notes_de_traitement",
                                to="courrier.courrier",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "note de traitement",
                        "verbose_name_plural": "notes de traitement",
                        "db_table": "note_traitement",
                        "ordering": ["publiee_le", "id"],
                    },
                ),
                migrations.CreateModel(
                    name="TacheTraitement",
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
                        ("libelle", models.TextField()),
                        ("faite_le", models.DateTimeField(blank=True, null=True)),
                        ("ordre", models.SmallIntegerField(default=0)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="taches_de_traitement",
                                to="courrier.courrier",
                            ),
                        ),
                        (
                            "utilisateur",
                            models.ForeignKey(
                                db_column="utilisateur_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="taches_de_courrier",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "tache de traitement",
                        "verbose_name_plural": "taches de traitement",
                        "db_table": "tache_traitement",
                        "ordering": ["ordre", "id"],
                    },
                ),
                migrations.CreateModel(
                    name="RechercheEnregistree",
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
                        ("libelle", models.TextField()),
                        ("criteres", models.JSONField()),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        (
                            "utilisateur",
                            models.ForeignKey(
                                db_column="utilisateur_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="recherches_enregistrees",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "recherche enregistree",
                        "verbose_name_plural": "recherches enregistrees",
                        "db_table": "recherche_enregistree",
                        "ordering": ["libelle"],
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("utilisateur", "libelle"),
                                name="recherche_libelle_unique_par_agent",
                            )
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]

"""
Etat Django de la decharge, du fil d'observations et du signalement d'ecart.

**Cette migration ne cree rien.** Les deux tables et les quatre colonnes
naissent de `noyau/migrations/sql/0019_fin_pilier_courrier.sql`, comme
`passage_structure` en 0002. Une seule source de verite pour le schema, c'est
l'[ADR 003].

Le contenu ci-dessous a ete ecrit a la main, puis enveloppe dans
`SeparateDatabaseAndState`. Un `makemigrations courrier` relance seul reecrirait
un fichier plat, sans l'enveloppe, et tenterait de creer les tables une seconde
fois.

[ADR 003]: ../../docs/architecture/003-django-proprietaire-du-schema.md
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courrier", "0002_passagestructure"),
        ("noyau", "0019_fin_pilier_courrier"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="affectation",
                    name="accepte_le",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="affectation",
                    name="accepte_par",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="accepte_par",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="affectations_courrier_acceptees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                migrations.AddField(
                    model_name="affectation",
                    name="remis_par",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="affectation",
                    name="reference_cahier",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.CreateModel(
                    name="Observation",
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
                        ("publie_le", models.DateTimeField(auto_now_add=True)),
                        (
                            "auteur",
                            models.ForeignKey(
                                db_column="auteur_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="observations_courrier",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="fil_observations",
                                to="courrier.courrier",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "observation",
                        "verbose_name_plural": "observations",
                        "db_table": "observation_courrier",
                        "ordering": ["publie_le", "id"],
                    },
                ),
                migrations.CreateModel(
                    name="SignalementEcart",
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
                        (
                            "type_ecart",
                            models.TextField(
                                choices=[
                                    ("PIECE_MANQUANTE", "Pièce manquante"),
                                    ("PLI_ENDOMMAGE", "Pli endommagé"),
                                    ("DESTINATAIRE_ERRONE", "Destinataire erroné"),
                                    ("PLI_NON_RECU", "Pli non reçu"),
                                    ("DOUBLON", "Doublon d'enregistrement"),
                                ]
                            ),
                        ),
                        (
                            "gravite",
                            models.TextField(
                                choices=[
                                    ("MINEURE", "Mineure"),
                                    ("NOTABLE", "Notable"),
                                    ("BLOQUANTE", "Bloquante"),
                                ],
                                default="NOTABLE",
                            ),
                        ),
                        ("description", models.TextField()),
                        (
                            "etat",
                            models.TextField(
                                choices=[
                                    ("ouvert", "Ouvert"),
                                    ("pris_en_compte", "Pris en compte"),
                                    ("clos", "Clos"),
                                ],
                                default="ouvert",
                            ),
                        ),
                        ("emis_le", models.DateTimeField(auto_now_add=True)),
                        ("pris_en_compte_le", models.DateTimeField(blank=True, null=True)),
                        ("clos_le", models.DateTimeField(blank=True, null=True)),
                        ("suite_donnee", models.TextField(blank=True, null=True)),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="signalements",
                                to="courrier.courrier",
                            ),
                        ),
                        (
                            "destinataire_structure",
                            models.ForeignKey(
                                db_column="destinataire_structure_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="signalements_recus",
                                to="noyau.structure",
                            ),
                        ),
                        (
                            "emetteur_structure",
                            models.ForeignKey(
                                blank=True,
                                db_column="emetteur_structure_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="signalements_emis",
                                to="noyau.structure",
                            ),
                        ),
                        (
                            "emis_par",
                            models.ForeignKey(
                                db_column="emis_par",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="signalements_emis",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "pris_en_compte_par",
                            models.ForeignKey(
                                blank=True,
                                db_column="pris_en_compte_par",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="signalements_pris_en_compte",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "clos_par",
                            models.ForeignKey(
                                blank=True,
                                db_column="clos_par",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="signalements_clos",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "signalement d'ecart",
                        "verbose_name_plural": "signalements d'ecart",
                        "db_table": "signalement_ecart",
                        "ordering": ["-emis_le", "-id"],
                    },
                ),
            ],
        ),
    ]

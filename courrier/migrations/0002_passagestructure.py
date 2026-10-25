"""
Etat Django de `passage_structure` — le registre du bureau d'ordre de structure.

**Cette migration ne cree rien.** La table naît de
`noyau/migrations/sql/0018_bureau_ordre_structure.sql`, avec son declencheur
d'entree et son rattrapage des cotations deja en base. Ce fichier n'enregistre
que l'etat, comme `0001_initial` l'a fait pour les onze tables du socle : une
seule source de verite pour le schema, c'est l'[ADR 003].

Le contenu ci-dessous a ete produit par `makemigrations courrier` puis enveloppe
a la main dans `SeparateDatabaseAndState`. Un `makemigrations` relance seul
reecrirait un fichier plat, sans l'enveloppe, et tenterait de creer la table une
seconde fois.

[ADR 003]: ../../docs/architecture/003-django-proprietaire-du-schema.md
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courrier", "0001_initial"),
        ("noyau", "0018_bureau_ordre_structure"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="PassageStructure",
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
                        ("entre_le", models.DateTimeField()),
                        ("accuse_le", models.DateTimeField(blank=True, null=True)),
                        ("sorti_le", models.DateTimeField(blank=True, null=True)),
                        (
                            "motif_sortie",
                            models.TextField(
                                blank=True,
                                choices=[
                                    ("reponse", "Réponse transmise"),
                                    ("retour", "Retour au bureau d'ordre central"),
                                    ("transmission", "Transmis à une autre structure"),
                                    ("cloture", "Clôturé"),
                                    ("autre", "Autre"),
                                ],
                                null=True,
                            ),
                        ),
                        ("note_sortie", models.TextField(blank=True, null=True)),
                        (
                            "accuse_par",
                            models.ForeignKey(
                                blank=True,
                                db_column="accuse_par",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="passages_accuses",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "cotation_structure",
                            models.OneToOneField(
                                db_column="cotation_structure_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="passage",
                                to="courrier.cotationstructure",
                            ),
                        ),
                        (
                            "courrier",
                            models.ForeignKey(
                                db_column="courrier_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="passages",
                                to="courrier.courrier",
                            ),
                        ),
                        (
                            "sorti_par",
                            models.ForeignKey(
                                blank=True,
                                db_column="sorti_par",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="passages_sortis",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "structure",
                            models.ForeignKey(
                                db_column="structure_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="passages",
                                to="noyau.structure",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "passage en structure",
                        "verbose_name_plural": "passages en structure",
                        "db_table": "passage_structure",
                        "ordering": ["-entre_le", "-id"],
                    },
                ),
            ],
        ),
    ]

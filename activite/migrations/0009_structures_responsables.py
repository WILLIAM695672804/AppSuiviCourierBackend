"""
L'activite est portee par des structures — ADR 047.

Une table `activite_structure` pour les structures **associees**, et un
`responsable_id` qui cesse d'etre obligatoire. La structure porteuse reste
`paa.structure_id` et ne figure pas dans la nouvelle table.

`SeparateDatabaseAndState` comme pour `0001` et `0008` : le SQL tient le schema
(ADR 003), la partie `state_operations` n'apprend a Django que ce qui existe
deja au moteur.
"""

from pathlib import Path

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0008_avancement_retenu"),
        ("noyau", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ActiviteStructure",
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
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "activite",
                            models.ForeignKey(
                                db_column="activite_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="structures_associees",
                                to="activite.activite",
                            ),
                        ),
                        (
                            "structure",
                            models.ForeignKey(
                                db_column="structure_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="activites_associees",
                                to="noyau.structure",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "activite_structure",
                        "verbose_name": "structure associee a une activite",
                        "verbose_name_plural": "structures associees a une activite",
                    },
                ),
                migrations.AlterField(
                    model_name="activite",
                    name="responsable",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="responsable_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="activites_dont_responsable",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=_lire("0003_structures_responsables.sql"),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

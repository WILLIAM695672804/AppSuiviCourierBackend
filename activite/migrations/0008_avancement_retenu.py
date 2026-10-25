"""
Le taux declare et le taux retenu — ADR 030.

L'exigence : la structure declare son avancement avec sa justification, et
**seule la DSR** peut le recalibrer si les realisations ne sont pas justifiees.
Le schema livre n'avait qu'une colonne pour les deux, ce qui revenait a effacer
le desaccord au moment ou il se produit.

`SeparateDatabaseAndState` comme pour `0001` : c'est le SQL qui tient le schema
(ADR 003), la partie `state_operations` n'apprend a Django que ce qui existe
deja. `avancement_retenu` est une colonne **generee** par le moteur, declaree comme
telle avec `GeneratedField` : un champ ordinaire partirait dans chaque `UPDATE`
et PostgreSQL refuserait de l'ecrire.
"""

from pathlib import Path

from django.db import migrations, models
from django.db.models.functions import Coalesce

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0007_relance_du_calendrier"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="activite",
                    name="avancement_recalibre",
                    field=models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                migrations.AddField(
                    model_name="activite",
                    name="recalibrage_motif",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="activite",
                    name="recalibre_le",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="activite",
                    name="recalibre_par",
                    field=models.BigIntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="activite",
                    name="avancement_retenu",
                    field=models.GeneratedField(
                        db_persist=True,
                        expression=Coalesce("avancement_recalibre", "avancement_calcule"),
                        output_field=models.DecimalField(decimal_places=2, max_digits=5),
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=_lire("0002_avancement_retenu.sql"),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

"""
L'avancement d'une activite est la somme de ses taches — ADR 049.

La tache perd `poids`, `etat` et `date_echeance`, et gagne sa valeur prevue, sa
valeur obtenue, son recalibrage et sa periode au mois. L'activite perd le
motif, la date et l'auteur de son recalibrage : ils vivent desormais sur chaque
tache recalibree.

`SeparateDatabaseAndState` comme pour `0001`, `0008` et `0009` : le SQL tient le
schema et la reprise des donnees (ADR 003), la partie `state_operations`
n'apprend a Django que ce qui existe deja au moteur.
"""

from pathlib import Path

from django.db import migrations, models
from django.db.models.functions import Coalesce

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


def _decimal(**options) -> models.DecimalField:
    return models.DecimalField(decimal_places=2, max_digits=5, **options)


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0009_structures_responsables"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="tache", name="poids"),
                migrations.RemoveField(model_name="tache", name="etat"),
                migrations.RemoveField(model_name="tache", name="date_echeance"),
                migrations.AddField(
                    model_name="tache",
                    name="valeur_prevue",
                    field=_decimal(default=100),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name="tache", name="valeur_obtenue", field=_decimal(default=0)
                ),
                migrations.AddField(
                    model_name="tache",
                    name="valeur_recalibree",
                    field=_decimal(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="tache",
                    name="recalibrage_motif",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="tache",
                    name="recalibre_le",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="tache",
                    name="recalibre_par",
                    field=models.BigIntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="tache",
                    name="valeur_retenue",
                    field=models.GeneratedField(
                        db_persist=True,
                        expression=Coalesce("valeur_recalibree", "valeur_obtenue"),
                        output_field=_decimal(),
                    ),
                ),
                migrations.AddField(
                    model_name="tache",
                    name="date_debut",
                    field=models.DateField(default="2026-01-01"),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name="tache",
                    name="date_fin",
                    field=models.DateField(default="2026-12-31"),
                    preserve_default=False,
                ),
                migrations.RemoveField(model_name="activite", name="recalibrage_motif"),
                migrations.RemoveField(model_name="activite", name="recalibre_le"),
                migrations.RemoveField(model_name="activite", name="recalibre_par"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=_lire("0004_avancement_par_taches.sql"),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

"""
Le premier mois de l'exercice — A52.

Une seule regle, en **hypothese** : aucun document fourni ne dit quand
l'exercice budgetaire du Port s'ouvre. Elle vaut 1 — l'annee civile — et le SQL
dit ce qu'elle coute si elle est mal posee.

`RunSQL` et non `RunPython`, pour la raison de `0004` : un parametre est une
donnee de reference, et les semis de reference du depot sont ecrits en SQL
depuis `0002_adaptations.sql`.

Pas de `reverse_sql` qui supprime : une valeur tranchee par une direction ne
doit pas disparaitre parce qu'on defait une migration.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0011_notifications"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0012_parametre_exercice.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

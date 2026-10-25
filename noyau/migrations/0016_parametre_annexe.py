"""
Le seuil de bascule en annexe des tableaux de la note de synthese — A58.

`RunSQL` et non `RunPython`, pour la raison de `0004` et `0006` : un parametre
est une donnee de reference, et les semis de reference du depot sont ecrits en
SQL. Les melanger obligerait a chercher dans deux endroits ce qui peuple la
table.

Pas de `reverse_sql` qui supprime : une valeur corrigee par la Direction
generale ne doit pas disparaitre parce qu'on defait une migration.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0015_recherche_correspondant"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0016_parametre_annexe.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

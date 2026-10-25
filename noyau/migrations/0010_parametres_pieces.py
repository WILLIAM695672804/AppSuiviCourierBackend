"""
Ce qu'une piece jointe a le droit d'etre — A49 et A50.

Deux hypotheses : le plafond de taille et la liste des extensions acceptees.
Le detail, et ce que chacune coute si elle est mal posee, est dans le SQL.

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
        ("noyau", "0009_affectation_poste"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0010_parametres_pieces.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

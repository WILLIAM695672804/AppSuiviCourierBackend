"""
Les trois reglages sans source du pilier dossiers — A37 et A38.

`RunSQL` et non `RunPython`, pour la raison de `0004` : un parametre est une
donnee de reference, et les semis de reference du depot sont ecrits en SQL
depuis `0002_adaptations.sql`.

Pas de `reverse_sql` qui supprime : une valeur corrigee par la Division du
Suivi et de la Relance ne doit pas disparaitre parce qu'on defait une
migration.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0006_parametres_exploitation_pilotage"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0007_parametres_dossier.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

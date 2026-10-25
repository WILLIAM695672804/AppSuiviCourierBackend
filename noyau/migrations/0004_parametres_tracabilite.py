"""
Le seuil de volume anormal du journal des acces — A23.

`RunSQL` et non `RunPython` : le parametre est une **donnee de reference**, au
meme titre que les quatre du pilier activites, et les semis de reference du
depot sont ecrits en SQL depuis `0002_adaptations.sql`. Les melanger — les uns
en Python, les autres en SQL — obligerait a chercher dans deux endroits ce qui
peuple la table.

Pas de `reverse_sql` qui supprime : un parametre corrige par un auditeur ne doit
pas disparaitre parce qu'on a defait une migration. Le retour arriere le laisse
en place, ce qui est sans effet — plus personne ne le lit.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0003_colonnes_de_gouvernance_de_l_organigramme"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0004_parametres_tracabilite.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

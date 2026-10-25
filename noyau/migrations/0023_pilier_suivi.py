"""
Le schema du pilier suivi : taches, notes, demandes de delai, recherches.

Le SQL voisin porte tout — c'est l'[ADR 003]. Cette migration ne declare aucun
etat Django : les quatre tables relevent du domaine courrier, et leur etat est
declare dans `courrier/migrations/0005`. Le SQL se pose ici parce que le schema
du socle se pose d'un bloc, comme en 0018 et 0019.

`reverse_sql` en `noop` : une note prise, un delai demande et la reponse qui lui
a ete faite sont des pieces du dossier. Une migration inverse qui les
supprimerait effacerait ce que l'agent avait ecrit et ce que son responsable
avait decide.

[ADR 003]: ../docs/architecture/003-django-proprietaire-du-schema.md
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


class Migration(migrations.Migration):
    dependencies = [("noyau", "0022_parametres_suivi_relance")]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0023_pilier_suivi.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

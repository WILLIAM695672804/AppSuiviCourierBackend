"""
L'acceptation par l'agent, le fil d'observations, le signalement d'ecart.

Le SQL voisin porte tout le schema — c'est l'[ADR 003]. Cette migration ne
declare **aucun etat** : les trois objets qu'elle cree (deux tables et quatre
colonnes) relevent tous du domaine courrier, et leur etat est declare dans
`courrier/migrations/0003`. Le SQL, lui, se pose ici parce que le schema du
socle se pose d'un bloc, comme en 0018.

`reverse_sql` en `noop`, pour la meme raison qu'en 0018 : une decharge signee et
un ecart signale sont des pieces du dossier. Une migration inverse qui les
supprimerait effacerait la preuve de ce qui a ete recu, par qui, et de ce que la
structure en a dit.

[ADR 003]: ../docs/architecture/003-django-proprietaire-du-schema.md
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0018_bureau_ordre_structure"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0019_fin_pilier_courrier.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

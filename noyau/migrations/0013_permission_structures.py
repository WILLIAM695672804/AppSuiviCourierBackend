"""
`ADM_STR` disparait : les structures reviennent a `ADM_ORG` — ADR 021.

Deux permissions se partageaient l'organigramme, et la coupure ne tenait pas a
l'usage : la DSR creait des structures sans pouvoir nommer leur responsable,
l'administrateur nommait dans des structures qu'il ne pouvait pas creer.

`RunSQL` et non `RunPython` : les droits sont des donnees de reference, semees
en SQL depuis `0002_adaptations.sql`, et le fichier dit pourquoi mieux qu'un
script Python ne le ferait.

`reverse_sql` en `noop` : redonner la permission a la DSR se decide, cela ne se
defait pas par une commande. La remettre demanderait de la recreer, de la
rattacher, et de rouvrir l'ecran — c'est une migration, pas un retour arriere.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0012_parametre_exercice"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0013_permission_structures.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

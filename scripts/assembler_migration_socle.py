#!/usr/bin/env python
"""
Reassemble la migration 0001 du noyau.

**A n'utiliser que pour regenerer 0001**, ce qui n'arrive qu'avant la premiere
mise en production. Passe ce jalon, l'etat est figé et toute evolution passe par
une migration 0002, 0003, etc.

Pourquoi un script plutot qu'un fichier ecrit a la main : la partie « etat » de
la migration compte plus de trois cents lignes de `CreateModel` que Django sait
generer et qu'un humain recopierait avec des fautes. Le script fait donc :

    1. `makemigrations noyau`, qui produit un fichier plat ;
    2. il enveloppe les operations generees dans `SeparateDatabaseAndState`,
       pour qu'elles n'enregistrent que l'etat sans creer les tables ;
    3. il prefixe les deux `RunSQL` qui creent reellement le schema.

Usage :

    ./.venv/bin/python scripts/assembler_migration_socle.py

Le script refuse de s'executer si la migration existe deja et porte deja son
entete : ecraser une migration appliquee est le meilleur moyen de perdre une
base de production.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MIGRATION = RACINE / "noyau" / "migrations" / "0001_initial.py"
MARQUEUR = "SeparateDatabaseAndState"

ENTETE = '''"""
Socle du schema.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_socle.sql`, copie fidele du
script livre avec le modele de donnees, puis adaptees par
`sql/0002_adaptations.sql`.

La raison est que le schema utilise des constructions que l'ORM ne sait pas
exprimer et qu'il serait absurde de perdre : partitionnement declaratif par
annee sur `evenement` et `champ_historique`, partitionnement mensuel sur
`journal_acces`, contrainte d'exclusion GiST sur le rattachement a une session,
index BRIN, index partiels, declencheurs d'historisation et de numerotation,
configuration de recherche plein texte sans accents.

`SeparateDatabaseAndState` sert donc a **enregistrer l'etat** sans rien creer :
Django apprend l'existence des modeles, les tables existent deja. A partir de la
migration 0002, Django reprend la main normalement — c'est la decision 003 :
une seule source de verite pour le schema.

Ce fichier est assemble par `scripts/assembler_migration_socle.py`. Un
`makemigrations` lance seul regenererait un fichier plat, sans le
`SeparateDatabaseAndState` ni les deux `RunSQL`, et la base serait creee deux
fois.
"""

import uuid
from pathlib import Path

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        # 1. Le schema livre, a l'identique. Irreversible : on ne defait pas la
        #    creation d'une base, on la recree.
        migrations.RunSQL(sql=_lire("0001_socle.sql"), reverse_sql=migrations.RunSQL.noop),
        # 2. Les adaptations du backend, isolees pour rester visibles au diff.
        migrations.RunSQL(sql=_lire("0002_adaptations.sql"), reverse_sql=migrations.RunSQL.noop),
        # 3. Enregistrement de l'etat seul : aucune table n'est creee ici.
        migrations.SeparateDatabaseAndState(
            state_operations=[
'''


def main() -> int:
    if MIGRATION.exists() and MARQUEUR in MIGRATION.read_text(encoding="utf8"):
        print(
            "La migration 0001 est deja assemblee. Supprimez-la explicitement "
            "si vous voulez vraiment la refaire — et verifiez d'abord qu'aucune "
            "base ne l'a appliquee."
        )
        return 1

    MIGRATION.unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "noyau"],
        cwd=RACINE,
        check=True,
    )

    genere = MIGRATION.read_text(encoding="utf8")
    debut = genere.index("    operations = [\n") + len("    operations = [\n")
    corps = genere[debut:].rstrip()
    if not corps.endswith("]"):
        raise SystemExit("Format inattendu de la migration generee.")
    corps = textwrap.indent(textwrap.dedent(corps[:-1].rstrip()), " " * 16)

    MIGRATION.write_text(ENTETE + corps + "\n            ]\n        ),\n    ]\n", encoding="utf8")
    print(f"Migration assemblee : {MIGRATION.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

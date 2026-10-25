#!/usr/bin/env python
"""
Assemble la migration 0001 d'un pilier.

Meme mecanique que `assembler_migration_socle.py`, mais pour les piliers, qui
en ont tous besoin : activite, courrier, gouvernance, performance. Le socle
garde son script a lui — il applique deux fichiers SQL et son ADR le nomme.

Ce que fait le script :

    1. `makemigrations <pilier>`, qui produit un fichier plat ;
    2. il enveloppe les operations generees dans `SeparateDatabaseAndState`,
       pour qu'elles n'enregistrent que l'etat sans creer les tables ;
    3. il prefixe le `RunSQL` qui cree reellement le schema.

Pourquoi un script plutot qu'un fichier ecrit a la main : la partie « etat »
compte plusieurs centaines de lignes de `CreateModel` que Django sait generer
et qu'un humain recopierait avec des fautes.

Usage :

    ./.venv/bin/python scripts/assembler_migration_pilier.py activite

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
MARQUEUR = "SeparateDatabaseAndState"

#: Ce dont chaque pilier depend, en plus du socle. La gouvernance renomme une
#: table livree par le pilier activites : elle doit passer apres lui.
DEPENDANCES: dict[str, list[tuple[str, str]]] = {
    "gouvernance": [("activite", "0004_parametres_traitements")],
}

#: Un pilier par entree : le fichier SQL livre, et le texte d'entete qui dit au
#: relecteur pourquoi cette migration ne se regenere pas seule.
PILIERS: dict[str, tuple[str, str]] = {
    "activite": (
        "0001_activite.sql",
        '''"""
Schema du pilier activites.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_activite.sql`, copie fidele du
script livre avec le modele de donnees — seules les trois lignes propres a psql
(`ON_ERROR_STOP`, `BEGIN`, `COMMIT`) en ont ete retirees, Django ouvrant
lui-meme la transaction.

La raison est la meme qu'au socle : le schema porte des constructions que l'ORM
ne sait pas exprimer et qu'il serait absurde de perdre. Ici, cinq declencheurs
qui tiennent des regles metier (code de l'activite sous verrou de ligne,
avancement pondere, refus d'avancement sur activite suspendue, coherence de
l'etat de suspension, historisation des champs), une vue `v_activite_etat`, des
index partiels, un index unique partiel garantissant une seule suspension
ouverte, et l'extension de `relance` a une seconde cible.

`SeparateDatabaseAndState` sert donc a **enregistrer l'etat** sans rien creer :
Django apprend l'existence des modeles, les tables existent deja. C'est la
decision 003 — une seule source de verite pour le schema.

La dependance a `noyau.0001_initial` n'est pas decorative : ce fichier
reference `structure`, `utilisateur` et `piece_jointe`, et modifie `relance`.

Ce fichier est assemble par `scripts/assembler_migration_pilier.py`. Un
`makemigrations` lance seul regenererait un fichier plat, sans le
`SeparateDatabaseAndState` ni le `RunSQL`, et les tables seraient creees deux
fois.
"""
''',
    ),
    "gouvernance": (
        "0001_gouvernance.sql",
        '''"""
Schema du pilier gouvernance.

**Cette migration ne doit pas etre regeneree a la main.** Les tables ne sont pas
creees par Django : elles le sont par `sql/0001_gouvernance.sql`.

Elle porte le renommage decide par l'ADR 006 : `decision_reunion`, livree avec
le pilier activites pour le §19, devient `engagement` et accueille les trois
origines — decision d'instance, prescription de filiale, recommandation externe.
D'ou la dependance a `activite.0004` : la table doit exister, et le pilier
activites doit avoir fini d'ecrire dessus, avant qu'elle ne change de nom.

Le retrait du modele `DecisionReunion` de l'etat d'`activite` suit dans
`activite.0005`, qui depend de celle-ci. L'ordre est impose : renommer la table
avant que Django n'apprenne que le modele a demenage.

Ce que l'ORM ne saurait pas exprimer et qu'il serait absurde de perdre : deux
declencheurs (reference sous verrou d'avis, avancement moyen des structures
chargees), une contrainte d'exclusion GiST sur le chevauchement des absences,
la vue `v_engagement_etat`, des index partiels et une colonne generee.

Ce fichier est assemble par `scripts/assembler_migration_pilier.py`.
"""
''',
    ),
}

PRELUDE = """
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

    dependencies = [
        ("noyau", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
_DEPENDANCES    ]

    operations = [
        # 1. Le schema livre, a l'identique. Irreversible : on ne defait pas la
        #    creation d'un schema, on la recree.
        migrations.RunSQL(sql=_lire(_FICHIER_SQL), reverse_sql=migrations.RunSQL.noop),
        # 2. Enregistrement de l'etat seul : aucune table n'est creee ici.
        migrations.SeparateDatabaseAndState(
            state_operations=[
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in PILIERS:
        print(f"Usage : {argv[0]} <{'|'.join(PILIERS)}>")
        return 2

    pilier = argv[1]
    fichier_sql, entete = PILIERS[pilier]
    migration = RACINE / pilier / "migrations" / "0001_initial.py"

    if migration.exists() and MARQUEUR in migration.read_text(encoding="utf8"):
        print(
            f"La migration 0001 de « {pilier} » est deja assemblee. Supprimez-la "
            "explicitement si vous voulez vraiment la refaire — et verifiez "
            "d'abord qu'aucune base ne l'a appliquee."
        )
        return 1

    migration.unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, "manage.py", "makemigrations", pilier],
        cwd=RACINE,
        check=True,
    )

    genere = migration.read_text(encoding="utf8")
    debut = genere.index("    operations = [\n") + len("    operations = [\n")
    corps = genere[debut:].rstrip()
    if not corps.endswith("]"):
        raise SystemExit("Format inattendu de la migration generee.")
    corps = textwrap.indent(textwrap.dedent(corps[:-1].rstrip()), " " * 16)

    supplement = "".join(
        f'        ("{app}", "{nom}"),\n' for app, nom in DEPENDANCES.get(pilier, [])
    )
    prelude = PRELUDE.replace("_FICHIER_SQL", f'"{fichier_sql}"').replace(
        "_DEPENDANCES", supplement
    )
    migration.write_text(
        entete + prelude + corps + "\n            ]\n        ),\n    ]\n",
        encoding="utf8",
    )
    print(f"Migration assemblee : {migration.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

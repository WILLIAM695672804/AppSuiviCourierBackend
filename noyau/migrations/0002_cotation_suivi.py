"""
La cotation pour suivi entre au modele — A7.

**Pourquoi une migration SQL et non un modele Django.** L'ADR 003 dit qu'a
partir de la migration 0002, Django reprend la main. C'est vrai des qu'un modele
couvre la table ; ici, `cotation` n'en a aucun — le pilier courrier n'est pas
commence — et Django ne sait pas declarer une cle etrangere vers une table qu'il
ignore.

Ecrire un modele `CotationSuivi` maintenant obligerait a le loger quelque part
dans le noyau, alors que sa place est le pilier courrier. Il y sera ecrit, avec
les autres, en `SeparateDatabaseAndState` : la table existera deja, exactement
comme pour le socle.

**Pourquoi maintenant plutot qu'avec le pilier courrier.** Parce que c'est une
porte d'acces aux donnees. L'ajouter apres coup demanderait de reprendre chaque
route du pilier — c'est ce que A7 annoncait comme cout eleve, et la seule facon
de ne pas le payer est d'ecrire la table avant les routes qui devront la lire.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0003_cotation_suivi.sql"),
            reverse_sql="DROP TABLE IF EXISTS cotation_suivi;",
        ),
    ]

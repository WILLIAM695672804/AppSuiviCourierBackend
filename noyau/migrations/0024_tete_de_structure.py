"""
La tete de structure, et le poste qui la dirige.

Le SQL voisin porte tout le schema — c'est l'[ADR 003] : PostgreSQL est
proprietaire, Django enregistre l'etat. Deux colonnes nouvelles,
`structure.tete_id` et `poste.est_responsable`, plus la fonction, le
declencheur et les index qui tiennent la premiere a jour.

`SeparateDatabaseAndState` autour des operations d'etat : les colonnes
existent deja, creees par le `RunSQL` qui precede. Sans l'enveloppe, Django
emettrait un second `ALTER TABLE ... ADD COLUMN`, qui echouerait — et surtout
il ne saurait rien du declencheur, qu'aucune operation d'etat ne peut decrire.

`reverse_sql` en `noop` : `tete_id` se recalcule, mais `est_responsable` non.
Qui dirige une structure est une designation, saisie par un administrateur et
reconstituable par personne. Une migration inverse qui supprimerait la colonne
effacerait ces designations sans laisser de trace — revenir en arriere se
decide, se prepare, et s'ecrit dans une migration a soi.

[ADR 003]: ../docs/architecture/003-django-proprietaire-du-schema.md
"""

from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


class Migration(migrations.Migration):
    dependencies = [("noyau", "0023_pilier_suivi")]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0024_tete_de_structure.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="structure",
                    name="tete",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="tete_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rattachees",
                        to="noyau.structure",
                    ),
                ),
                migrations.AddField(
                    model_name="poste",
                    name="est_responsable",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]

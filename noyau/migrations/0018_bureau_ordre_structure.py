"""
Le bureau d'ordre de structure, le cloisonnement, et le routage direct.

Le SQL voisin porte tout le schema — c'est l'[ADR 003] : PostgreSQL est
proprietaire, Django enregistre l'etat. Trois objets nouveaux, et un seul est
declare ici : `regle_routage`, plus la colonne `evenement.structure_id`.
`passage_structure` releve du domaine courrier, et son etat est declare dans
`courrier/migrations/0002` — la table naît pourtant du meme fichier SQL, parce
qu'elle depend de `cotation_structure` et que le schema se pose d'un bloc.

`SeparateDatabaseAndState` autour des operations d'etat : les objets existent
deja, crees par le `RunSQL` qui precede. Sans l'enveloppe, Django emettrait un
`CREATE TABLE regle_routage` une seconde fois.

`reverse_sql` en `noop` : le registre d'entree et de sortie d'une structure est
une piece du dossier, au meme titre que le journal. Une migration inverse qui le
supprimerait effacerait la preuve de ce qui a ete recu et quand — revenir en
arriere se decide, se prepare, et s'ecrit dans une migration a soi.

[ADR 003]: ../docs/architecture/003-django-proprietaire-du-schema.md
"""

from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


def _lire(nom: str) -> str:
    return (SQL / nom).read_text(encoding="utf8")


class Migration(migrations.Migration):
    dependencies = [
        ("noyau", "0017_organigramme_reel"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_lire("0018_bureau_ordre_structure.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # `Evenement` est `managed = False` : Django ne touche pas la
                # table. L'operation accorde l'etat de l'ORM au schema, sans quoi
                # le prochain `makemigrations` proposerait de le refaire.
                migrations.AddField(
                    model_name="evenement",
                    name="structure_id",
                    field=models.BigIntegerField(blank=True, null=True),
                ),
                migrations.CreateModel(
                    name="RegleRoutage",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("code", models.TextField(unique=True)),
                        ("libelle", models.TextField()),
                        (
                            "sens",
                            models.TextField(
                                blank=True,
                                choices=[
                                    ("arrive", "Arrivée"),
                                    ("depart", "Départ"),
                                    ("interne", "Interne"),
                                ],
                                null=True,
                            ),
                        ),
                        ("priorite", models.SmallIntegerField(default=100)),
                        ("actif", models.BooleanField(default=True)),
                        (
                            "statut",
                            models.TextField(
                                choices=[("acte", "Acté"), ("hypothese", "Hypothèse")],
                                default="hypothese",
                            ),
                        ),
                        ("source", models.TextField(blank=True, null=True)),
                        ("cree_le", models.DateTimeField(auto_now_add=True)),
                        ("cree_par", models.BigIntegerField(blank=True, null=True)),
                        ("modifie_le", models.DateTimeField(blank=True, null=True)),
                        ("modifie_par", models.BigIntegerField(blank=True, null=True)),
                        ("invalide_le", models.DateTimeField(blank=True, null=True)),
                        ("invalide_par", models.BigIntegerField(blank=True, null=True)),
                        (
                            "correspondant",
                            models.ForeignKey(
                                blank=True,
                                db_column="correspondant_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.correspondant",
                            ),
                        ),
                        (
                            "mention_type",
                            models.ForeignKey(
                                blank=True,
                                db_column="mention_type_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.mentiontype",
                            ),
                        ),
                        (
                            "nature",
                            models.ForeignKey(
                                blank=True,
                                db_column="nature_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                to="noyau.nature",
                            ),
                        ),
                        (
                            "structure",
                            models.ForeignKey(
                                db_column="structure_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="routages",
                                to="noyau.structure",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "regle de routage direct",
                        "verbose_name_plural": "regles de routage direct",
                        "db_table": "regle_routage",
                        "ordering": ["priorite", "id"],
                    },
                ),
            ],
        ),
    ]

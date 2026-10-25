"""
`pilote` est declaree comme colonne generee.

La colonne existe deja en base — `GENERATED ALWAYS AS (rang = 1) STORED`, posee
par `sql/0001_gouvernance.sql`. Ce qui change ici est **ce que Django en sait** :
declaree en `BooleanField` ordinaire, il l'envoyait dans chaque `INSERT` et
PostgreSQL refusait :

    cannot insert a non-DEFAULT value into column "pilote"

`SeparateDatabaseAndState` parce que la base n'a rien a apprendre : sans lui,
Django tenterait de recreer une colonne qui existe deja, dans sa forme a lui.

Le meme piege attend `cotation_structure.chef_de_file`, generee elle aussi et
non encore couverte par un modele. Voir docs/pieges.md.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gouvernance", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[

            migrations.AlterField(
                model_name='engagementstructure',
                name='pilote',
                field=models.GeneratedField(db_persist=True, expression=models.Q(('rang', 1)), output_field=models.BooleanField()),
            ),
            ]
        ),
    ]

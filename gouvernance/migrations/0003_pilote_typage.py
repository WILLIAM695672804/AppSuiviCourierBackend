"""
`pilote` : l'expression prend son enveloppe de type.

Rien ne change en base ni au comportement. `Q(rang=1)` et
`ExpressionWrapper(Q(rang=1), …)` produisent le meme SQL ; seul le second est
une `Expression` au sens du verificateur de types, qui refusait le premier a
juste titre.

`SeparateDatabaseAndState`, donc : la colonne generee existe deja et Django n'a
rien a lui faire.
"""

from django.db import migrations, models
from django.db.models import ExpressionWrapper, Q


class Migration(migrations.Migration):
    dependencies = [
        ("gouvernance", "0002_pilote_genere"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[

            migrations.AlterField(
                model_name='engagementstructure',
                name='pilote',
                field=models.GeneratedField(db_persist=True, expression=models.ExpressionWrapper(models.Q(('rang', 1)), output_field=models.BooleanField()), output_field=models.BooleanField()),
            ),
            ]
        ),
    ]

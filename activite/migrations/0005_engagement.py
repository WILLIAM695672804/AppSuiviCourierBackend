"""
`DecisionReunion` demenage vers la gouvernance — ADR 006.

La table `decision_reunion` a ete renommee `engagement` par
`gouvernance.0001`, et le modele qui la couvre vit desormais dans
`gouvernance/modeles.py` sous le nom `Engagement`. Cette migration ne fait
qu'enregistrer le depart : **aucune table n'est touchee ici**, le SQL a deja
tout fait.

L'ordre importe. Renommer la table d'abord, apprendre a Django que le modele a
change d'application ensuite — d'ou la dependance a `gouvernance.0001`.

Les trois cles etrangeres qui la visaient (`instruction_activite`,
`decision_effet`, `activite_suspension`) pointent maintenant vers
`gouvernance.Engagement`. Elles gardent leur nom de champ `decision_reunion` et
leur colonne `decision_reunion_id` : c'est bien une decision de reunion **dans
ce contexte** — le §19 parle des decisions issues des reunions de coordination —
et renommer la colonne aurait casse le SQL livre pour un gain nul.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activite", "0004_parametres_traitements"),
        ("gouvernance", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="instructionactivite",
                    name="decision_reunion",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="decision_reunion_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="gouvernance.engagement",
                    ),
                ),
                migrations.AlterField(
                    model_name="decisioneffet",
                    name="decision_reunion",
                    field=models.ForeignKey(
                        db_column="decision_reunion_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="effets",
                        to="gouvernance.engagement",
                    ),
                ),
                migrations.AlterField(
                    model_name="activitesuspension",
                    name="decision_reunion",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="decision_reunion_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="gouvernance.engagement",
                    ),
                ),
                migrations.DeleteModel(name="DecisionReunion"),
            ]
        ),
    ]

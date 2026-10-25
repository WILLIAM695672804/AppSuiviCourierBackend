"""
Etat Django de la table `jour_ferie`.

**Aucune table n'est creee ici.** `jour_ferie` existe depuis
`sql/0001_socle.sql` ; elle n'avait simplement aucun modele, faute d'usage : le
calcul en jours ouvres n'etait requis par aucun pilier livre. Il l'est par le
courrier — l'echeance affichee a l'enregistrement se compte en jours ouvres — et
`noyau.calendrier.ajouter_jours_ouvres` la lit.

`SeparateDatabaseAndState` avec un `database_operations` vide, comme
`noyau/0001_initial` et `courrier/0001_initial` : le schema a une seule source de
verite (ADR 003), et la creer une seconde fois echouerait.

**Aucune donnee n'est semee.** Le socle previent que la table « n'existe dans
aucun document source : a administrer ». Un calendrier de feries invente
decalerait toutes les echeances de courrier sans que rien ne le signale, alors
qu'une table vide se voit dans l'onglet qui l'administre. Le calendrier connait
donc les week-ends, et rien d'autre, jusqu'a ce que l'institution declare ses
jours feries.

Ecrite a la main, comme toutes les migrations de `noyau` : voir l'entete de
`0001_initial`.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("noyau", "0013_permission_structures")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="JourFerie",
                    fields=[
                        ("date_ferie", models.DateField(primary_key=True, serialize=False)),
                        ("libelle", models.TextField()),
                    ],
                    options={
                        "verbose_name": "jour ferie",
                        "verbose_name_plural": "jours feries",
                        "db_table": "jour_ferie",
                        "ordering": ["date_ferie"],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]

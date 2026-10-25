"""
Etat Django de `correspondant.recherche`.

**La colonne existe depuis le socle**, et son declencheur aussi
(`correspondant_recherche_maj`, corrige des le script d'origine : le vecteur
etait declare avec son index GIN mais n'etait alimente par rien). Ce qui
manquait est l'etat : le modele ne declarait pas la colonne, donc l'ORM ne
pouvait pas chercher dessus.

Pourquoi la declarer maintenant. `GET /referentiels/correspondants` cherche
l'expediteur au fil de la frappe, avec la configuration `fr_unaccent` du socle :
« Impots » doit trouver « Impôts ». Chercher par `icontains` a la place aurait
rendu la recherche sensible aux accents — donc conduit l'agent a creer un
doublon plutot qu'a retrouver l'entree existante, ce qui est exactement ce que le
referentiel des correspondants existe pour eviter.

`SeparateDatabaseAndState` avec `database_operations` vide : la colonne est deja
la, l'ajouter une seconde fois echouerait (ADR 003).
"""

import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("noyau", "0014_jour_ferie")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="correspondant",
                    name="recherche",
                    field=django.contrib.postgres.search.SearchVectorField(
                        editable=False, null=True
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]

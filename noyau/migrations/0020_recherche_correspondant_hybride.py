"""
Recherche hybride du carnet d'adresses : sigle, trigrammes, classement.

**Le probleme, pose une fois.** Le referentiel des correspondants existe pour
une seule raison : qu'un meme ministere ne finisse pas ecrit de six manieres.
Il ne la sert que si l'agent **retrouve** l'entree existante. Trois manques l'en
empechaient — le sigle absent du schema, le plein texte qui ne pardonne aucune
faute de frappe, et `pg_trgm` installee mais servie par aucun index.

Ce que la migration pose :

 1. `correspondant.sigle` — « MINFI », « APN ». Ce que l'agent tape en premier,
    parce que c'est ce qui est imprime sur l'en-tete de la lettre qu'il tient.
 2. `correspondant.cible_recherche`, colonne **generee**, et son index GIN
    trigramme. Generee et non calculee a la lecture : un index d'expression sur
    une chaine recomposee a chaque ligne ne serait pas utilise.
 3. `sans_accent()`, enveloppe IMMUTABLE de `unaccent` — la forme a un argument
    est STABLE et n'est donc pas indexable.
 4. Le sigle dans le vecteur plein texte, au poids A.

Le SQL porte le schema, Django enregistre l'etat ([ADR 003]). `AddField` sous
`SeparateDatabaseAndState` : les colonnes existent deja quand l'etat est pose.

`cible_recherche` n'est pas declaree au modele : rien en Python ne la lit. Elle
sert la recherche, qui est ecrite en SQL — et une colonne generee que l'ORM
croirait modifiable serait un piege, pas un service.

`reverse_sql` en `noop` : revenir en arriere supprimerait un sigle saisi par le
metier. Cela se decide et s'ecrit dans une migration a soi.

[ADR 003]: ../docs/architecture/003-django-proprietaire-du-schema.md
"""

from pathlib import Path

from django.db import migrations, models

SQL = Path(__file__).parent / "sql"


class Migration(migrations.Migration):
    dependencies = [("noyau", "0019_fin_pilier_courrier")]

    operations = [
        migrations.RunSQL(
            sql=(SQL / "0020_recherche_correspondant_hybride.sql").read_text(encoding="utf8"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="correspondant",
                    name="sigle",
                    field=models.TextField(blank=True, null=True),
                ),
            ],
            database_operations=[],
        ),
    ]

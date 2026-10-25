# Faire évoluer le schéma

Le schéma n'a pas été créé par Django : il vient du SQL livré, et la migration
`0001` ne fait qu'en déclarer l'état
([ADR 003](../architecture/003-django-proprietaire-du-schema.md)).

**À partir de `0002`, Django reprend la main normalement.** Le jalon est net :
avant, la base fait foi ; après, les migrations.

## Le cas normal : ajouter une colonne, une table, un index

Rien de particulier.

```bash
# 1. modifier le modèle
# 2.
./.venv/bin/python manage.py makemigrations activite
# 3. LIRE la migration générée
# 4.
make migrer
make test
```

L'étape 3 n'est pas de la politesse. Django prend parfois un renommage pour une
suppression suivie d'une création — et c'est une perte de données silencieuse.

## Ce qui demande du SQL à la main

Le partitionnement, les contraintes d'exclusion GiST, les déclencheurs, les
index BRIN et les configurations de recherche plein texte ne sont pas exprimés
par l'ORM. Ils s'ajoutent par `RunSQL`, dans une migration ordinaire :

```python
operations = [
    migrations.AddField(...),
    migrations.RunSQL(
        sql="CREATE INDEX ... USING brin (survenu_le);",
        reverse_sql="DROP INDEX ...;",
    ),
]
```

Écrivez le `reverse_sql`. Une migration qu'on ne peut pas défaire transforme un
retour arrière en restauration de sauvegarde.

## Ce qu'il ne faut jamais faire

**Relancer `makemigrations noyau` en espérant régénérer `0001`.** Vous
obtiendriez un fichier plat, sans `SeparateDatabaseAndState` ni les deux
`RunSQL`, qui essaierait de créer des tables existantes.

Régénérer `0001` n'a de sens qu'avant la première mise en production, par
`scripts/assembler_migration_socle.py` — lequel refuse de s'exécuter si la
migration porte déjà son en-tête.

**Modifier une migration déjà appliquée ailleurs.** On en écrit une nouvelle.

## Le garde-fou permanent

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run   # No changes detected
```

Cette commande doit rester silencieuse **à tout moment**. Si elle propose une
migration, un modèle et le schéma ne disent plus la même chose. C'est le signal
le moins cher qui existe ; ne le rendez pas vert en générant la migration
proposée sans l'avoir lue.

## Les particularités qui vont vous surprendre

**Les défauts serveur sont doublés en Python.** Django envoie toutes les
colonnes dans son `INSERT`, y compris à `NULL` : un `DEFAULT gen_random_uuid()`
ne s'applique jamais. D'où `default=uuid.uuid4` sur les modèles concernés. À
refaire sur tout nouveau modèle portant un défaut serveur.

**Les tables de liaison n'ont pas d'`id`.**
`pk = models.CompositePrimaryKey("profil_id", "permission_id")` (Django ≥ 5.2),
sinon `column …id does not exist` à la première insertion.

**Les tables partitionnées sont `managed = False`.** Django ne doit pas essayer
de les recréer, en test notamment. Les écritures y passent par du SQL direct
(`noyau/journal/service.py`).

## Documenter le changement

Une colonne se commente **dans la base** — c'est là que le dictionnaire de
données se lit :

```python
migrations.RunSQL(
    "COMMENT ON COLUMN activite.avancement_attendu IS "
    "'Avancement théorique à la date du jour. Règle non arbitrée : voir A1.';",
    reverse_sql=migrations.RunSQL.noop,
)
```

Le dictionnaire s'extrait ensuite sans rien recopier : voir le
[runbook](../exploitation/runbook.md).

Si le changement modifie une règle de gestion, il modifie aussi
[`regles/`](../regles/) — dans le même diff.

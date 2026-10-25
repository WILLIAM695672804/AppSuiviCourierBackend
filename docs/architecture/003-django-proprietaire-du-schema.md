# 003 — PostgreSQL propriétaire du schéma, Django suiveur

**Statut :** acceptée · **Date :** 11 août 2026

## Contexte

Le modèle de données a été livré **avant** le backend, sous forme d'un script
SQL complet (`init_base.sql`, à la racine du dépôt) accompagné de deux documents
de conception. Ce script n'est pas une esquisse : il utilise des constructions
que l'ORM ne sait pas exprimer, et qui répondent à des exigences précises.

- partitionnement déclaratif par année sur `evenement` et `champ_historique`,
  mensuel sur `journal_acces` — volumétrie et purge de la traçabilité ;
- contrainte d'exclusion `EXCLUDE USING gist` sur le rattachement à une session ;
- index BRIN sur les colonnes temporelles, index partiels sur les états ;
- déclencheurs d'historisation des champs et de numérotation ;
- recherche plein texte `TSVECTOR` avec une configuration `fr_unaccent`.

Laisser Django générer le schéma aurait signifié perdre tout cela, ou le
réintroduire par des `RunSQL` en aval — en acceptant une divergence permanente
entre ce que le modèle décrit et ce que la base contient.

## Décision

**Le SQL livré crée le schéma. Django l'apprend sans le créer.**

La migration `noyau/migrations/0001_initial.py` fait trois choses, dans l'ordre :

1. `RunSQL(sql/0001_socle.sql)` — copie fidèle du script livré ;
2. `RunSQL(sql/0002_adaptations.sql)` — les adaptations du backend, isolées pour
   rester visibles au diff ;
3. `SeparateDatabaseAndState(state_operations=[…])` — les `CreateModel`
   n'enregistrent que l'**état**, aucune table n'est créée.

**À partir de la migration 0002, Django reprend la main normalement.** Le jalon
est net : avant, la base fait foi ; après, les migrations Django.

Ce fichier est **assemblé** par `scripts/assembler_migration_socle.py`, qui
refuse de s'exécuter si la migration porte déjà son en-tête.

### Les trois adaptations, et pourquoi elles sont isolées

`0002_adaptations.sql` ne modifie pas le script livré, il s'y ajoute — pour
qu'un lecteur voie exactement ce que le backend a dû changer :

1. `utilisateur.mot_de_passe` — transitoire, jusqu'à la bascule SSO (voir 004) ;
2. `piece_jointe.objet_type` / `objet_id` + reprise — les pièces jointes
   deviennent génériques, sinon chaque pilier aurait sa table de pièces ;
3. la table `parametre` et ses semis — voir 005.

Une correction, en revanche, a été portée dans `0001_socle.sql` : le script livré
insère `EXP_SAI` et `EXP_LEC` avec `domaine = 'exploitation'`, valeur absente de
la contrainte `permission_domaine_valide`. **En l'état, `init_base.sql` ne
s'applique pas.** Le `CHECK` a été complété. À signaler à l'auteur du modèle.

## Conséquences

- Une seule source de vérité pour le schéma, et rien n'est perdu de ce qui a été
  conçu.
- Le garde-fou permanent : `makemigrations --check --dry-run` doit toujours
  répondre `No changes detected`. Dès qu'un modèle diverge du SQL, Django le dit
  — c'est le signal le moins cher qui existe.
- Certains modèles sont `managed = False` (les tables partitionnées du journal),
  parce que Django ne doit surtout pas essayer de les recréer en test.
- Django court-circuite les `DEFAULT` de la base : il envoie toutes les colonnes,
  y compris à `NULL`. Les défauts serveur sont donc **doublés** côté Python
  (`default=uuid.uuid4` sur `Structure`, `Utilisateur`, `PieceJointe`).
- Les tables de liaison n'ont pas d'`id` : `models.CompositePrimaryKey` (Django
  ≥ 5.2) est obligatoire sur `profil_permission` et `delegation_permission`.
- PostgreSQL 16 devient un prérequis dur, pas une préférence.
- **Le coût :** on ne peut pas régénérer 0001 à la légère, et un développeur qui
  lance `makemigrations noyau` par réflexe casse la migration. D'où le refus
  explicite du script d'assemblage et l'entrée dans [les pièges](../../../docs/pieges.md).

## Ce qui invaliderait cette décision

- Une refonte du modèle de données qui abandonnerait le partitionnement et les
  déclencheurs — l'ORM saurait alors tout exprimer.
- Le passage à une base qui n'a pas ces constructions (ce serait un autre
  projet).
- Une dérive de fait : si `0002_adaptations.sql` finissait par contenir plus de
  code que le socle, c'est que le schéma livré n'est plus la référence, et il
  faudrait l'assumer par une nouvelle décision.

## Alternatives écartées

**Laisser Django générer le schéma, puis rajouter le reste en `RunSQL`.** Le
modèle de données aurait été réécrit à l'approximation près, et les
constructions avancées seraient revenues par la fenêtre, en second rideau et
sans revue.

**`inspectdb`.** Génère des modèles mécaniques, sans docstring, sans
`related_name`, sans les commentaires qui expliquent *pourquoi* une colonne
existe. Les modèles ont été écrits à la main pour cette raison ; ils portent la
référence à l'exigence qui les justifie.

**Ne pas utiliser l'ORM du tout, tout en SQL.** Cohérent, mais on perdrait les
migrations, l'admin, les tests avec base transactionnelle, et l'intégration de
ninja avec les modèles.

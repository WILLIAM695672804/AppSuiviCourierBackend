# Module « activités »

**État : fait et testé.** Schéma, modèles, règles, lectures, écritures, les
dix-neuf routes et les traitements nocturnes. 77 tests pour ce seul pilier.

Ce document sera mis à jour au fur et à mesure — c'est la règle du projet, pas
une intention.

## Ce que le pilier suit

Une **activité** est une action menée par une structure dans l'année. Les
activités d'une structure pour une année forment son **plan d'actions annuel**
(PAA), validé par la DCG.

Source : cahier des charges §15 à §20.

## Ce qui caractérise une activité

| Élément | Remarque |
|---|---|
| axe stratégique | référentiel **fermé** de trois axes, jamais de saisie libre |
| structure porteuse | décide de la visibilité |
| responsable | l'agent, pour la portée `propre` |
| période | début, échéance |
| avancement | 0 à 100, déclaré par la structure |
| avancement attendu | **calculé** — règle non arbitrée, voir [A1](../../../docs/questions-ouvertes.md) |
| état | découle de l'avancement, de l'échéance et de la suspension |
| critique | en retard **et** contrainte échue — règle non arbitrée ([A3](../../../docs/questions-ouvertes.md)) |
| indicateurs | avec relevés datés |
| tâches | avec échéance et fait / non fait |
| pièces | via `noyau/pieces`, générique |
| instructions rattachées | ordre d'autorité, avec échéance et levée |
| suspension | motif, date, auteur |
| relances | dernière relance, par la DSR |
| fiche de vie | **pas une table** : les événements de l'objet |

## Les gestes, et qui les porte

Trois rôles distincts, trois permissions. C'est la découpe qui gouverne les
routes comme les écrans — une structure ne se suspend pas elle-même.

| Geste | Permission | Qui |
|---|---|---|
| créer, modifier une activité | `ACT_SAI` | la structure |
| déclarer un avancement | `ACT_SAI` | la structure |
| ajouter un indicateur, relever | `ACT_SAI` | la structure |
| ajouter une tâche, la cocher | `ACT_SAI` | la structure |
| joindre une pièce | `ACT_SAI` | la structure |
| suspendre / reprendre | `DEC` | l'autorité |
| rattacher une instruction, la lever | `DEC` | l'autorité |
| relancer | `REL` | la DSR |
| soumettre un plan | `ACT_SAI` | la structure |
| valider / renvoyer un plan | `ACT_VAL` | la DCG |
| lire | `ACT_LEC` | dans son périmètre |

## Le schéma

`activite/migrations/sql/0001_activite.sql` est la copie fidèle de
`init_activite.sql` livré à la racine du dépôt — seules les trois lignes propres
à psql (`ON_ERROR_STOP`, `BEGIN`, `COMMIT`) en ont été retirées, Django ouvrant
lui-même la transaction. Il est appliqué par `activite/0001_initial`, assemblée
par `scripts/assembler_migration_pilier.py` sur le modèle du socle
([ADR 003](../architecture/003-django-proprietaire-du-schema.md)).

Quinze tables et une vue :

| Table | Rôle |
|---|---|
| `axe_strategique` | référentiel fermé des trois axes |
| `exercice` | l'année de gestion, qui se clôt |
| `paa`, `paa_version` | le plan d'actions annuel et ses soumissions |
| `activite` | §15, une colonne par attribut demandé |
| `activite_indicateur`, `indicateur_mesure` | l'indicateur et ses relevés datés |
| `tache` | pondérée ; c'est elle qui porte l'avancement |
| `decision_reunion`, `decision_effet` | §19, avec valeur avant / après |
| `instruction_activite` | §17, avec échéance et levée |
| `activite_suspension` | §19, un état motivé et réversible |
| `calendrier_production`, `obligation` | §3.3, ce que chaque structure doit déposer |
| `agregat_activite_jour` | le cockpit n'agrège jamais à la volée |
| `v_activite_etat` (vue) | l'état affiché et la contrainte échue |

Le journal, les pièces jointes et les relances **ne sont pas dupliqués** : ce
sont ceux du socle. `relance` a simplement gagné une colonne `activite_id`.

Quatre règles sont posées dans le moteur, pas dans le code — elles tiennent donc
aussi pour une reprise de données ou une correction en SQL direct :

- la référence `PAA-<structure>-<n>` est attribuée par déclencheur, jamais saisie ;
- `avancement_calcule` est recalculé à chaque changement de tâche, pondéré par
  `tache.poids` (arbitrage n° 1) ;
- une activité suspendue **refuse** toute modification d'avancement ;
- `activite.etat` suit la table de suspension, qui est la source. Le code ne doit
  jamais écrire `etat = 'suspendue'` directement.

## Toute écriture exige un acteur en session

**Découvert en appliquant le schéma, et cela vaut pour tout le pilier.** Le
déclencheur `historiser_champs()` du socle refuse toute modification de
`activite`, `paa`, `tache` et `instruction_activite` quand la variable
`app.utilisateur_id` n'est pas posée :

> `Modification de activite sans acteur identifié.`

Le noyau n'avait jamais eu à s'en soucier : il ne modifie aucune des sept tables
historisées. Le pilier activités en modifie quatre. D'où
`noyau/journal/contexte.py` :

```python
with acteur(utilisateur):  # une écriture métier
    ...
with traitement_automatique("recalcul_agregats"):  # une tâche nocturne
    ...
```

`SET LOCAL` n'ayant d'effet qu'en transaction, les deux gestionnaires ouvrent
leur propre bloc atomique.

**La portée est plus large qu'il n'y paraît.** Cocher une tâche déclenche le
recalcul de l'avancement, qui met à jour `activite`, qui déclenche
l'historisation. Poser une suspension met à jour `activite.etat`, même effet.
Une écriture qui ne touche pas directement une table historisée peut donc
échouer par ricochet.

## Ce qui reste à écrire

```
activite/
  modeles.py     ✔ fait — reflet du SQL, pas sa source
  services.py    les règles — c'est ici que tout se joue
  schemas.py     SaisieXxx / XxxSortie, en camelCase
  api.py         les routes, montées sur /activites
  taches.py      Celery : recalcul nocturne, engendrement des obligations, relances
  tests/
    test_schema.py   ✔ fait — les règles du moteur, éprouvées
    test_regles.py   ✔ fait — l'état affiché, et le filet Python ↔ SQL
```

Le montage est prêt, commenté dans `config/api.py`.

## Deux choses que les services devront faire

**Recharger l'activité après création.** Le code est posé par un déclencheur
`BEFORE INSERT` ; Django ne relit pas la ligne, et l'objet en mémoire porte la
chaîne vide. Un `refresh_from_db()` est obligatoire avant de renvoyer la fiche.

**Traduire les refus du moteur.** Le déclencheur qui interdit d'avancer une
activité suspendue lève un `check_violation`, que psycopg remonte en
`IntegrityError`. Laissée telle quelle, elle sort en 500. Le service doit la
traduire en `EtatInvalide` (409).

## La définition du retard — tranchée

**Deux définitions coexistaient, et elles ne désignaient pas les mêmes
activités.** C'est l'**arbitrage n° 2** qui fait foi depuis le 12 août 2026 :

> Une activité est en retard quand son échéance est passée et qu'elle n'est ni
> réalisée ni suspendue.

Retenue non parce qu'elle serait plus juste, mais parce qu'elle a une **source**
— le MODELE DE DONNEES v2 la cite comme un arbitrage rendu. L'autre, l'écart à
un avancement attendu avec un seuil de dix points, a été inventée par la
conception.

Le choix est **en base** (`parametre` → `activite.definition_retard`,
statut `acte`) et non en dur : le jour où la DSR trancherait autrement, c'est une
valeur à changer, pas un redéploiement.

L'écart à l'attendu n'a pas disparu — `regles.ecart_a_attendu()` le calcule
toujours, et il reste affichable comme indication. Mais **il ne décide plus de
l'état**, et ses deux paramètres restent en `hypothese`.
Voir [A2](../../../docs/questions-ouvertes.md).

**Deux implémentations, une seule règle.** La vue `v_activite_etat` l'applique en
SQL — c'est elle qui sert aux registres et aux agrégats, on ne parcourt pas deux
cents activités en Python pour recalculer ce qu'un `SELECT` donne.
`activite/regles.py` l'applique en Python, pour les cas unitaires et parce
qu'une règle métier doit être lisible quelque part. Le filet
`test_les_deux_definitions_du_retard_concordent` vérifie qu'elles ne divergent
pas — c'est exactement ce que trancher A2 devait faire cesser.

**Suspendue prime sur en retard.** Reprocher un retard à une structure à qui une
autorité a interdit d'avancer serait faux.

## Les autres points d'attention

**Trois règles restent des hypothèses.** Avancement attendu, criticité, taux
d'atteinte d'un indicateur : aucune n'a de source. Depuis que A2 est tranchée,
l'avancement attendu ne décide plus de rien — il n'est qu'un écart affiché. Elles se lisent dans la table
`parametre`, jamais en dur. Voir
[regles/activite-parametres.md](../regles/activite-parametres.md).

Le cas de l'indicateur **décroissant** (un délai à réduire) est désormais
modélisé — `activite_indicateur.sens_decroissant` — mais la formule elle-même
reste à arbitrer.

**Une activité suspendue refuse la mise à jour d'avancement** — 409 côté API.
La base la refuse déjà, par déclencheur : le service doit traduire l'erreur
PostgreSQL en `EtatInvalide`, pas la laisser remonter en 500.

**Le recalcul d'état est différé.** L'avancement attendu, donc le retard, donc la
criticité changent avec le simple passage du temps, sans qu'aucune écriture ne
survienne. Une tâche Celery nocturne doit les recalculer ; sinon le cockpit
n'affiche du retard qu'aux activités que quelqu'un a touchées.

**`structuresAccessibles`** est renvoyé au front pour peupler un sélecteur. Ce
n'est **pas** une protection : `restreindre()` l'est.

**Le pilier écrit beaucoup.** Chaque geste inscrit un événement — c'est ce qui
constitue la fiche de vie (§18). Et c'est avec la première route d'écriture
d'ici qu'il faudra écrire le filet manquant : le test qui refuse une route de
mutation sans écriture au journal. Voir [traçabilité](../tracabilite.md).

## La référence en attendant

`frontend/src/lib/demo/serveur.ts` est aujourd'hui la description la plus
complète du comportement attendu, et `frontend/src/features/activite/api.ts`
donne les formes exactes que le backend doit rendre.

Quand le backend et la démo divergeront, ce sera une **question**, pas un bug du
front.
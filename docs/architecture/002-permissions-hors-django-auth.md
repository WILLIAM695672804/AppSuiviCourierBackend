# 002 — Permissions et périmètre hors de `django.contrib.auth`

**Statut :** acceptée · **Date :** 11 août 2026

## Contexte

Le contrôle d'accès de ce projet pose **deux questions indépendantes** :

> Les permissions disent **QUOI**. Le périmètre dit **SUR QUELLES DONNÉES**.

`ACT_SAI` autorise à saisir une activité. Elle ne dit pas *lesquelles* : un point
focal saisit celles de sa structure, un attaché à la DSR voit tout
l'établissement, un directeur voit sa direction et ses divisions. Même
permission, trois ensembles de lignes.

Le modèle de Django ne connaît que la première question. Sa réponse est
`utilisateur.has_perm("activite.change_activite")` — un booléen, sans notion
d'étendue. Les permissions par objet existent en bibliothèque tierce
(`django-guardian`), mais elles répondent « cet objet précis », alors que notre
périmètre se dit en compréhension : « ma structure et ses descendants ».

Par ailleurs, le schéma de la base est **livré**. Il porte déjà `permission`,
`profil`, `profil_permission`, `utilisateur_profil`, `delegation`, avec des
colonnes en français et des attributions datées (`retire_le`) que Django ne
prévoit pas.

## Décision

Les permissions, les profils et les délégations sont modélisés **par le projet**,
dans `noyau/habilitation/`, sur les tables livrées. `django.contrib.auth` n'est
pas utilisé pour l'autorisation.

Le périmètre est un mécanisme **distinct**, dans `noyau/perimetre/portee.py`.

Deux fonctions publiques, et l'usage doit passer par elles :

```python
possede(utilisateur, PERM.ACT_SAI)                    # QUOI
restreindre(requete, utilisateur, champ_structure=…)  # SUR QUELLES DONNÉES
```

Les routes déclarent la première par `auth=exige(PERM.ACT_SAI)`. La seconde
n'est jamais automatique : **chaque route qui renvoie des données appelle
`restreindre()` elle-même.**

Quatre portées, stockées telles quelles en base :

| En base | Côté front | Signification |
|---|---|---|
| `propre` | `poste` | ce que l'agent a produit |
| `structure` | `structure` | sa structure |
| `sous_arbre` | `structure_et_descendants` | sa structure et ses descendants |
| `toutes` | `institution` | tout le PAD |

Règle de nommage qui découle de tout ceci : **aucun code de permission ne nomme
un poste.** Un poste est un profil, qui porte des permissions. C'est ce qui
permet de déplacer une responsabilité sans toucher au code. Deux exceptions
assumées — `VUE_DG` et `VUE_CODIR` — sont commentées dans le schéma SQL et ne
doivent pas servir de précédent.

## Conséquences

- Le contrôle d'accès est **explicite et lisible**, dans deux modules qu'on peut
  relire en entier.
- Le front reçoit une **liste plate** de codes et ne recalcule rien
  (`UtilisateurConnecte.permissions`). Sa construction a un seul endroit :
  `noyau/habilitation/resolution.py`.
- Une délégation n'accorde **que** ce qu'elle énumère ; elle ne transmet pas les
  droits du titulaire en bloc (RF-BPM-04).
- L'admin Django ne sait pas gérer ces droits. Ce n'est pas une perte :
  l'administration passe par les écrans du pilier « administration », qui sont
  eux-mêmes soumis aux permissions.
- **Le vrai coût :** `restreindre()` n'étant pas automatique, l'oublier ne
  produit aucune erreur — juste une fuite silencieuse. C'est le risque le plus
  sérieux du projet, et il est traité par la revue et par les tests, pas par le
  cadre.
- `portee.py` a un piège volontaire : `structures_visibles()` renvoie **`None`**
  pour la portée `toutes`, ce qui veut dire « aucune restriction » et non
  « aucune structure ». Et `restreindre()` **lève `ValueError`** si la portée
  `propre` est demandée sans `champ_agent` — ne rien filtrer serait pire.

## Ce qui invaliderait cette décision

- Le schéma cesserait de porter ces tables (autrement dit : le modèle de données
  serait refait).
- Django gagnerait des permissions à périmètre exprimé en compréhension.
- Le besoin de brancher un outil tiers qui suppose `django.contrib.auth`
  (certains outils d'administration ou d'audit).

## Alternatives écartées

**`django.contrib.auth` + `django-guardian`.** Guardian raisonne par objet, nous
raisonnons par sous-arbre. Il aurait fallu matérialiser une ligne d'ACL par
objet et par utilisateur, à recalculer à chaque réorganisation de
l'organigramme.

**Tout mettre dans les permissions** (`ACT_SAI_STRUCTURE`,
`ACT_SAI_SOUS_ARBRE`, `ACT_SAI_TOUT`). Le produit cartésien des deux axes :
37 permissions deviennent une centaine, et chaque nouvelle portée les multiplie.
C'est précisément ce que la séparation évite.

**Row-level security PostgreSQL.** Élégant, et la base le permet. Écarté pour
l'instant : il faudrait propager l'identité de l'utilisateur dans la session
PostgreSQL sous le pooling, et le contrôle deviendrait invisible depuis Python —
donc invérifiable par un test lisible. À réexaminer si les fuites par oubli de
`restreindre()` deviennent un problème réel.

# 037 — La date de clôture se lit sur le courrier

27 août 2026. **Corrige une conséquence de l'[ADR 036](036-le-traitement-et-la-cloture-ferment-le-trajet.md)**, dont le reste tient.

## Contexte

L'ADR 036 affirmait ceci, et c'était faux :

> La date de clôture se lit au journal, pas sur le courrier : le socle ne porte
> pas de colonne `cloture_le`.

Le socle porte `courrier.cloture_le` depuis le premier jour, avec
`cloture_par` et `motif_cloture`, et une contrainte qui les rend obligatoires :

```sql
CONSTRAINT courrier_cloture_coherente
  CHECK ((statut_courrier = 'cloture') = (cloture_le IS NOT NULL))
```

Deux conséquences, l'une visible et l'autre non :

1. **`clore()` ne pouvait pas fonctionner.** Il posait `statut_courrier` seul.
   Le premier appel réel aurait levé une `IntegrityError`. Aucun test ne l'a vu,
   parce qu'aucun test n'appelait encore la route.
2. **Les mesures lisaient le journal** — une jointure sur `evenement`, qui est
   partitionnée par `RANGE (survenu_le)`, plus un `DISTINCT ON (c.id)` pour ne
   pas compter trois fois un courrier coté à trois structures. Tout cela pour
   retrouver une colonne qui était là.

Ce qui a fait apparaître les deux : charger le jeu de données de démonstration.
Le semis écrivait la clôture en `UPDATE` direct — et renseignait `cloture_le`,
parce que la contrainte l'y avait obligé le jour où il a été écrit.

## Décision

**La date de clôture se lit sur `courrier.cloture_le`, et `clore()` la
renseigne** avec `cloture_par` et `motif_cloture`.

L'événement `courrier.cloture` reste inscrit, et reste un jalon public : il dit
*qui* a clôturé et *quand* dans la fiche de vie. Ce n'est simplement plus lui
qu'on interroge pour compter.

## Conséquences

- **Les quatre requêtes de mesure perdent leur jointure sur `evenement`**, leur
  `DISTINCT ON` et leur sous-requête — dans `pilotage/mesures.py` et
  `performance/matrice.py`. Le cloisonnement par structure passe d'une jointure
  à un `EXISTS`, pour la même raison qui imposait le `DISTINCT ON`.
- **`modifie_le` reste écarté**, et c'est le seul point de l'ADR 036 qui
  survit intact sur ce sujet : il bouge à chaque correction de saisie.
- **Le semis de démonstration passe par `services.clore()`**, comme il passe
  déjà par `coter` et `affecter`. Ce qu'il écrivait à la main ne produisait
  aucun événement : la fiche de vie s'arrêtait à l'affectation.

## Ce qui invaliderait cette décision

Un courrier clos doit pouvoir se rouvrir. `cloture_le` ne porterait alors qu'une
seule date là où le journal les porte toutes — et c'est le journal qu'il
faudrait interroger, comme l'ADR 036 le proposait pour une mauvaise raison.

## Alternatives écartées

**Laisser la lecture au journal et se contenter de renseigner `cloture_le`.**
Deux sources pour la même date, dont une seule contrainte par la base. Elles
auraient divergé au premier `UPDATE` fait à la main — exactement ce que le semis
faisait la veille.

**Écrire l'ADR 036 à nouveau.** Un ADR ne se modifie pas
([README](README.md)). Celui-ci se trompait sur un fait, pas sur sa décision :
les quatre gestes, la clôture définitive et le jalon public tiennent tous. Le
remplacer en entier aurait effacé un raisonnement encore valable pour corriger
une phrase.

## Le piège, pour mémoire

Le socle fait 1 200 lignes de SQL, et le modèle Django le suit sans le
contraindre ([ADR 003](003-django-proprietaire-du-schema.md)). J'ai écrit
`clore()` en lisant `modeles.py` — où `cloture_le` figure pourtant, ligne 224 —
sans lire le `CREATE TABLE`. **Avant d'écrire un service qui change un statut,
lire les `CONSTRAINT` de sa table.** Elles disent quelles colonnes vont
ensemble, ce qu'aucune annotation de modèle ne dit.

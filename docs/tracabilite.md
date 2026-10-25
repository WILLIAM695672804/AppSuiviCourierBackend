# Traçabilité

**Règle du projet : toute écriture métier inscrit un événement. Sans
exception.**

Exigée par §18 pour les activités, §10 et §23 pour les courriers, RNF-TRACE-01
pour tout le reste. Ce n'est pas une exigence de confort : la plateforme suit des
décisions d'instances, et un suivi qu'on ne peut pas prouver ne suit rien.

## Trois tables, trois rôles à ne pas confondre

| Table | Répond à | Alimentée par | Modifiable |
|---|---|---|---|
| `evenement` | « qu'est-ce qui s'est passé ? » | le code, via `inscrire()` | non |
| `champ_historique` | « quelle colonne a changé, de quoi à quoi ? » | **des déclencheurs** | non |
| `journal_acces` | « qui a lu quoi ? » | le code, via `tracer_acces()` | non |

La distinction qui compte : `evenement` porte ce que l'application a **décidé de
raconter** — un fait métier, avec un libellé lisible par un agent.
`champ_historique` porte ce qui a **matériellement changé**, y compris une
modification faite en SQL direct, hors application. Les deux sont nécessaires :
le premier est compréhensible, le second est incontournable.

Aucun des trois modèles n'a de `save()` surchargé ni de méthode d'édition, et
c'est délibéré : une piste d'audit qu'on peut corriger ne prouve rien.

## La fiche de vie

La fiche de vie d'une activité (§18) **n'est pas une table**. C'est la liste des
événements portant `objet_type = 'activite'` et `objet_id = <id>`, dans l'ordre
où ils sont survenus. Les tables du journal étant génériques, chaque nouveau
pilier s'y branche sans en créer une seule.

## Écrire au journal

Un seul point d'entrée : `noyau/journal/service.py`. Un service métier appelle
`inscrire()`, **jamais** `Evenement.objects.create()`.

```python
from noyau.journal.service import inscrire

inscrire(
    objet_type="activite",
    objet_id=activite.pk,
    type_evenement="suspension",
    libelle=f"Activité suspendue par {acteur.nom_complet}",
    detail=motif,
    acteur=acteur,
    agit_pour=titulaire,  # si l'acteur agit par délégation
    donnees={"motif": motif},  # ce qu'un humain ne lira pas, mais qu'une requête cherchera
)
```

L'insertion passe par du SQL direct : les tables sont partitionnées, leur clé
primaire est composite (`id`, `survenu_le`), et l'ORM ne sait pas y écrire.

### `acteur` et `agit_pour` : deux colonnes, jamais une

`acteur` est **qui a saisi**. `agit_pour` est le titulaire **au nom duquel** il
agit, en cas de délégation ou de remplacement (RF-BPM-04).

Renseigner les deux n'est pas facultatif quand une délégation est active. C'est
ce qui distingue « le remplaçant a validé » de « le directeur a validé » — et
attribuer au remplaçant une décision qu'il n'a pas prise viderait le journal de
sa valeur probante.

`noyau/habilitation/resolution.delegation_active()` donne le titulaire.

## Tracer un accès

`tracer_acces()` — RF-ADM-03. À appeler sur la lecture d'un objet **sensible** :
courrier confidentiel, dossier clos, pièce versée aux archives.

**Pas sur chaque liste.** La table grossirait de plusieurs millions de lignes par
mois sans rien apprendre à personne, et la seule chose qu'on y gagnerait est de
ne plus pouvoir la lire quand elle servirait vraiment.

Le journal d'accès est chaîné par empreinte (RNF-TRACE-01) ; le scellement se
fait par lot en arrière-plan.

## Volumétrie et purge

`evenement` et `champ_historique` sont partitionnées **par année**,
`journal_acces` **par mois**. Conséquences pratiques :

- créer les partitions de l'année à venir est une tâche d'exploitation
  planifiée. Une partition manquante, c'est une écriture en échec —
  c'est-à-dire, ici, une écriture métier en échec. Voir le
  [runbook](exploitation/runbook.md).
- purger, c'est détacher une partition, pas supprimer des lignes ;
- les durées de conservation ne sont pas arrêtées : voir
  [question ouverte A10](../../docs/questions-ouvertes.md).

Les index BRIN sur les colonnes temporelles supposent des données insérées dans
l'ordre du temps. C'est le cas par construction ; une reprise massive qui
insérerait dans le désordre les rendrait inefficaces.

## Ce qui n'est pas encore fait

Le filet manque. Rien n'empêche aujourd'hui une route d'écriture d'oublier
`inscrire()`. Le test qui refuserait toute route de mutation sans écriture au
journal est **à écrire avec la première route d'écriture du pilier
« activités »** — d'ici là, la règle en tête de page n'est qu'une intention, et
c'est dit ici pour que personne ne s'y trompe.

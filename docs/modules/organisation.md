# Module « organisation » — l'organigramme et son référentiel

**État.** Les modèles sont livrés depuis le socle ; la lecture publique
(`/api/referentiels/structures`) est livrée et le front est branché dessus.
L'écriture vit ailleurs — voir plus bas.

Ce module n'est pas un pilier : c'est le socle sur lequel les autres s'appuient.
Le périmètre s'y calcule, la cotation y choisit sa cible, la hiérarchie s'y lit.

## Les trois principes du schéma

Ils sont dans la docstring de `modeles.py`, ils sont répétés ici parce qu'on les
casse sans s'en apercevoir.

1. **Rien n'est supprimé.** Une structure ne se modifie pas : on clôt la ligne en
   vigueur (`valide_au`) et on en insère une nouvelle. Après une réorganisation,
   une cotation de 2024 doit rester lisible avec les structures de 2024. D'où
   `Structure.objects.en_vigueur()`, à utiliser partout sauf en consultation
   historique.
2. **Le poste porte la hiérarchie, pas l'agent.** La remontée reste juste quand
   l'occupant change. Ne jamais chaîner deux utilisateurs : chaîner leurs postes.
3. **Les niveaux ne sont pas écrits dans le code.** L'administrateur en crée et
   en supprime. Toute constante du genre `NIVEAU_DIRECTION = 2` est un défaut.

## Les tables

| Table | Rôle |
|---|---|
| `niveau_hierarchique` | les échelons, avec leur `rang` — **1 = sommet** |
| `structure` | direction, service, division, filiale, succursale ; historisée |
| `poste` | le poste, sa structure, son échelon, son `poste_superieur` |

`nature` dit ce qu'est la structure **en droit**, pas sa place dans l'arbre : une
filiale et une succursale ont leurs propres organes de gestion, dont la DSR suit
les sessions (§3.3).

**`descendants()` descend en SQL**, par CTE récursive, et non par boucle Python :
la portée `sous_arbre` du périmètre s'en sert à chaque requête de liste, et une
remontée par boucle produirait une requête par nœud.

## La lecture — `GET /referentiels/structures`

**Elle ne passe pas par `restreindre()`, et c'est une dérogation écrite** —
[ADR 007](../architecture/007-referentiel-organigramme-sans-perimetre.md). Un
référentiel de saisie doit montrer les structures que l'agent ne voit pas : on ne
cote pas vers une direction absente de la liste. La dérogation porte sur
l'organigramme seul — rien de ce qui s'y rattache, courriers, décisions,
activités, ne se lit ainsi. La garde est donc `session_seule`, dont le commentaire
dans `noyau/habilitation/dependances.py` **énumère ses trois usages** : une garde
plus faible que les autres doit rester dénombrable.

**Seules les structures en vigueur sortent.** Une direction dissoute garde sa
ligne close pour l'histoire, mais elle ne doit plus pouvoir être choisie.

**`responsable` est déduit du poste, jamais d'une colonne.** Il n'existe pas de
colonne « responsable » sur `structure`, et c'est délibéré : la stocker aurait
coûté une seconde vérité, qui aurait vieilli. Trois critères, dans cet ordre — le
poste **sans supérieur** dans la structure (le sommet local), puis le rang de
l'échelon, puis le nom. Arbitraire au dernier cran, mais **stable** : un
référentiel qui change d'avis d'un rafraîchissement à l'autre est illisible.

**`delaiMoyenJours` et `courriersEnCours` sortent à `None` et `0`.** Aucune source
ne dit ce que « en cours » recouvre ni sur quelle fenêtre se calcule la moyenne.
Depuis la livraison du pilier courrier (17 août 2026), la matière **est** là : ce
qui manque n'est plus la source mais la définition. Un calcul inventé aurait été
recopié dans un rapport avant d'être corrigé —
[A18](../../../docs/questions-ouvertes.md).

**`niveau` est le rang de l'échelon, pas une profondeur calculée.** C'est déjà ce
que `POST /organisation/structures` reçoit en entrée : lecture et écriture parlent
du même nombre. Côté front, l'indentation se compte donc en `(niveau - 1)` —
sinon la Direction Générale serait décalée d'un cran.

## L'écriture — `POST /organisation/structures`

Sous `ADM_ORG`, comme les niveaux, les postes et les affectations. Les règles de
création sont dans `noyau/organisation/services.py::creer_structure`.

Elle vivait sur `/gouvernance`, sous `ADM_STR`, permission de la DSR : le
descriptif lui confie le référentiel des structures (§3.3). Le partage ne tenait
pas, parce que créer une structure **ouvre son poste responsable vacant** — et
pourvoir ce poste relevait de l'administrateur. Chacun faisait la moitié du
geste ; les deux sont réunis
([ADR 021](../architecture/021-l-organigramme-tient-sous-une-seule-permission.md)).

La **lecture**, elle, n'a pas bougé : elle sert sept écrans de quatre piliers et
reste ouverte à toute session (ADR 007). La DSR consulte donc toujours le
référentiel depuis son espace de travail.

## Le piège des tests

**Toute modification de `structure` exige un acteur.** Un déclencheur du schéma le
vérifie, y compris en test :

```python
from noyau.journal.contexte import acteur as contexte_acteur

with contexte_acteur(agent):
    structure.libelle = "…"
    structure.save()
```

Sans quoi : `ProgrammingError: Modification de structure sans acteur identifie`.
La **création** (`Structure.objects.create`) passe sans acteur — ce qui rend le
défaut d'autant plus facile à écrire, puisque le jeu d'essai ne le déclenche
jamais. Sept tables sont historisées ainsi : `activite`, `paa`, `tache`,
`instruction_activite`, `courrier`, `cotation`, `structure`.

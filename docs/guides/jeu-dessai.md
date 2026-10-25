# Le jeu d'essai

```bash
make semer
```

Charge un organigramme, dix comptes, leurs profils et leurs périmètres. La
commande est **idempotente** : la relancer ne crée pas de doublons.

Le mot de passe est commun à tous les comptes : `demonstration`. Il se change
par `--mot-de-passe`.

## L'avertissement, avant tout le reste

**Cet organigramme est fictif.** L'organigramme réel du Port autonome de Douala
n'a jamais été communiqué — les décisions de cadrage le classent parmi les trois
documents réellement bloquants : « sans lui, les périmètres restent théoriques,
et l'écran de cotation ne peut pas proposer de vraies structures ».

L'arbre ci-dessous est une approximation de travail. Il est conçu pour une seule
chose : **éprouver les quatre portées de périmètre**. Il ne prétend rien d'autre.

La commande refuse de s'exécuter quand `DEBUG` est faux — ces comptes ont un mot
de passe commun et public. `--force` passe outre, et c'est volontairement
pénible.

## L'organigramme

```
DG  ─ Direction Générale
├── DSR      Division du Suivi et de la Relance
├── DCG      Direction du Contrôle de Gestion
├── DSI      Direction des Systèmes d'Information
│   ├── DSI-ET   Service des Études
│   └── DSI-IN   Service Infrastructure
├── DAF      Direction des Affaires Financières
│   └── DAF-CP   Service Comptabilité
└── SCC      Service du Courrier Central
```

La DSI porte deux services, et ce n'est pas décoratif : c'est le seul moyen
d'éprouver la portée `sous_arbre`, celle qui distingue un directeur d'un chef de
service — et celle dont une erreur ne se voit pas.

## Les comptes

| Identifiant | Profil | Portée | Voit | Sur les activités |
|---|---|---|---|---|
| `dg` | Directeur Général | `toutes` | tout | `ACT_LEC`, `DEC` |
| `admin` | Administrateur fonctionnel | `toutes` | tout | — |
| `dsr` | Division du suivi | `toutes` | tout | `ACT_LEC`, `ACT_VAL`, `DEC`, `REL` |
| `att.dsr` | Attaché à la DSR | `toutes` | tout | `ACT_LEC`, `DEC`, `REL` |
| `dcg` | Contrôle de gestion | `toutes` | tout | `ACT_LEC`, `ACT_VAL` |
| `dir.dsi` | Responsable de structure | `sous_arbre` | DSI, DSI-ET, DSI-IN | `ACT_LEC`, `ACT_SAI` |
| `focal.dsi` | Point focal | `structure` | DSI | `ACT_LEC`, `ACT_SAI` |
| `focal.daf` | Point focal | `structure` | DAF | `ACT_LEC`, `ACT_SAI` |
| `agent.dsi` | Collaborateur | `propre` | DSI-ET | — |
| `agent.scc` | Agent de session | `structure` | SCC | — (session « arrivé ») |

Les profils et leurs permissions ne sont **pas** créés par la commande : ils sont
semés par la migration, depuis le référentiel livré. La commande ne fait que les
attribuer.

## Les deux comptes qui comptent le plus

`focal.dsi` et `focal.daf`. Même profil, même portée, structures différentes.
C'est la seule façon de vérifier qu'un agent **ne voit pas le plan du voisin** —
et le cloisonnement est ce qu'un filtre d'affichage ne remplace jamais.

De même, quatre comptes portent quatre rôles distincts sur les activités : qui
déclare (`focal.*`), qui arbitre (`dg`), qui relance (`att.dsr`), qui valide
(`dcg`). Si un seul compte cumulait tout, les tests du pilier passeraient sans
rien prouver.

## Le périmètre n'est pas optionnel

Chaque compte reçoit un périmètre, et c'est le point le plus facile à oublier.
Un agent **sans périmètre ne voit rien** — c'est la règle 3 de
`noyau/perimetre/portee.py`, et c'est voulu.

Un jeu d'essai qui omettrait cette ligne produirait dix comptes qui se connectent
et n'affichent aucune donnée. On chercherait le bug ailleurs pendant une
demi-journée. Le test `test_chaque_compte_porte_un_perimetre` existe pour cela.

## Ce que le jeu d'essai ne couvre pas

- **Aucune activité, aucun courrier.** Seuls l'organigramme et les comptes. Les
  données métier viendront avec les piliers.
- **La portée `propre` sur les activités.** `agent.dsi` la porte, mais son profil
  (Collaborateur) n'a aucune permission d'activité — c'est le référentiel livré
  qui en décide, et il n'a pas été déformé pour arranger les tests. La portée
  `propre` reste donc éprouvée sur le courrier, pas sur les activités.
- **Les délégations.** Aucune n'est posée ; le champ `agit_pour` du journal n'est
  donc pas exercé.

## Quand vous le modifiez

La commande a ses tests (`noyau/tests/test_semer.py`). Ils ne vérifient pas
qu'elle s'exécute — ils vérifient que **les périmètres cloisonnent réellement**.
Ajouter un compte sans ajouter l'assertion correspondante, c'est ajouter un
compte dont personne ne sait ce qu'il voit.

Et mettez cette page à jour dans le même diff : le tableau ci-dessus est ce que
lira le prochain arrivant.

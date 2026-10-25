# Module « gouvernance »

**État.** Complet. Schéma, modèles, lecture, services, routes et tâches, montés
sur `/api/gouvernance`. Le front n'est pas encore branché.

Source : descriptif fonctionnel §3.3, qui confie à la Direction du Suivi et des
Relations cinq charges — plus une sixième, le planning des congés.

## Un seul engagement, trois origines

**C'est la décision structurante du pilier** —
[ADR 006](../architecture/006-un-seul-engagement.md).

Le front décrit trois objets sur trois écrans : décision d'instance,
prescription de filiale, recommandation externe. Ce sont **les mêmes champs et
le même suivi** — un objet, une échéance, des structures internes chargées, un
avancement, un état. Ce qui les distingue est leur provenance.

D'où une seule table, `engagement`, avec une colonne `origine` et trois clefs
étrangères mutuellement exclusives. Une contrainte garantit qu'une et une seule
est renseignée : un engagement sans provenance ne serait rattachable à aucun
écran, deux le feraient apparaître sur deux registres.

**La table est l'ancienne `decision_reunion`**, livrée avec le pilier activités
pour le §19 et renommée. Conséquence voulue : une décision du CODIR qui suspend
une activité reste **la même ligne** que celle que la gouvernance suit. Un test
le vérifie de bout en bout.

## Les tables

| Table | Rôle |
|---|---|
| `engagement` | décision, prescription ou recommandation — trois origines |
| `engagement_structure` | qui est chargé, et où il en est ; **rang 1 = pilote** |
| `engagement_jalon` | les étapes datées |
| `engagement_observation` | le fil de suivi ; le drapeau `relance` distingue |
| `seance` | réunions, sessions et rapports dont la DSR tient le secrétariat |
| `seance_point`, `seance_participant`, `seance_document` | ordre du jour, présents, pièces |
| `entite_externe`, `organe_gestion` | filiales et succursales, et leurs organes |
| `organisation_externe`, `representation` | où le PAD siège, et qui l'y représente |
| `disponibilite` | absences des hauts responsables, et intérim |
| `conge_droit`, `conge_periode` | le planning annuel, distinct des absences |
| `agregat_gouvernance_jour` | le tableau de bord n'agrège jamais à la volée |
| `v_engagement_etat` (vue) | l'état affiché, les relances, le jalon échu |

## Ce que le moteur tient

**La référence** — `DEC-2026-0001`, `PRE-…`, `REC-…` — est posée par
déclencheur, sous verrou d'avis : deux insertions concurrentes obtiendraient
sinon le même numéro. Jamais saisie, comme le numéro du courrier.

**L'avancement d'un engagement** est la moyenne de ses structures chargées,
recalculée par déclencheur. **À parts égales, et c'est une hypothèse** : rien ne
dit qu'une structure pilote pèse davantage — [A17](../../../docs/questions-ouvertes.md).

**Deux absences ne se chevauchent pas** pour un même agent : contrainte
d'exclusion GiST, comme pour le rattachement à une session courrier. Deux
absences simultanées rendraient la question « qui le remplace ? » sans réponse.

**`pilote` est une colonne générée** (`rang = 1`), déclarée en
`GeneratedField` : un champ ordinaire serait envoyé dans chaque `INSERT` et
PostgreSQL refuserait. Voir [pièges](../../../docs/pieges.md).

## Ce qui ne se stocke pas

L'**état affiché** d'un engagement — à lancer, en cours, exécuté, en retard,
suspendu. Deux sont stockés (`suspendu_le`, `execute_le`), les trois autres se
déduisent. Même arbitrage que pour les activités : les stocker imposerait de
réécrire toutes les lignes chaque nuit pour un résultat que la date donne déjà.

L'**état du dépôt** d'un compte rendu, de même : `echeance_depot` et la date
constatée suffisent à dire « hors délai ».

## Ce qui n'a pas été unifié, et pourquoi

**Les séances et les organes de filiales** se ressemblent, mais la DSR n'y joue
pas le même rôle : elle tient le secrétariat de l'une et prépare seulement le
dossier de l'autre. Les champs diffèrent réellement.

**Le planning des congés et le registre de disponibilité** : l'un arbitre des
souhaits, l'autre enregistre une absence décidée. Deux objets, deux moments — le
front y insiste, et il a raison.

## Qui voit quoi

**Un engagement est visible par les structures qui en sont chargées, et par
elles seules.** Ni la séance d'origine ni l'auteur de la saisie n'ouvrent le
droit de lecture : la DSR voit tout parce que son périmètre est large, pas parce
qu'elle a tenu la plume.

Conséquence assumée : un engagement **sans structure chargée n'est visible de
personne**. C'est pourquoi la création en exige au moins une — et de toute
façon, personne ne répondrait quand l'instance demanderait où cela en est.

Un engagement n'a pas d'agent responsable : il pèse sur des structures, comme
une obligation. `restreindre()` lève donc en portée `propre` faute de
`champ_agent`, et l'on passe par `porte_une_structure()`.

## Voir n'est pas répondre

**Consigner un avancement se fait pour sa structure de rattachement**, pas pour
tout ce qu'on voit. La distinction est un défaut qu'un test a rattrapé : bornée
au périmètre de lecture, la garde aurait laissé la DSR — qui voit toutes les
structures — déclarer l'avancement de chacune. Elle tient le registre, elle
n'exécute pas.

Les structures descendantes sont incluses : une directrice répond de ses
divisions. Si le besoin apparaît que la DSR consigne à la place d'une direction,
c'est une **délégation** qu'il faudra poser — le socle en a une — et non cette
garde qu'il faudra relâcher.

## Les permissions

| Permission | Ce qu'elle ouvre |
|---|---|
| `DEC` | le registre des décisions, les filiales, les représentations, le tableau de bord, et les écritures d'engagement |
| `INST` | les séances et leurs documents |
| `DISPO` | les absences et le planning des congés |
| `REL` | **la relance seule** — personne ne se relance soi-même, §1.1 — et, en lecture, l'écran du référentiel des structures |

`DEC` n'ouvre pas `INST` : tenir les décisions n'est pas tenir les réunions, et
le §3.3 en fait deux charges distinctes.

## Les routes

Quinze routes, toutes montées sous `/api/gouvernance`. Chacune déclare
`auth=exige(…)` ; chacune de celles qui renvoient des données passe par
`restreindre()` ou par un `_visibles()` de `lecture.py`.

### Ce qui se lit

| Route | Garde | Paramètres | Écran |
|---|---|---|---|
| `GET /tableau-de-bord` | `DEC` | — | `TableauDeBordGouvernance` |
| `GET /decisions` | `DEC` | `instance`, `etat` | `RegistreDecisions` |
| `GET /decisions/{engagement_id}` | `DEC` | — | `FicheDecision` |
| `GET /seances` | `INST` | `type` | `RegistreSeances` |
| `GET /seances/{seance_id}` | `INST` | — | `FicheSeance` |
| `GET /disponibilites` | `DISPO` | `filtre` | `Disponibilites` |
| `GET /conges` | `DISPO` | `annee` | `PlanningConges` |
| `GET /filiales` | `DEC` | — | `Filiales` |
| `GET /representations` | `DEC` | — | `Representations` |

Les valeurs de filtre réellement reconnues, et le sort des autres :

| Paramètre | Valeurs | Hors liste |
|---|---|---|
| `instance` | les libellés d'instance du front | `""` et `toutes` ne filtrent pas |
| `etat` | les libellés d'état composés | `""` et `tous` ne filtrent pas |
| `type` | les libellés de type de séance | `""` et `tous` ne filtrent pas ; un libellé inconnu ne rend **rien** |
| `filtre` | `En cours`, `Sans intérim`, `À venir`, ou un type d'absence | `""` et `Toutes` ne filtrent pas ; un libellé inconnu ne rend **rien** |
| `annee` | entier | l'année en cours par défaut |

`instance`, `etat`, `type` et `filtre` acceptent les **libellés affichés**, pas les codes
de base : c'est ce que le front émet dans sa chaîne de requête, et la traduction
se fait en une passe dans `lecture.py`. Le paramètre s'appelle `type` et non
`type_seance` pour la même raison.

`etat` s'applique **après** composition, parce que l'état d'un engagement est
calculé et non stocké. Le compteur `sansInterim` des disponibilités se calcule
avant le filtrage : il compte ce qui bloque, pas ce qu'on regarde.

### Ce que le tableau de bord renvoie

Quatre blocs, un par carte de l'écran, plus le bandeau :

| Clef | Ce qu'elle alimente | Contenu |
|---|---|---|
| `compteurs` | le bandeau | décisions à suivre, en retard, dépôts hors délai, absences sans intérim |
| `aRelancer` | « Décisions à relancer » | lignes de décision complètes, retards d'abord |
| `depotsEnSouffrance` | « Comptes rendus en souffrance » | lignes de séance dont le dépôt n'est pas fait |
| `absencesSansInterim` | « Absences sans intérim » | absences **en cours** sans suppléant |
| `parInstance` | les barres « Décisions par instance » | les **quatre** instances, même à zéro |

Les listes portent les mêmes lignes composées que les registres — `DecisionLigne`,
`SeanceLigne`, `DisponibiliteLigne` : l'écran y lit `structures`, `avancement`,
`relances`, `echeanceDepot`, `initiales`, qu'il n'aurait pas sur une ligne réduite.

`aRelancer` retient les décisions **en retard ou déjà relancées** : une décision
relancée encore dans les temps appelle une action, et c'est ce que la carte
annonce. Le compteur « En retard » ne compte que les retards.

Le tableau de bord **agrège à la volée**, sans passer par
`agregat_gouvernance_jour` : l'écran doit refléter la relance partie il y a dix
minutes. L'agrégat sert l'historique.

### Ce qui s'écrit

| Route | Garde | Écran |
|---|---|---|
| `POST /decisions` | `DEC` | `ModaleNouvelleDecision`, depuis `RegistreDecisions` |
| `POST /decisions/{id}/avancement` | `DEC` | `ModaleAvancement`, depuis `FicheDecision` |
| `POST /decisions/{id}/relance` | **`REL`** | `ModaleRelance`, depuis `FicheDecision` |
| `POST /seances` | `INST` | `ModaleNouvelleSeance`, depuis `RegistreSeances` |
| `POST /seances/{id}/documents` | `INST` | `ModaleDeposerDocument`, depuis `FicheSeance` |
| `POST /disponibilites` | `DISPO` | `ModaleDeclarerAbsence`, depuis `Disponibilites` |

Toutes délèguent à `services.py` et n'ont dans `api.py` que la garde, la
validation et l'appel. Toutes inscrivent un événement.

**`POST /structures` a quitté le pilier** ([ADR 021](../architecture/021-l-organigramme-tient-sous-une-seule-permission.md)).
Elle écrivait un objet du socle — `noyau.organisation.Structure` — sous une
permission propre à la DSR, et ouvrait au passage un poste que seul
l'administrateur pouvait pourvoir. Elle est devenue
`POST /organisation/structures`, sous `ADM_ORG`.

L'écran `ReferentielStructures` reste, en **lecture** : le référentiel se lit
par `GET /referentiels/structures`, hors pilier et sans permission nommée
(ADR 007).

### Deux points d'attention au branchement

**Les fiches sont déclarées après les chemins fixes.** `/decisions/{id}` placé
avant `/decisions/tableau-de-bord` capturerait le second comme identifiant.
django-ninja retient la première route qui correspond, sans arbitrer.

**Le filtre des disponibilités a deux familles derrière une seule barre.**
`En cours`, `Sans intérim` et `À venir` portent sur l'état de la suppléance ;
les autres libellés sont des **types d'absence**. `Sans intérim` retient toutes
les absences sans suppléant, y compris à venir — une mission qui commence lundi
sans intérimaire se prépare avant. Le compteur `sansInterim`, lui, ne compte que
les absences en cours : ce n'est pas la même question.

**`Filiales` est gardé par `DEC`, des deux côtés.** L'écran était sous `INST`
dans `routeur.tsx` ; il est passé sous `DEC`, comme la route. Les prescriptions
des organes de gestion sont des `engagement` d'origine `ORGANE_FILIALE` ([ADR
006](../architecture/006-un-seul-engagement.md)) — la matière du registre des
décisions — et le DG comme le CODIR portent `DEC` **sans** `INST` : garder par
`INST` fermait l'écran à ceux qui siègent dans ces organes.

## Les traitements nocturnes

| Tâche | Heure | Ce qu'elle fait |
|---|---|---|
| `relancer_les_engagements` | 2 h 30 | relance la structure pilote au-delà du seuil |
| `signaler_les_depots` | 2 h 45 | inscrit un événement par compte rendu manquant, **une seule fois** |
| `recalculer_agregats` | 3 h 30 | alimente `agregat_gouvernance_jour` |

Les relances passent avant les agrégats : un agrégat calculé après coup compte la
relance du jour, l'inverse la manquerait de vingt-quatre heures.

**Une relance automatique n'a pas d'auteur** — `engagement_observation.auteur_id`
est nullable depuis la migration `0004`. Personne ne l'a signée, et lui attribuer
un agent serait faux ; c'est déjà ce que le socle fait pour `relance.emetteur_id`.
Une contrainte remplace le `NOT NULL` : une observation sans auteur est
nécessairement une relance.

Seuil et intervalle sont en `parametre`, statut `hypothèse` —
[A16](../../../docs/questions-ouvertes.md), avec des valeurs propres au pilier :
rien ne dit qu'on relance une direction sur une décision du conseil au même
rythme que sur une activité de son plan.

## Le fichier

```
gouvernance/
  modeles.py     reflet du SQL
  lecture.py     les six registres, tous bornés au périmètre
  services.py    les écritures
  schemas.py     en camelCase
  api.py         16 routes sur /gouvernance
  taches.py      relances, dépôts en souffrance, agrégats
  tests/
    test_schema.py  les règles du moteur, et le filet de l'ADR 006
    test_api.py     ce que les routes refusent, et ce qu'elles ne montrent pas
```

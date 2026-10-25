# Module « courrier »

**État : livré pour tout ce qui ne dépend pas des étapes de circuit** — 17 août
2026. Registre, enregistrement, fiche, cotation, affectation, fiche de vie,
compteurs du menu.

**Ce qui reste dehors, et pourquoi.** `circuit_etape` est **vide** : le trajet
réel d'un courrier au Port n'a jamais été communiqué
([A24](../../../docs/questions-ouvertes.md#a24--quels-référentiels-métier-personne-na-t-il-encore-fournis-)).
Tout ce qui s'y ancre est donc absent — `instance_circuit`, `instance_etape`,
`validation`, la transmission, les relances automatiques, les escalades, et le
pilier départ. Les déclarer aurait promis un acheminement que rien ne peut
dérouler.

## Ce qui gouverne le module

### 1. La visibilité passe par `visibles()`, jamais par `restreindre()` seul

C'est le seul pilier dans ce cas, parce que c'est le seul dont un objet **circule
d'une structure à l'autre**. La règle du client, énoncée le 11 août 2026 :

> On voit ce à quoi on est rattaché — sa structure, plus ce sur quoi on a été
> coté ou désigné. Tout le reste est invisible, sauf permission explicite de
> consolidation.

`noyau.perimetre.portee.restreindre()` n'en tient qu'une : le rattachement.
`courrier/visibilite.py` tient les quatre, plus la serrure :

| Porte | Ce qu'elle ouvre |
|---|---|
| Session | le registre de sa session — c'est ce qu'est un registre |
| Rattachement | ce que porte sa structure, selon la portée |
| Cotation | ce courrier précis, même venu d'ailleurs |
| Désignation | ce qu'on suit ou ce qui nous est affecté, **hors structure** |

La quatrième porte — la session — n'est pas dans la phrase du client, et
l'[ADR 022](../architecture/022-le-registre-est-une-porte-de-visibilite.md) dit
pourquoi elle est indispensable : un courrier qui vient d'être enregistré n'est
coté à personne, et sans elle l'agent qui l'a saisi reçoit un 404 sur la fiche
vers laquelle son propre écran le redirige.

**La confidentialité n'est pas une porte, c'est une serrure**, posée **avant** les
quatre : la portée `toutes` consolide sans lever le secret.

Une exception, et une seule : **l'agent rattaché au registre confidentiel lit ce
registre**, même sans porter `CONF`. Aucun profil du socle ne cumule `ENR` et
`CONF` — sans cette exception, l'agent enregistrerait un courrier qu'il ne peut
plus relire, et le registre confidentiel serait intenable. Le rattachement y est
l'acte d'habilitation ; il est exclusif et administré. Voir
l'[ADR 024](../architecture/024-la-serrure-du-confidentiel-ne-ferme-pas-son-propre-registre.md),
qui complète l'ADR 022 sans la contredire.

Un courrier hors périmètre répond **404, jamais 403** — décision de cadrage D5.
Répondre « interdit » confirmerait l'existence du courrier et celle de son
expéditeur à qui n'a pas à les connaître.

### 2. L'étape est déduite, jamais stockée

Les étapes que le front affiche — `ENREGISTRE`, `COTE`, `AFFECTE`,
`EN_TRAITEMENT`, `EN_VALIDATION`, `CLOTURE` — résultent de l'existence d'une
cotation, d'une affectation, d'un traitement et de `statut_courrier`. Aucune
colonne ne les porte. C'est l'arbitrage n° 2 du pilier activités : stocker un état
qui résulte d'un calcul impose de le réécrire partout où l'une de ses sources
change, et garantit qu'un jour les deux se contrediront.

`TRANSMIS`, `SIGNE` et `PARTI` sont déclarées par le front et **jamais émises** :
les deux premières supposent une transmission, la troisième relève du départ.

### 3. Le numéro vient du moteur

Le déclencheur `courrier_numero` (BEFORE INSERT) lit `sequence_numerotation`,
l'incrémente **sous verrou de ligne** et compose `0001/2026`. Le service insère
`numero=""` et **relit** la ligne. Le prédire côté Python serait le seul moyen
d'en produire deux identiques.

Le numéro est unique **par session**, pas globalement : trois registres, trois
cahiers, et `0001/2026` peut exister trois fois.

`GET /courriers/contexte` **prédit** le numéro sans le consommer : réserver un
numéro à l'ouverture d'un formulaire aurait troué la séquence dès le premier
abandon de saisie, et un registre à trous ne se certifie plus.

### 4. `decide_par` n'est pas `saisi_par`

Le Directeur général cote, l'agent de session tape. Une colonne unique
attribuerait à l'agent une décision qu'il n'a pas prise, ce qui vide le journal de
sa valeur probante. Le journal porte les deux : `acteur` et `agit_pour`.

Deux permissions ouvrent la route de cotation pour cette raison — `COT` pour
l'autorité, `COT_DEL` pour l'agent qui saisit à sa place.

### 5. Le rang 1 est chef de file

`structureIds` est **ordonné**. Ce n'est pas une convention d'affichage : le rang
est écrit en base, le déclencheur `cotation_structure_chef_file` recopie le rang 1
sur `courrier.structure_chef_file_id`, et le registre trie dessus. Le front lit
`structuresCotees[0]` comme chef de file.

La **cotation pour suivi** est une seconde cotation, à une **personne** : elle
coordonne au-dessus du chef de file et rend compte au DG (A7, tranchée le
11 août 2026). C'est une table et non une colonne, parce qu'une désignation est
une période. Conséquence pratique : la relance lui part, pas au chef de file.

### 6. Toute écriture passe par `acteur()`

`courrier` et `cotation` sont historisées par le déclencheur
`historiser_champs()`, qui **refuse** l'écriture quand `app.utilisateur_id` n'est
pas posé. C'est une des rares règles que le moteur fait respecter tout seul.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `modeles.py` | sept modèles, **aucune table créée** — `SeparateDatabaseAndState`, ADR 003 |
| `visibilite.py` | les quatre portes et la serrure. **La pièce la plus sensible** |
| `lecture.py` | registre, fiche, chronologie, fiche de vie, indicateurs, et les tables `*_VERS_FRONT` |
| `services.py` | les règles d'écriture : enregistrer, coter, affecter |
| `schemas.py` | entrées / sorties, en camelCase |
| `api.py` | les routes, montées sur `/api/courriers` (plus `GET /api/compteurs`, à la racine) |

## Les routes

| Route | Garde |
|---|---|
| `GET /courriers`, `/indicateurs`, `/{id}`, `/{id}/fiche-de-vie` | `LEC` |
| `GET /courriers/contexte`, `POST /courriers` | `ENR` |
| `POST /courriers/{id}/cotations` | `COT` **ou** `COT_DEL` |
| `POST /courriers/{id}/affectations` | `AFF` |
| `GET /compteurs` | session seule — la garde est portée par la lecture, qui rend trois zéros sans `LEC` |

## Ce qui sort vide, et n'est pas un oubli

Application de l'[ADR 011](../architecture/011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) :
on rend ce qu'on mesure, on **nomme** ce qu'on ne mesure pas.

| Champ | Valeur | Pourquoi |
|---|---|---|
| `modeCotation` | `null` | La base oppose `directe` à `cascade` — une question de **hauteur**. Le front oppose `CASCADE` à `PARALLELE` — une question de **simultanéité**. `cascade` figure dans les deux listes et n'y veut pas dire la même chose : traduire aurait inventé la règle |
| `observations` | `[]` | Aucune table ne porte d'observation datée et signée. `courrier.observations` est un texte libre sans auteur — [A56](../../../docs/questions-ouvertes.md#a56--le-fil-dobservations-dun-courrier-na-pas-de-table) |
| `chronologie[].etat` | jamais `attendue` | Les étapes à venir se lisent dans `circuit_etape`, qui est vide (A24) |
| `variation`, `serie` | « Non mesuré », `[]` | La variation suppose une période de référence, la série un historique que rien n'archive |
| `delaiMoyenCotation` | « Non mesuré » quand rien n'est coté | « 0 h » se lirait « cotation instantanée » — la meilleure valeur possible là où il n'y en a aucune |

## Les vocabulaires

La base et le front ne parlent pas la même langue, et le piège est silencieux :
un `str` en face d'un `str` passe toutes les revues de schémas. **Une seule table
de traduction, dans `lecture.py`.**

| Notion | Base | Front |
|---|---|---|
| Sens | `arrive` / `depart` / `interne` | `ARRIVEE` / `DEPART` / `INTERNE` |
| Priorité | `URGENT` / `ELEVEE` / `NORMALE` / `BASSE` | `NORMALE` / `URGENTE` (`TRES_URGENTE` jamais émis) |
| Session | `arrive` / `confidentiel` | `ARRIVE` / `CONFIDENTIEL` |

La traduction des priorités est **volontairement lossy** et préserve le sens des
mots : la case « Urgent » écrit `URGENT` et se relit « Urgent », jamais « Très
urgent » —
[A55](../../../docs/questions-ouvertes.md#a55--quatre-niveaux-durgence-en-base-une-case-à-cocher-à-lécran).
Voir aussi [les pièges](../../../docs/pieges.md).

## Les migrations

Trois, toutes en **état seul** : elles ne créent aucune table, les tables
existent depuis `sql/0001_socle.sql` (ADR 003).

- `courrier.0001_initial` — **ne pas relancer `makemigrations courrier` à vide** :
  la migration serait aplatie et tenterait de créer les tables une seconde fois.
- `noyau.0014_jour_ferie` — écrite à la main, `makemigrations noyau` étant
  interdit. La table reste **vide** : un calendrier de fériés inventé décalerait
  silencieusement toutes les échéances. À administrer.
- `noyau.0015_recherche_correspondant` — idem, pour le vecteur plein texte.

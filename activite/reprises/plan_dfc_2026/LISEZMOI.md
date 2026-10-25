# Reprise du plan d'actions 2026 de la DFC

Le classeur `PLAN_ACTIONS_2026_DFC.xlsx` porte 36 activités décrites dans le
vocabulaire **budgétaire** de l'institution — programme, action, activité,
code à sept chiffres. Le modèle, lui, décrit un plan **stratégique** rattaché à
un axe. Les deux parlent du même objet sans employer les mêmes mots : c'est
tout l'écart que cette reprise comble.

**Reprise exécutée le 9 septembre 2026** : 36 activités, 96 tâches et
34 indicateurs versés dans le plan DFC 2026, en brouillon. Références
`PAA-DFC-01` à `PAA-DFC-36`. Ce qui suit décrit comment elle a été faite, et ce
qui reste à compléter à l'écran.

## Ce que contient ce répertoire

| Fichier | Rôle |
|---|---|
| `correspondances.py` | Les règles de conversion, chacune marquée `SUR` ou `A_VALIDER` |
| `extraire.py` | Lit le classeur, applique les règles, écrit `activites.csv` |
| `activites.csv` | Le tableau versé. C'est lui que l'import lit |
| `importer.py` | Verse le tableau par l'API — `--reel` pour écrire |

L'import ne lit jamais le classeur. Un tableur reste un document de travail :
il change sans prévenir, et une reprise doit pouvoir être rejouée à l'identique
six mois plus tard.

L'import passe par l'**API**, non par l'ORM : ce sont les règles de
`services.py` qui doivent s'appliquer — périmètre, journal des événements, code
d'activité posé par le déclencheur, plan créé s'il n'existe pas.

## La marche à suivre

```bash
python activite/reprises/plan_dfc_2026/extraire.py ~/Téléchargements/PLAN_ACTIONS_2026_DFC.xlsx
export MOT_DE_PASSE_IMPORT='…'          # compte focal.dfc
python activite/reprises/plan_dfc_2026/importer.py           # simulation
python activite/reprises/plan_dfc_2026/importer.py --reel    # écrit
```

Le mot de passe passe par l'environnement : la ligne de commande figure dans
l'historique du shell et dans `ps`.

**L'import est reprenable.** Il lit le plan avant d'écrire et saute les
activités dont l'intitulé y figure déjà : une exécution interrompue se relance
sans créer de doublon. Le prix de cette simplicité : deux activités homonymes
ne peuvent pas coexister dans le plan.

Les colonnes `*_origine` d'`activites.csv` conservent la valeur du classeur en
regard de la valeur convertie : elles ne servent qu'à la relecture et l'import
les ignore.

## Ce qui a été décidé, et ce qui reste à compléter

Arbitrage de William du 9 septembre 2026 : **rien ne bloque l'import.** Ce qui
ne se rapproche pas est laissé vide et se complète depuis l'application. La
colonne `a_completer` du tableau nomme, ligne à ligne, ce qui reste à saisir.

Il faut en dire le prix : une activité importée avec un axe proposé et sans
structure associée **a l'air complète**. Rien à l'écran ne la distingue d'une
activité vérifiée. C'est `activites.csv` qui garde la trace de ce qui a été
deviné, et lui seul.

1. **L'axe de chaque activité — proposé, jamais lu.** Le classeur ne le donne
   jamais. Répartition retenue : `Port attractif et performant` pour 30 lignes
   (gestion financière, comptable, recouvrement), `Port innovant et
   responsable` pour 4 (déontologie, dématérialisation ×2, finance verte),
   `Port compétitif et fluide` pour 2 (dettes croisées et emprunts du
   programme 2, qui portent les infrastructures). La règle est écrite par
   activité budgétaire dans `correspondances.py` ; elle se modifie à l'écran,
   activité par activité.

2. **Quatre sigles absents de l'organigramme, tranchés le 10 septembre 2026**
   par William, sur le contexte de leur ligne — tâche, indicateur, structures
   citées à côté — et non sur le sigle seul : `BC` → `DCG-ACB` (la ligne parle
   de rapports de contrôle), `CCODRCV` → `DQDD-DDR` (finance verte), `DCOA` →
   `DAJ-RF` (plan de recouvrement). `SCO` redit `DFC-CPT`, déjà associé par
   `DpCFI` sur la même ligne : il n'ajoute rien. Ces trois rattachements
   restent des lectures, marquées `A_VALIDER`. Les autres résolus
   comprennent les départements de la DFC (`DpCFI` → `DFC-CPT`, `DpCREC` →
   `DFC-FIN-CR`, `DpFOT`/`DPOFT` → `DFC-FIN-OFT`, `DIVF` → `DFC-FIN`), `DEX` →
   `DEXP` et `DAP` → `DAPC`. Onze activités n'ont aucune structure associée : le
   classeur n'y nomme que la DFC, qui est la porteuse et ne se répète pas.

3. **Onze périodes qui sont des rythmes** et non des périodes — « Mensuel »,
   « Au jour le jour », « Au plus tard le 15 de chaque mois », « Annuel »,
   « semestrielle ». Elles couvrent l'exercice entier : `date_debut` et
   `date_fin` ne savent pas dire « tous les mois ». La récurrence, si elle
   compte, se porte en tâches.

4. **La ligne 13 (`3207028`) n'a aucune période** — le classeur s'arrête à la
   colonne de la valeur cible. Elle couvre l'exercice entier.

5. **La ligne 25 (`3208015`, notation financière)** porte `1 / 1 / 2` en cible et
   `Nov / Fev-Mars / Avril-Mai` en période : trois jalons dans deux cellules,
   pour un champ décimal unique. L'activité est créée, **l'indicateur ne l'est
   pas** — un seul à 4, ou trois distincts ? La fiche ne dit pas la même chose
   selon le choix. La ligne 15 (`3207037`, dématérialisation du système de
   paiement) n'a **aucune cible** au classeur. Ce sont les deux seules
   activités sans indicateur : `PAA-DFC-15` et `PAA-DFC-25`.

6. **La colonne « INDICATIONS » n'a pas d'équivalent au modèle.** Elle vaut
   « 100% » sur dix-sept lignes, du texte libre sur deux (« Action
   permanente », « tous les comptes banquiers »), « / » sur une — et elle
   **contredit parfois la valeur cible** : la ligne 17 porte `100%` en
   indication et `9` en cible. Elle est reportée telle quelle dans les
   résultats attendus, précédée de « Indications du classeur : », sans
   conversion. Son sens reste à préciser avec la DFC.

7. **Quatre lignes sans objectif** (n° 24, 26, 31, 32), et le **numéro 17 est
   employé deux fois** dans le classeur — le 16 manque. Sans incidence sur
   l'import, qui ne s'appuie pas sur cette numérotation, mais à signaler à la
   DFC.

## Ce que l'import ne pose pas

- **Le point focal** de chaque activité. La colonne du classeur nomme des
  structures, pas des agents ; le déduire du compte qui importe ferait de
  `focal.dfc` le responsable des 36 (ADR 020, ADR 047).
- **Les résultats attendus**, absents du classeur.
- **L'état de référence des indicateurs** : le classeur donne l'état des lieux
  au niveau de l'activité, pas de l'indicateur.
- **Le poids des tâches**, tous à 1 : le classeur ne hiérarchise pas. Tant
  qu'ils sont égaux, l'avancement calculé est la moyenne des tâches faites.

## Sept écarts entre le classeur et le modèle

Ils ne relèvent pas de la reprise mais de la conception. Ils sont notés ici
parce que c'est en versant les données qu'ils se sont vus.

| | Le classeur | Le modèle |
|---|---|---|
| **Rattachement** | hiérarchie budgétaire : programme → action → activité → code à 7 chiffres | trois axes stratégiques |
| **Période** | souvent un **rythme** (« mensuel », « au jour le jour ») ou une suite de jalons | un intervalle continu `debut`/`fin` |
| **Nature** | document de **programmation** : ce qui est prévu | outil de **suivi** : avancement, feu, retard, relance |
| **Cible** | parfois non chiffrable (`1 / 1 / 2`, `/`) et doublée d'une colonne « INDICATIONS » qui la contredit | `valeur_cible` décimale, taux d'atteinte calculé |
| **Responsables** | une colonne mêlant directions, départements et mentions collectives | structure porteuse + structures associées + point focal |
| **Budget** | colonne sous le chapeau « **Prévisions** », renseignée sur 17 lignes de 36 | `budget_valide` — un montant *arrêté*, pas une prévision |
| **Tâches** | texte numéroté dans une cellule, sans échéance ni poids propres | objets datés, pondérés de 1 à 10, avec responsable |

Trois conséquences pratiques :

1. **Le code budgétaire est perdu en base.** `Activite.code` est posé par
   déclencheur (`PAA-DFC-01`…) ; `3207011` ne subsiste que dans `activites.csv`.
   C'est le lien avec la nomenclature ministérielle qui se coupe.
2. **`budget_valide` a reçu une prévision.** Le nom du champ dit « validé ».
   Tant que le contrôle de gestion n'a pas arrêté ces montants, la colonne
   ment sur son propre sens.
3. **Le classeur n'a pas de cycle de vie.** Le modèle en a un — brouillon,
   soumis, validé ou retourné par le contrôle de gestion (§15), avec fiche de
   vie, suspension et relance. Rien de cela n'existe côté tableur : c'est le
   gain de la bascule, et ce que la DFC devra apprendre à faire.

## Le point de retour

L'import a été fait sur la préproduction, qui porte des données réelles. Le
point de retour est la sauvegarde `~/sauvegardes-suivi/base-2026-09-09-1911.dump`,
antérieure à l'écriture. Un plan en brouillon se corrige toutefois à l'écran :
la restauration n'a de sens qu'en cas d'erreur de masse.

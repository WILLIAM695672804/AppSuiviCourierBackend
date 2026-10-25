# Les règles du pilier « activités »

Ce document sépare deux choses que le code ne distingue pas tout seul : **ce qui
est décidé** et **ce qui est supposé**.

À lire avant de toucher au calcul d'un état, d'un retard ou d'un taux.

Décision de fond : [ADR 005](../architecture/005-regles-parametrables.md).
Arbitrages attendus : [questions ouvertes A1–A6](../../../docs/questions-ouvertes.md).

---

## Ce qui est décidé

### Les axes stratégiques — référentiel fermé

Trois axes, arrêtés (communication de la Direction générale, 11 août 2026).
Chaque activité se rattache à **un** axe.

1. Port attractif et performant à l'aide des services sûrs et de qualité
2. Port compétitif par la fluidité du passage portuaire à travers l'amélioration
   et la densification de l'outil de production
3. Port innovant, digital et sociétalement responsable

`parametre` → `activite.axes_strategiques`, `statut = 'acte'`.
Référentiel front : `frontend/src/lib/axesStrategiques.ts`.

**Jamais de champ texte libre pour un axe.** Le cahier des charges (§15)
demandait le rattachement sans donner la liste ; l'axe était donc saisi
librement, et tout regroupement par axe était faux — quatre orthographes pour un
même axe.

### Qui déclare, qui arbitre, qui relance

Trois permissions, trois rôles distincts. C'est la découpe qui gouverne les
écrans comme les routes.

| Permission | Qui | Ce qu'elle ouvre |
|---|---|---|
| `ACT_SAI` | la structure | déclarer et mettre à jour ses activités, ses tâches, ses relevés |
| `DEC` | l'autorité | suspendre une activité, y rattacher une instruction, la lever |
| `REL` | la DSR | relancer une structure en retard |
| `ACT_VAL` | la DCG | valider ou renvoyer un plan d'actions annuel |
| `ACT_LEC` | — | lire, dans les limites de son périmètre |

Une structure ne se suspend pas elle-même et ne se relance pas elle-même.

### Une activité suspendue n'accepte plus d'avancement

Une mise à jour d'avancement sur une activité suspendue est refusée en **409**.
La suspension n'est pas un statut décoratif : elle arrête la déclaration.

Ce que la suspension ne fait **pas** : geler le compteur de retard. Voir
[A6](../../../docs/questions-ouvertes.md).

### La visibilité

Une activité se voit par sa structure, selon la portée de la session. Rien de
particulier au pilier — c'est la règle générale, appliquée par `restreindre()`.
Le champ `structuresAccessibles` renvoyé au front sert à peupler un sélecteur,
**pas** à protéger quoi que ce soit.

---

## Ce qui est supposé

Les quatre règles ci-dessous **n'ont aucune source documentaire**. Le cahier des
charges dit quoi suivre (§15–§20), jamais comment le calculer. Elles ont été
inventées par la conception, et elles sont marquées `statut = 'hypothese'` en
base pour qu'on ne l'oublie pas.

Le code les lit par `noyau/parametres/service.valeur(cle, defaut)`. **Aucune
n'est écrite en dur.**

### H1 — L'avancement attendu · `activite.mode_avancement_attendu`

Valeur : `lineaire_jours_ouvres`.

À une date donnée, l'avancement « attendu » est interpolé linéairement entre la
date de début et l'échéance, en jours ouvrés.

Ce que cela suppose et qui n'a jamais été validé : qu'une activité progresse
régulièrement. Une activité à jalons (une étude, un marché) ne progresse pas
ainsi — elle reste à 10 % puis saute à 80 %, et le calcul l'affiche en retard
tout du long.

**À trancher par :** DSR et contrôle de gestion.

### H2 — Le seuil de retard · `activite.seuil_retard_points`

Valeur : `10`.

Une activité est « en retard » quand `avancement < avancement_attendu - 10`.

Le nombre est arbitraire. Il est le même pour une activité de deux semaines et
pour une activité annuelle, ce qui est difficilement défendable.

**À trancher par :** DSR.

### H3 — La criticité · `activite.criticite_exige_contrainte`

Valeur : `true`.

Une activité est **critique** quand elle est en retard **et** qu'elle porte au
moins une contrainte échue — instruction non levée dont l'échéance est passée,
ou tâche non faite dont l'échéance est passée.

Une activité suspendue ou réalisée n'est jamais critique.

C'est la définition la plus lourde de conséquences : le cockpit de la Direction
générale et les alertes en dépendent. Mise en œuvre de référence :
`recalculerCriticite()` dans `frontend/src/lib/demo/donneesActivite.ts`, à
porter côté backend.

**À trancher par :** Direction générale — c'est elle qui reçoit le cockpit.

### H4 — Le taux d'atteinte d'un indicateur · `activite.mode_taux_indicateur`

Valeur : `reference_vers_cible`. Le taux mesure la progression depuis la valeur
de référence vers la cible.

**Défaut connu et non corrigé :** les indicateurs qui doivent **baisser** (un
délai de traitement, un taux d'erreur) ne sont pas traités. La formule leur
donne aujourd'hui des valeurs fausses, sans que rien ne le signale.

**À trancher par :** contrôle de gestion.

---

## Le cycle du plan d'actions annuel

Également sans source, et traité à part parce qu'il touche à des états
persistés : brouillon → soumis → validé / renvoyé, validation par la DCG, pas
de mécanisme d'avenant.

Ce qui n'est pas décidé : peut-on revenir en arrière ? un plan validé se
modifie-t-il en cours d'année, et sous quelle forme ? Voir
[A5](../../../docs/questions-ouvertes.md) — c'est celle dont la réponse tardive
coûtera le plus cher, parce qu'un état de plus est une colonne, des transitions,
des écrans et des droits.

---

## Ajouter une règle paramétrable

```sql
INSERT INTO parametre (cle, libelle, valeur, type_valeur, domaine,
                       statut, source, a_trancher_par)
VALUES ('activite.ma_regle', 'Ce qu''elle décide', '3', 'entier', 'activite',
        'hypothese', NULL, 'DSR');
```

La base refuse une hypothèse sans `a_trancher_par` : une hypothèse dont personne
n'est chargé n'est jamais tranchée — c'est exactement ce qui est arrivé aux
quatre ci-dessus.

Puis, dans le même diff : une entrée dans
[questions ouvertes](../../../docs/questions-ouvertes.md), et une ligne ici.

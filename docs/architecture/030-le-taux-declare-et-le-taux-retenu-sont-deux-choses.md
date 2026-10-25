# 030 — Le taux déclaré et le taux retenu sont deux choses

*Statut : acceptée — 25 août 2026*

## Contexte

L'exigence, telle qu'elle a été posée :

> La structure déclare son avancement (pourcentage + justification dans
> l'observation qui alimente la « Fiche de vie »), mais seule la DSR dispose du
> droit de modifier ou de recalibrer ce pourcentage si les réalisations ne sont
> pas justifiées.

Le code livré en tenait la première moitié et pas la seconde.

**Ce qui tenait.** `POST /activites/{id}/avancement` sous `ACT_SAI`, borné au
périmètre, et l'observation inscrite au journal — donc à la fiche de vie
(§18), qui n'est pas une table mais la suite des événements de l'objet.

**Ce qui ne tenait pas.**

1. L'observation était **facultative** (`observation: str = ""`). Un avancement
   pouvait être déclaré sans un mot.
2. Le profil `DSR` ne porte pas `ACT_SAI` — il porte `LEC, REL, STAT, IMP,
   ADM_STR, ACT_LEC, ACT_VAL, DEC, INST, DISPO, SCORE, SCORE_ADM, COCKPIT,
   DOS_LEC`. La DSR lit, relance, valide les plans ; elle ne peut pas toucher un
   pourcentage.
3. Aucune route de recalibrage n'existait, et il n'aurait pas suffi d'en écrire
   une : `avancement_calcule` est réécrit par le déclencheur
   `maj_avancement_activite()` à chaque changement d'état de tâche. Un
   recalibrage posé dans cette colonne aurait disparu à la première tâche cochée.

Et un défaut voisin, découvert en instruisant celui-ci : `tache.poids` existait
en base, le déclencheur en tenait compte, mais `SaisieTache` ne le portait pas.
Toute tâche créée par l'application pesait `1`. La pondération existait sans
jamais s'exercer — « rédiger le compte rendu » comptait autant que « livrer le
système », ce que le poids existe précisément pour éviter.

## Décision

**Deux colonnes, et une troisième générée.**

| colonne | ce qu'elle dit |
|---|---|
| `avancement_calcule` | ce que la structure déclare, ou ce que ses tâches produisent. Inchangée, et jamais écrite par la DSR |
| `avancement_recalibre` | ce que la DSR retient. `NULL` tant qu'elle n'a pas contredit la structure |
| `recalibrage_motif` | pourquoi. Obligatoire dès que le précédent est posé — `CHECK`, comme `paa_retour_motive` |
| `avancement_retenu` | **générée** : `COALESCE(avancement_recalibre, avancement_calcule)` |

La colonne générée est le point d'appui de la décision, pas un raffinement.
Sans elle, les six consommateurs de l'avancement — ligne de registre, corbeille
des plans, `v_activite_etat`, matrice de performance, mesures de pilotage,
relance automatique — auraient chacun écrit son propre `COALESCE`, et il aurait
suffi qu'un seul l'oublie pour qu'un écran continue d'afficher un taux que la
DSR a rejeté. Ils lisent tous `avancement_retenu`, et le moteur seul le calcule.

**La déclaration ne s'écrase pas.** La DSR pose un second taux à côté du
premier ; elle ne réécrit pas ce que la structure a dit. C'est ce qui rend le
désaccord lisible — l'effacer au moment où il se produit aurait retiré au
recalibrage la seule chose qui le rend contestable.

**La justification devient obligatoire.** Le §15 demande « pourcentage +
observation ». Un taux déclaré sans un mot ne se conteste pas : il se subit.
C'est aussi la matière sur laquelle la DSR s'appuie pour recalibrer.

**Une permission neuve, `ACT_REC`, au seul profil `DSR`.** Pas `ACT_VAL` : le
contrôle de gestion la porte aussi, et l'exigence dit *seule la DSR*. Une
permission qui donnerait le geste à deux profils ne serait pas la règle
demandée, ce serait une autre règle. Elle reste déléguable (ADR 002) — c'est le
mécanisme prévu pour l'absence, borné et tracé — mais elle ne part jamais avec
un autre geste.

**Le poids se saisit.** `SaisieTache.poids`, de 1 à 10, affiché dans la liste
des tâches et au moment de cocher. Le plafond n'est pas de prudence : au-delà,
une tâche emporte à elle seule l'avancement et les autres cessent de compter.

**Le recalibrage tient jusqu'à sa levée**, y compris si la structure redéclare
entre-temps. Sinon il suffirait de redéclarer pour se donner raison. La
contrepartie est réelle et assumée — une activité qui progresse vraiment reste
plafonnée tant que la DSR n'a pas levé. Voir
[A66](../../../docs/questions-ouvertes.md).

## Conséquences

- Le score d'une structure, son feu et son rang tiennent compte du recalibrage :
  c'est le but, et c'est aussi ce qui en fait un geste lourd.
- Le responsable de l'activité est notifié à la pose comme à la levée. Le lui
  laisser découvrir sur son tableau de bord serait la meilleure façon de
  transformer un arbitrage en incident.
- La fiche de vie porte un type propre, « Recalibrage », et non « Modification » :
  c'est le seul geste où une autorité extérieure contredit la structure, et le
  confondre avec une modification ordinaire le rendrait invisible.
- Une activité suspendue ne se recalibre pas davantage qu'elle ne se déclare.
  Le déclencheur `refuser_avancement_si_suspendue()` surveillait
  `avancement_calcule` seul ; il surveille les deux colonnes. Sans quoi le §19
  se rouvrait par la fenêtre.
- `avancement_retenu` est déclarée `GeneratedField` côté Django. Un
  `DecimalField` ordinaire serait parti dans chaque `UPDATE` et PostgreSQL
  l'aurait refusé — même piège que `EngagementStructure.pilote`.
- Les tâches existantes gardent leur poids `1` : la colonne avait ce défaut, et
  rien ne permet de deviner rétroactivement ce que chacune aurait dû peser.

## Alternatives écartées

**Laisser la DSR écrire `avancement_calcule`.** La plus simple, et elle détruit
la seule chose qui rend le recalibrage utile : savoir ce que la structure avait
déclaré. Le désaccord devient invisible le jour même où il se produit.

**Une table `activite_recalibrage`.** Elle donnerait l'historique — mais le
journal le donne déjà, événement par événement, avec l'acteur et les deux taux
dans `donnees`. Une table de plus pour une chronologie qui existe ailleurs
aurait fait deux vérités à tenir d'accord.

**Réutiliser `ACT_VAL`.** Le contrôle de gestion valide les plans d'actions ;
il ne contredit pas une structure sur ses réalisations. Deux gestes, deux
permissions.

**Calculer `COALESCE` chez chaque lecteur.** Six endroits, six occasions
d'oublier, et l'oubli ne produit aucune erreur — juste un écran qui affiche un
taux rejeté.

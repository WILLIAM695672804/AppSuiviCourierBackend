# 010 — La matrice de scoring se recalcule, elle ne se stocke pas

*Statut : acceptée — 13 août 2026*

## Contexte

Le §2 définit la matrice de scoring administratif comme un agrégat mensuel de
ce qui se passe ailleurs : « les résultats liés à l'exécution des activités, au
traitement du courrier et des dossiers, ainsi qu'à la conformité aux rituels ».
Elle produit un classement des structures et une évaluation globale de chacune.

Un agrégat mensuel appelle naturellement une table : une ligne par structure et
par mois, alimentée par une tâche de fin de mois. C'est la forme habituelle, et
elle a un avantage réel — la lecture devient triviale et l'historique est figé.

Trois faits du dépôt s'y opposent :

1. **Les sources se corrigent après coup.** Une activité mal saisie est
   rectifiée le mois suivant ; une obligation déposée hors ligne est
   enregistrée avec retard. Le score calculé le 1er ne vaut plus le 15.
2. **Le pilier courrier n'existe pas.** Un des trois critères n'a aucune
   source, et n'en aura pas avant plusieurs livraisons.
3. **La pondération est administrée** (`critere_matrice.poids`). La DSR peut
   décider demain que les rituels comptent double. Tout l'historique stocké
   deviendrait alors incomparable avec le présent, sans que rien ne le signale.

## Décision

La matrice, le classement et l'historique des douze mois se **calculent à
chaque lecture**, depuis les tables sources. Aucune table ne stocke un score,
un rang ou une moyenne.

Deux corollaires, portés par `performance/matrice.py` :

- un critère sans source mesurable rend `None`, et il est **retiré du score
  global après renormalisation des poids** — il ne vaut pas zéro ;
- le rang du mois précédent est **recalculé**, pas lu.

## Conséquences

- Un chiffre affiché ne peut jamais contredire sa source : il n'existe pas
  d'endroit où une seconde vérité pourrait se déposer.
- Une correction rétroactive est prise en compte immédiatement, y compris sur
  l'historique — ce qui est le comportement attendu d'un tableau de bord de
  suivi, et non d'un registre comptable.
- Le coût est un second passage sur les mêmes requêtes pour le mois précédent,
  et douze pour la courbe d'une fiche. Sur une dizaine de structures et des
  requêtes agrégées, c'est négligeable.
- Il n'existe aucune tâche de fin de mois à surveiller, donc aucun mois qui
  manquerait parce que la tâche n'a pas tourné.
- **Un score ne peut pas être gelé.** Si l'institution décide un jour de
  publier un classement officiel opposable, il faudra le figer explicitement —
  et ce sera un autre objet que la matrice, avec sa propre table et sa propre
  date d'arrêté.

## Ce qui invaliderait cette décision

- Le nombre de structures classées dépasse la centaine, ou le calcul d'une
  fiche demande plus d'une seconde. La matrice deviendrait alors un candidat
  légitime à une vue matérialisée rafraîchie — ce qui reste un calcul, pas un
  stockage de résultat métier.
- L'institution donne au classement mensuel une portée statutaire (prime,
  notation, décision opposable). Un chiffre opposable doit être arrêté à une
  date, et un arrêté se stocke.

## Alternatives écartées

**Une table `score_mensuel` alimentée en fin de mois.** Écartée : elle crée une
seconde vérité que rien ne resynchronise, et un poids modifié rendrait
l'historique incomparable en silence.

**Un cache applicatif avec invalidation.** Écarté : l'invalidation devrait
suivre les écritures de trois piliers, dont un qui n'existe pas encore. Un
cache qu'on oublie d'invalider est exactement le problème qu'on cherchait à
éviter, avec une couche de plus.

**Compter zéro pour le critère courrier.** Écarté : toute l'institution
plafonnerait aux deux tiers de sa note pour un module non livré, et le
classement serait faux tout en paraissant complet. « On ne sait pas » n'est pas
« c'est nul ».

# 011 — Le pilotage rend ce qu'il mesure et nomme ce qu'il ne mesure pas

Statut : acceptée — 13 août 2026

## Contexte

Le pilotage restitue ce que les autres piliers enregistrent. Deux d'entre eux
n'existent pas : le courrier et les dossiers. Or la moitié des restitutions
décrites au descriptif fonctionnel les cite — le §3.11 demande des « analyses
croisées entre exécution des activités, traitement du courrier, avancement des
dossiers et respect des délais », soit quatre mesures dont deux sont hors
d'atteinte à ce jour.

Le contrat que le front portait jusqu'ici typait ces mesures en `number`. Un
serveur qui le respecte n'a que trois façons de répondre :

1. **rendre `0`** — l'écran affiche « 0 % de courriers traités dans le délai »,
   ce qui se lit comme une défaillance grave, se commente en séance, et
   n'appelle aucune correction puisque rien ne la soutient ;
2. **omettre le bloc** — l'écran n'a plus le même nombre de cartes chez l'un et
   chez l'autre, ce qui se lit comme une panne d'affichage ;
3. **rendre une valeur plausible** — c'est-à-dire inventer.

Aucune des trois n'est acceptable dans un outil dont le but est de fonder des
décisions de direction. Le problème n'est pas passager : il se reposera à
chaque mesure absente — une structure sans activité commencée, un mois sans
relevé de chenal, une cible du programme jamais fixée.

## Décision

**Une mesure absente sort à `null`, jamais à zéro, et le serveur dit pourquoi.**

Quatre règles en découlent :

1. **`null` dans le contrat.** Tout champ portant un taux, une moyenne ou une
   cote est nullable. Les **comptages** ne le sont pas : « zéro décision en
   retard » est une mesure, pas une absence de mesure.
2. **Un libellé, pas un vide.** La valeur affichée est produite par le serveur
   — `"Non mesuré"` — et accompagnée d'une raison en clair (« le pilier
   courrier n'est pas en service »). Le front ne recompose rien : la mise en
   forme d'une absence est une décision métier.
3. **Les agrégats se renormalisent.** Moyennes, dispersions et feux ne portent
   que sur les mesures disponibles, exactement comme la matrice renormalise ses
   poids (ADR 010). Deux `null` traités comme deux zéros auraient rendu toute
   l'institution médiocre, avec un écart-type rassurant et faux.
4. **L'absence est dite, pas tue.** Chaque écran énumère ce qu'il ne mesure pas
   — champ `nonMesure`, ligne « Non mesuré » dans les indicateurs, phrase
   explicite dans la note de synthèse. Un tableau de bord qui passe le courrier
   sous silence le fait croire sain.

La règle vaut au-delà des piliers manquants. Une variation contre une mesure
absente sort à `null` et le front n'affiche aucune flèche ; une cible non fixée
donne un feu « inconnu » et non « vert » ; un mois sans relevé ne produit aucun
point sur la courbe plutôt qu'un point à zéro ; une structure dont aucun critère
n'est renseigné n'est pas « à risque » au cockpit.

## Conséquences

* **Le contrat front a dû changer.** Plusieurs champs typés `number` sont
  devenus `number | null`, et les pages qui les affichent ont été reprises. Le
  coût est réel et il est payé une fois.
* **Le jour où le pilier courrier entrera**, il y aura peu à modifier :
  `mesures.traitement_courrier()` et `mesures.instruction_dossiers()` sont deux
  fonctions qui rendent `None` et qui nomment la mesure manquante à l'endroit
  où les autres sont calculées. Le calcul les remplacera ; les écrans n'auront
  pas à changer.
* **Les écrans sont plus bavards.** Une carte « Non mesuré » occupe autant de
  place qu'une carte pleine. C'est voulu : le Directeur général doit savoir ce
  que son tableau de bord ne lui dit pas, et cette information a la même valeur
  que les autres.
* **Un test par absence.** Plusieurs tests de `pilotage/tests/` ne vérifient
  rien d'autre que « ceci n'est pas zéro ». C'est la seule régression de ce
  dossier qui ne se voit pas à l'écran.

## Ce qui invaliderait cette décision

* **L'arrivée des piliers courrier et dossiers**, si elle rendait tous les
  champs mesurables. La règle 1 resterait utile pour les cas ponctuels — une
  structure sans activité, un mois sans saisie — mais la refonte des contrats
  qui l'a motivée n'aurait plus lieu d'être décidée deux fois.
* **Une exigence contraire de la Direction générale**, qui préférerait un écran
  homogène quitte à ce qu'il taise ses trous. Ce serait une décision de
  gouvernance, pas d'architecture : elle devrait être écrite, et cet ADR
  remplacé.

## Alternatives écartées

* **Rendre zéro et documenter la convention.** Écartée : la convention n'est
  lue que par ceux qui écrivent le code, jamais par ceux qui lisent l'écran en
  séance. Un chiffre faux affiché à un directeur est un chiffre faux.
* **Omettre les champs manquants du contrat.** Écartée : le front devait alors
  décider quoi afficher à leur place, c'est-à-dire décider seul de ce qui est
  mesuré. La décision remonte au serveur, qui est le seul à le savoir.
* **Ne pas ouvrir les écrans tant que les piliers manquent.** Écartée : les
  mesures disponibles — activités, rituels, décisions, exploitation — sont
  utiles dès aujourd'hui, et un outil qu'on n'ouvre pas n'est jamais adopté.
* **Une valeur sentinelle (`-1`).** Écartée sans discussion : elle se retrouve
  tôt ou tard dans une moyenne.

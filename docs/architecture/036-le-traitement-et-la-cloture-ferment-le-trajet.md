# 036 — Le traitement et la clôture ferment le trajet

27 août 2026.

## Contexte

L'[ADR 034](034-le-trajet-du-courrier-n-est-pas-un-circuit.md) a établi que le
trajet du courrier arrivé tient en sept étapes et qu'aucune n'est paramétrable.
Six d'entre elles avaient un geste. La septième n'en avait pas, et les deux qui
la précèdent non plus :

- `EN_TRAITEMENT` et `RESTITUE` se déduisaient de la table `traitement`, qu'**aucune
  route n'écrivait** ;
- `CLOTURE` se déduisait de `courrier.statut_courrier`, qu'**aucune route ne
  faisait passer à `cloture`**.

Autrement dit : le trajet était décrit, mais il n'allait pas jusqu'au bout. Un
courrier accepté restait accepté pour toujours. Rien ne le disait à l'écran —
c'est le même défaut silencieux que le 404 lu comme une liste vide.

Le coût se voyait ailleurs, et c'est ce qui a fait remonter le sujet : sept
écrans du pilotage et de la performance affichaient « Le pilier courrier n'est
pas en service ». C'était exact. Un délai qui ne s'arrête jamais ne se mesure
pas.

## Décision

**Quatre gestes ferment le trajet, et la clôture est définitive.**

| Geste | Route | Permission |
|---|---|---|
| L'agent écrit son traitement | `POST /courriers/{id}/traitement` | `TRA` |
| Il le restitue au responsable | `POST /courriers/{id}/restitution` | `TRA` |
| Le responsable le lui retourne | `POST /courriers/{id}/traitements/{id}/retour` | `CLO` |
| Le responsable clôture | `POST /courriers/{id}/cloture` | `CLO` |

Un traitement par agent et par courrier, repris à chaque enregistrement. Une
ligne `traitement_version` est figée **à chaque restitution**, jamais à
l'enregistrement du brouillon.

`valider` et `transmettre` sont **retirés** de la table des actions, côté serveur
comme côté front : il n'y a ni visa ni transmission sur le courrier arrivé.

## Conséquences

- **La décharge trouve son appelant.** `exiger_la_decharge()` avait été écrite la
  veille sans personne pour l'appeler ([ADR 035](035-l-agent-cote-signe-avant-de-traiter.md)) ;
  `rediger()` l'appelle. C'était exactement l'idée : écrire la règle là où elle
  serait trouvée, plutôt que dans un journal de bord où elle aurait été oubliée.
- **Un brouillon n'est visible que de son auteur.** Un responsable qui lirait
  par-dessus l'épaule jugerait un texte que l'agent n'a pas fini d'écrire. Les
  traitements restitués, eux, suivent le cloisonnement ordinaire
  ([ADR 032](032-un-evenement-appartient-a-une-structure-ou-a-personne.md)).
- **La clôture est un jalon public**, pas un geste interne : sans cela, le bureau
  d'ordre central et la DSR verraient encore un courrier ouvert que plus
  personne ne traite.
- **Elle n'exige pas de traitement.** Beaucoup de courriers arrivent pour
  information. En exiger un aurait forcé l'agent à écrire « pour information »
  pour pouvoir refermer. Un brouillon en cours, lui, arrête le geste — et un
  second appel passe outre, en connaissance de cause.
- **Elle valide les traitements restitués.** C'est ce que le responsable dit en
  clôturant ; un statut `valide` posé par un autre geste aurait demandé un
  troisième bouton pour la même décision.
- **Sept écrans se remplissent.** `performance.matrice._critere_courrier`,
  la fiche structure, le tableau de bord, les statistiques, la note de synthèse,
  le rapport et la vue de direction mesurent au lieu d'annoncer une absence. La
  constante `SANS_COURRIER` disparaît au profit de `SANS_COURRIER_CLOS`, qui ne
  dit plus « pas d'outil » mais « pas encore de matière ».
- **La date de clôture se lit au journal**, pas sur le courrier : le socle ne
  porte pas de colonne `cloture_le`, et `modifie_le` bouge à chaque correction de
  saisie. L'événement, lui, ne bouge plus (ADR 012). Le coût est une jointure sur
  une table partitionnée, en SQL direct.
- **Il n'y a pas de réouverture**, et ce n'est pas un oubli.

## Ce qui invaliderait cette décision

Le Port décrit un **visa** : un directeur qui doit approuver le traitement de son
agent avant que le courrier ne se referme. Le trajet donné en trois phrases n'en
comporte pas, mais il a été donné en trois phrases.

Ou bien : un courrier clos doit pouvoir se rouvrir — parce que l'expéditeur
relance, parce que la réponse était fausse. Il faudra alors dire ce que devient
la première date de fin, et le délai qu'elle mesurait.

## Alternatives écartées

**Une ligne `traitement` par enregistrement.** Le registre se serait rempli de
versions que personne n'a rendues, et « qu'a-t-il écrit ? » n'aurait plus eu de
réponse unique. Les versions figées à la restitution disent la même histoire, en
n'en gardant que les chapitres.

**Clôturer sous `AFF`.** C'est la permission qui distribue le courrier, pas celle
qui le referme. `CLO` existe au socle depuis le premier jour et ne servait à
rien : lui donner enfin son objet valait mieux que d'en détourner une autre.

**Laisser `valider` et `transmettre` en place « au cas où ».** C'est ce qui avait
été fait pour `TRANSMIS`, `SIGNE` et `PARTI`, et le coût s'est vu : quatre étapes
mortes, des filtres sur du vide, et un front qui déclarait un circuit que le
serveur ne pouvait pas produire.

**Attendre que le Port décrive l'écran de rédaction.** Il a décrit le trajet ; le
contenu du traitement, lui, n'a jamais été spécifié — le commentaire de la table
le dit depuis le premier jour. Une zone de texte libre, horodatée et versionnée
est le plus petit engagement qui rende le trajet complet, et celui qui se
remplacera le plus facilement le jour où le contenu sera dit.

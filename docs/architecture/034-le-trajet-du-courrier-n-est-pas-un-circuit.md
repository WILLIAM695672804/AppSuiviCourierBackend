# 034 — Le trajet du courrier n'est pas un circuit paramétrable

26 août 2026.

## Contexte

Pendant trois semaines, le pilier courrier a porté un trou nommé : `circuit_etape`
est vide, donc aucune validation ne se déroule, donc quatre des neuf étapes que le
front déclarait n'étaient jamais émises, donc `valider`, `transmettre`, `clôturer`
et `relancer` étaient inatteignables. La question ouverte A24 réclamait « le trajet
réel d'un courrier au Port : qui agit, dans quel ordre, sous quel délai ».

Le 26 août 2026, le Port l'a décrit :

> tout commence lorsque le bureau central enregistre le courrier, puis le cabinet
> du directeur les cote à des structures, puis les responsables de structure
> (directeur de structure ou son secrétariat) cotent à un ou plusieurs agents de
> la direction qui eux vont traiter le courrier, puis vont le restituer au
> responsable de structure.

Interrogé sur la suite, le Port a précisé : **le responsable clôture, fin**. Et
sur les délais : **fixés à la main à la cotation**, comme aujourd'hui.

Ce trajet ne comporte **ni validation hiérarchique, ni signature, ni escalade
automatique, ni délai standard par étape**. C'est exactement la chaîne que le
socle porte depuis le premier jour : `cotation` → `cotation_structure` →
`affectation` → `traitement`.

## Décision

**Le trajet du courrier arrivé est le pipeline des tables existantes, et
`circuit_etape` reste vide.** Aucune étape n'y est semée, aucune instance de
circuit ne se déroule, et rien ne se paramètre.

Les étapes deviennent sept, toutes émises par `lecture.etape()` :

    ENREGISTRE → COTE → AFFECTE → ACCEPTE → EN_TRAITEMENT → RESTITUE → CLOTURE

`TRANSMIS`, `SIGNE` et `PARTI` sont **retirés** du type `EtapeCourrier` et de la
table des actions. `EN_VALIDATION` est renommée `RESTITUE`.

## Conséquences

- Les quatre étapes mortes disparaissent. Un type qui annonce une valeur
  impossible se lit comme une spécification : il a fait déclarer au front des
  filtres sur du vide, et c'est le même défaut que le membre `"Refusé"` retiré
  d'`ActionAcces` le 19 août (A64).
- `ACCEPTE` est une étape **nouvelle**, et non un renommage : c'est la décharge
  de l'agent, décrite par le Port le même jour (ADR 035).
- `RESTITUE` dit ce qui se passe réellement — un traitement soumis attend son
  responsable de structure, pas une validation hiérarchique. Le mot précédent
  décrivait un circuit qui n'existe pas.
- Le **fil d'observations** n'est pas cloisonné : tout lecteur du courrier le lit
  en entier, quelle que soit la structure de l'auteur. C'est l'arbitrage du Port,
  et c'est la seule exception à l'ADR 032 — un fil cloisonné aurait produit cinq
  fils parallèles au lieu d'une conversation.
- A24 se réduit de trois entrées à deux : restent le plan de classement
  (`rubrique_classement`) et les seuils d'alerte (`seuil_alerte`).
- Coût : `circuit_version`, `circuit_regle`, `circuit_etape`, `instance_circuit`,
  `instance_etape` et `validation` restent au schéma sans emploi. Elles ne sont
  pas supprimées — le pilier départ, lui, comporte une signature, et c'est là
  qu'un circuit aura peut-être un sens.

## Ce qui invaliderait cette décision

Le Port décrit un jour un trajet **qui varie** : selon la nature, selon la
direction, selon le degré de confidentialité. Un trajet unique se code ; trois
trajets se codent encore ; dix se paramètrent. C'est à ce moment-là que
`circuit_etape` reprendra son sens, et il faudra alors trancher laquelle de la
table ou du code fait foi.

Ou bien : une validation hiérarchique apparaît sur le courrier **arrivé** — un
directeur qui doit viser le traitement de son agent avant clôture. Le trajet
décrit n'en comporte pas, mais il a été donné en trois phrases.

## Alternatives écartées

**Semer `circuit_etape` avec les cinq étapes décrites.** Le trajet aurait été
« paramétré », donc modifiable sans code. Écarté parce que le paramétrage aurait
été un mensonge : les étapes n'auraient rien piloté — c'est `services.py` qui
décide, et une table que personne ne lit finit par diverger de ce qu'elle prétend
décrire. Le jour où quelqu'un aurait modifié une ligne, rien ne se serait passé.

**Garder `EN_VALIDATION` et ajouter `RESTITUE` à côté.** Deux mots pour le même
fait, et six mois plus tard personne ne sait lequel le serveur émet.

**Attendre encore, et ne rien retirer.** C'est ce qui a été fait pendant trois
semaines. Le coût s'est vu : trois écrans en 404, quatre étapes mortes, et un
front qui déclarait un circuit que le serveur ne pouvait pas produire.

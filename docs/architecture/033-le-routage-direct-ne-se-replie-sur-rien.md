# 033 — Le routage direct ne se replie sur rien

24 août 2026.

## Contexte

Le cahier des charges cite un circuit spécifique : « les factures allant
directement chez le DFC sans passer par le DG ». C'est une règle de routage —
une nature de courrier, un sens, et une structure de destination.

La tentation était de la brancher sur `circuit_regle` et `circuit_etape`, qui
existent et qui décrivent des trajets. Elles sont **vides** : le trajet réel d'un
courrier au Port n'a jamais été communiqué (A24), et aucun circuit ne se déroule.
Y poser le routage direct aurait fait dépendre une règle connue — les factures
vont au DFC — d'une règle qui ne l'est pas.

## Décision

Une table `regle_routage`, indépendante des circuits. Une règle apparie un
courrier par sa **nature**, son **sens** et son **correspondant**, et désigne la
structure à coter d'office à l'enregistrement.

Une règle doit porter **au moins un critère** (`CHECK
regle_routage_a_un_critere`). Il n'existe donc pas de règle attrape-tout, et
**aucun repli** : un courrier qui ne correspond à aucune règle suit le circuit
ordinaire, c'est-à-dire l'appréciation humaine.

La règle la plus spécifique gagne, à égalité la priorité, à égalité
l'identifiant. Le routage entier s'éteint par le paramètre
`courrier.routage_direct_actif`.

## Conséquences

- Le routage direct écrit une cotation ordinaire, et un événement
  `courrier.routage_direct` qui nomme la règle appliquée **et son statut**
  (`hypothese` ou `acte`). Un courrier routé par une règle inventée le dit.
- La règle d'exemple `FACTURE / ARRIVEE → DFC` est semée en `hypothese`, avec
  une question ouverte (A69) : ni le sigle exact de la structure destinataire, ni
  le sort des factures au départ ne sont écrits (ADR 016).
- Le paramètre d'extinction existe parce qu'une règle fausse en production doit
  se couper **sans redéploiement** — et parce qu'une cotation automatique fausse
  se voit tard.
- La règle doit être posée **deux fois** dans le dépôt : par le semeur de
  l'organigramme fictif et par le chargeur de l'organigramme réel. Les migrations
  tournent avant l'existence des structures (ADR 025), donc une migration ne peut
  pas la poser en visant un sigle.
- Coût : une seconde table qui décrit un trajet, à côté de `circuit_regle`. Le
  jour où les circuits se rempliront, il faudra dire laquelle des deux fait foi.

## Ce qui invaliderait cette décision

Que le Port communique le trajet réel d'un courrier et que `circuit_etape` se
remplisse. Le routage direct deviendrait le cas dégénéré d'un circuit à une
étape, et maintenir deux mécanismes coûterait plus que d'en fusionner un.

Ou qu'une règle doive dépendre d'autre chose que de la nature, du sens et du
correspondant — de l'objet, d'un mot-clé, de l'expéditeur nominatif. Les trois
colonnes ne suffiraient plus, et un moteur de règles est une autre décision.

## Alternatives écartées

**Poser le routage sur `circuit_regle`.** Écarté ci-dessus : brancher le connu
sur l'inconnu.

**Une règle attrape-tout, sans critère, en repli.** Elle aurait routé
silencieusement tout courrier non prévu vers une structure choisie par défaut.
Un courrier mal routé qu'on ne remarque pas coûte plus qu'un courrier non routé,
qui reste visiblement à traiter.

**Router en dur dans le service.** La règle serait alors une ligne de code, et
sa correction un déploiement. La table `parametre` a déjà tranché ce débat
(ADR 005) : ce qui vient du métier vit en base.

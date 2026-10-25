# 035 — L'agent coté signe avant de traiter

26 août 2026.

## Contexte

L'écran A-11 « Accusés de réception physiques » existait depuis la maquette, avec
un récépissé imprimable, un coursier, un récepteur et une décharge. La route
`GET /accuses` n'existait pas : aucune table du socle ne portait de décharge
physique, et l'écran répondait 404 — c'est-à-dire, du fait d'un `= []` en valeur
de repli, une liste vide silencieuse.

Interrogé sur ce que cet écran devait suivre, le Port a répondu :

> le port tient un cahier où chaque agent coté signe qu'il a bien reçu le
> courrier ! c'est pourquoi il faut ajouter une fonctionnalité qui permet à
> l'agent coté d'accepter le courrier, pour prouver qu'il a bien reçu le courrier

Et sur la portée de ce geste : **bloquante — pas de traitement sans acceptation**,
avec **conservation de la trace du support papier** (coursier, signature).

Le socle portait déjà un accusé : `passage_structure.accuse_le`, posé le 24 août
(ADR 031). Mais c'est l'accusé du **bureau d'ordre de la structure**, pas celui de
l'agent. Les deux mesurent des choses différentes : le premier dit quand la
structure a reconnu l'entrée, le second quand la personne a reçu le pli.

## Décision

**La décharge se pose sur l'affectation, et elle conditionne le traitement.**

Quatre colonnes sur `affectation` : `accepte_le`, `accepte_par`, `remis_par`
(le coursier) et `reference_cahier`. Une affectation vaut pour un agent et un
seul ; sa décharge aussi.

`services.exiger_la_decharge()` refuse tout dépôt de traitement tant que
`accepte_le` est nul. Le paramètre `courrier.acceptation_obligatoire` l'éteint
sans redéploiement.

Le geste s'ouvre sous **`LEC`**, pas sous `TRA`.

## Conséquences

- L'étape `ACCEPTE` s'intercale entre `AFFECTE` et `EN_TRAITEMENT` (ADR 034).
  L'écart entre les deux dates est le **temps de remise du pli** — la seule chose
  que le cahier mesure, et que personne ne voyait.
- **Une seule fois.** Un second accusé écraserait l'heure du premier et remettrait
  cette mesure à zéro à chaque clic. Le service répond 409, comme l'accusé du
  bureau d'ordre.
- `LEC` et non `TRA`, parce qu'accuser réception est le geste de celui qui
  **reçoit**, pas de celui qui traite. Exiger `TRA` aurait empêché d'accuser un
  courrier mal dirigé — c'est-à-dire exactement le cas où le cahier sert. La
  qualité du signataire est vérifiée autrement : l'agent affecté, ou quelqu'un de
  sa structure, qui tient le cahier et signe pour un absent.
- **Il n'y a pas de refus.** L'agent qui estime que le courrier ne le concerne pas
  ouvre un signalement d'écart de type `DESTINATAIRE_ERRONE`. Deux voies pour le
  même fait auraient produit deux registres à réconcilier (A70).
- La garde `exiger_la_decharge()` **n'a aujourd'hui aucun appelant**, et c'est
  assumé : aucune route ne dépose de traitement — `Traitement` existe pour que
  `lecture.etape()` distingue « affecté » de « en traitement », et l'écran de
  rédaction n'est pas spécifié. La règle est écrite là où elle sera trouvée le
  jour où cet écran arrivera, plutôt que dans un journal de bord où elle aurait
  été oubliée.
- Coût : deux accusés coexistent, celui de la structure et celui de l'agent. Un
  lecteur pressé les confondra. C'est la raison des commentaires de colonne.

## Ce qui invaliderait cette décision

Le Port cesse de tenir le cahier papier, et l'acceptation à l'écran devient la
seule preuve. `remis_par` et `reference_cahier` perdent alors leur objet — ils
sont facultatifs pour cette raison, et pourront être retirés sans migration de
données.

Ou bien : un agent doit pouvoir **refuser** nommément, avec un motif qui remonte
au responsable. Le signalement d'écart y pourvoit aujourd'hui ; s'il s'avère trop
lourd pour un geste quotidien, une colonne `refuse_le` viendra — et il faudra
alors dire ce que devient l'affectation refusée.

## Alternatives écartées

**Une table `accuse_reception` séparée.** Une jointure de plus à chaque lecture du
dossier pour n'y ranger qu'un fait par ligne mère. Écarté.

**Réutiliser `passage_structure.accuse_le`.** C'est l'accusé de la structure, pas
celui de l'agent : un point focal qui tamponne à l'entrée n'a pas remis le pli à
qui le traitera. Les confondre aurait fait disparaître le temps de remise interne,
qui est précisément ce que le cahier existe pour mesurer.

**Rendre l'acceptation facultative.** Le Port a dit « bloquante ». Une décharge
que l'on peut sauter n'est pas une décharge.

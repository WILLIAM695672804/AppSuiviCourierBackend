# 032 — Un événement appartient à une structure, ou à personne

24 août 2026. Complète la
[012](012-le-journal-est-l-histoire-du-dossier.md) et la
[022](022-le-registre-est-une-porte-de-visibilite.md).

## Contexte

Le cahier des charges demande de suivre l'entrée et la sortie d'une structure
« sans exposer inutilement les instructions internes confidentielles aux autres
utilisateurs ». Deux directions cotées sur le même courrier doivent voir que
l'autre l'a reçu et rendu — pas ce que son directeur a écrit à son
collaborateur.

Or la fiche de vie rendait **tout** le journal à quiconque voyait le courrier
(ADR 012). L'annotation d'une cotation en cascade, l'affectation nominative à un
agent, l'instruction manuscrite : tout se lisait d'un bout à l'autre du port dès
lors qu'on était coté.

Le cloisonnement demandait donc une frontière, et une frontière demande un
porteur. Aucune colonne du journal ne disait « à l'intérieur de quelle structure
ce geste a eu lieu ».

## Décision

`evenement` porte une colonne `structure_id`, **nullable**, et la règle tient en
une phrase : `NULL` est un **jalon public**, lisible par toute structure qui voit
le courrier ; une valeur est un **geste interne**, lisible par cette structure et
par qui la consolide.

Sont publics : l'enregistrement, la cotation de premier niveau, l'entrée en
structure, la sortie de structure, la clôture, le routage direct. Sont internes :
l'affectation à un agent, et la cotation en cascade (niveau ≥ 2).

Le défaut de `inscrire()` est `structure_id=None`, donc **public**.

## Conséquences

- Le défaut est le **moins protecteur des deux**, et c'est délibéré : un
  événement qu'on oublie de qualifier reste visible dans le dossier plutôt que
  d'en disparaître sans que personne ne s'en aperçoive. Un jalon manquant se
  remarque ; un jalon en trop se corrige.
- Le porteur du cloisonnement est la **structure de l'auteur**, pas celle du
  destinataire du geste : c'est la structure qui instruit qui décide de ce qui
  reste chez elle.
- La DSR et le poste de direction ne sont pas cloisonnés : `REL` et `VUE_DG`
  ouvrent tout, sans quoi le mapping complet exigé pour le suivi des délais
  serait amputé.
- Le cloisonnement des **détenteurs** est différent de celui du journal : la
  ligne reste, avec sa durée, et seul le **nom** de l'agent s'efface au profit du
  libellé de la structure. Masquer la ligne entière aurait faussé la lecture du
  trajet — on aurait cru le courrier immobile alors qu'il circule.
- Le filtre est en SQL, dans `courrier/lecture.py`, appliqué aux trois lectures
  du journal. Une quatrième lecture écrite sans le filtre ne produirait **aucune
  erreur** — juste une fuite. C'est le même risque que `restreindre()`.
- Coût : chaque nouvel appel à `inscrire()` demande de se poser une question de
  plus. Elle est écrite dans la docstring.

## Ce qui invaliderait cette décision

Que le Port demande qu'une instruction interne soit lisible par la structure
**destinataire** de l'affectation quand elle diffère de celle de l'auteur. Le
porteur changerait de camp, et la colonne ne suffirait plus : il faudrait une
liste de structures par événement.

Ou, à l'inverse, qu'il énonce qu'aucun geste n'est confidentiel entre structures
cotées. La colonne deviendrait sans emploi, et il faudrait la retirer plutôt que
la laisser dormir.

## Alternatives écartées

**Une liste de types d'événements « internes », en dur.** Plus simple, et faux :
une affectation est interne *à une structure donnée*, pas dans l'absolu. Sans
porteur, on n'aurait pas su à qui l'ouvrir.

**Une colonne `interne` booléenne.** Elle aurait dit qu'un geste est caché sans
dire de qui il ne l'est pas. La question n'est pas « est-ce secret » mais « chez
qui cela s'est passé » — et cette seconde question a une réponse utile ailleurs,
par exemple pour reconstituer le trajet.

**Un défaut à « interne ».** Plus sûr en apparence. En pratique, le premier
événement mal qualifié disparaît du dossier des autres structures, et personne
ne le sait : il n'y a pas d'erreur, il y a un trou. On préfère le bruit au
silence.

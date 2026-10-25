# 024 — La serrure du confidentiel ne ferme pas son propre registre

18 août 2026. Complète la [022](022-le-registre-est-une-porte-de-visibilite.md),
qu'elle ne contredit pas.

## Contexte

L'ADR 022 a posé que le registre est une quatrième porte de visibilité, et que
la confidentialité est une **serrure** appliquée avant les quatre portes : un
courrier `confidentiel` disparaît des listes de qui ne porte pas la permission
`CONF`, y compris en portée `toutes`. Consolider n'est pas déverrouiller.

Ce que l'ADR 022 n'a pas regardé, c'est **qui tient le registre confidentiel**.

Le socle distribue les permissions par profil. Le profil `AGENT_SESS` — celui
de l'agent d'enregistrement — porte `LEC`, `ENR`, `COT_DEL`, `TRANS`, `CLO`,
`IMP`, `DOS_LEC`. Il ne porte pas `CONF`. Le seul profil qui porte `CONF` est
`DG`, qui ne porte pas `ENR`.

Conséquence, constatée par un test : l'agent rattaché à la session
`confidentiel` enregistre un courrier, la route relit la fiche pour la lui
renvoyer, et reçoit **404 sur le courrier qu'il vient de créer**. Il ne peut ni
le relire, ni le retrouver au registre, ni le coter. Le registre confidentiel
n'est pas seulement inconfortable : il est intenable.

Deux lectures s'offraient, et une seule tient :

- exiger `CONF` pour enregistrer en confidentiel — alors personne ne peut tenir
  ce registre, puisqu'aucun profil du socle ne cumule `ENR` et `CONF` ;
- reconnaître que **le rattachement à ce registre est l'acte d'habilitation**.

Le socle penche déjà pour la seconde : `session.lit_toutes_sessions` n'est vrai
que pour le confidentiel, et son commentaire dit « droit de lecture sur les
autres sessions ». On ne confie pas ce registre par distraction — le
rattachement est exclusif, garanti par une contrainte d'exclusion du moteur, et
il s'administre.

## Décision

La serrure du confidentiel épargne les courriers de **la propre session** de
l'agent, quand cette session est le registre confidentiel. Partout ailleurs elle
reste posée, inchangée.

En clair : `CONF` ouvre les courriers confidentiels **de tous les registres** ;
le rattachement au registre confidentiel ouvre **ce registre-là**, et rien
d'autre.

## Conséquences

- Le registre confidentiel devient tenable : celui qui y enregistre y lit.
- La consolidation reste sans effet sur le secret. L'attachée de suivi de la DSR
  voit tout le port en portée `toutes` et ne voit aucun courrier confidentiel,
  ce qui était le point de l'ADR 022.
- Un agent d'un autre registre ne gagne rien : la condition porte sur le code de
  sa session, pas sur l'existence d'un rattachement.
- La serrure prend désormais la session en argument, donc `visibles()` la
  calcule **avant** de poser la serrure. L'ordre du code change ; l'ordre
  logique — serrure d'abord, portes ensuite — ne change pas.
- Une seule permission ne suffit plus à décrire qui voit un courrier
  confidentiel. C'est le coût : la réponse est en deux morceaux.

## Ce qui invaliderait cette décision

Que le client attribue `CONF` au profil `AGENT_SESS`, ou crée un profil
d'agent du registre confidentiel qui la porte. L'exception deviendrait alors
inutile, et il faudrait la retirer plutôt que de la laisser dormir : une
exception sans emploi finit par servir à autre chose.

Ou, à l'inverse, qu'il énonce que l'agent qui enregistre un courrier
confidentiel n'a pas à en connaître le contenu — un registre à l'aveugle, où la
saisie se fait sous pli. C'est concevable, ce n'est écrit nulle part, et cela
demanderait un écran d'enregistrement qui ne relit pas ce qu'il vient d'écrire.

## Alternatives écartées

**Exiger `CONF` à l'enregistrement en confidentiel.** Cohérent sur le papier,
inapplicable : aucun profil du socle ne cumule `ENR` et `CONF`. On aurait livré
un registre que personne ne peut ouvrir, et le refus serait tombé sur l'agent
au lieu de tomber sur la configuration.

**Donner `CONF` à `AGENT_SESS` dans le socle.** Ce serait trancher une règle
d'habilitation à la place du client, et beaucoup plus largement que nécessaire :
l'agent du registre « Arrivée » lirait alors les confidentiels du registre
qu'il ne tient pas. La règle marquée `hypothese` ne se remplace pas par une
autre invention (ADR 016).

**Rendre la fiche sans passer par `visibles()` juste après l'enregistrement.**
Deux règles de visibilité au lieu d'une, et c'est toujours celle qui protège le
moins qui finit par s'appliquer. Le module dit lui-même que toute lecture passe
par `visibles()`.

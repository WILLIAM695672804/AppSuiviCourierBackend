# 041 — Les profils livrés se modifient, mais ne sortent pas du catalogue

*acceptée — 28 août 2026*

## Contexte

Le socle livre une quinzaine de profils — `ADMIN`, `RESP`, `AGENT_SESS`,
`CABINET`… — marqués `systeme` en base. Depuis l'origine, `services.py` posait
comme règle non négociable qu'*un profil système ne se modifie pas* : ni son
libellé, ni ses permissions. L'écran G-02 affichait un cadenas et des cases
grisées, et le message de refus recommandait de créer un profil dérivé.

Deux choses ont fini par se voir.

La première est que le verrou ne protégeait rien. L'administrateur pouvait déjà
copier `RESP` dans `RESP_2`, y cocher ce qu'il voulait, l'attribuer aux mêmes
agents et retirer l'ancien. Le résultat est identique, en cinq gestes au lieu
d'un, avec un catalogue qui se remplit de doublons et un journal où l'on ne
reconnaît plus les profils. Un verrou qui se contourne par une procédure plus
longue ne protège pas : il fatigue.

La seconde est que le référentiel livré n'est pas la vérité. Il décrit
l'organisation du Port telle que nous l'avons comprise en lisant le descriptif
fonctionnel. Le profil `CABINET`, écrit le matin même de cette décision, en est
la preuve : il a fallu une phrase de l'utilisateur — « c'est chez nous que l'on
cote et enregistre les ordres du directeur » — pour découvrir un profil que
personne n'avait prévu. D'autres corrections viendront, et elles ne peuvent pas
toutes passer par une migration.

L'utilisateur l'a demandé en une phrase : « déverrouille les profils, je dois
pouvoir modifier les habilitations ».

## Décision

**Les permissions et le libellé de tout profil se modifient, `systeme` compris.**
`_profil_modifiable` devient `_profil_vivant` et ne refuse plus rien.

Deux verrous demeurent, et aucun n'est une opinion sur qui doit avoir quel droit :

1. **Un profil `systeme` ne sort pas du catalogue.** Le semis, les migrations et
   les tests le citent par son **code** ; l'invalider ne casserait rien avant le
   déploiement suivant, ce qui est la pire façon de casser. Le code lui-même
   reste non modifiable, pour la même raison, et pour tous les profils.
2. **On ne retire pas `ADM_HAB` du dernier profil qui la porte.** Ce geste-là
   ferme l'administration à tout le monde, y compris à celui qui vient de le
   faire, et aucun écran ne permet d'y revenir — il faudrait un `INSERT` en base.
   Tout le reste se reprend d'un clic.

## Conséquences

- Une erreur d'administration est désormais possible sur un profil livré : elle
  se voit, elle est datée, elle porte un nom d'acteur, et elle se corrige en
  recochant la case. C'est ce que le journal est fait pour rendre supportable.
- Le drapeau `systeme` change de sens et le vocabulaire de l'écran suit :
  « Verrouillé » devient « Référentiel livré ». Il n'affirme plus « intouchable »
  mais « livré avec l'application, et cité par son paramétrage initial ».
- Un profil livré modifié à l'écran **diverge du socle**. Une migration future
  qui voudrait corriger ses droits doit tenir compte de ce que l'exploitation a
  pu changer — écrire en `get_or_create` et jamais en écrasement.
- Le refus de la dernière clef doit se lire à l'écran, sinon la case revient à
  son état sans explication et le clic paraît sans effet. L'écran affiche donc
  l'erreur de la mutation.

## Ce qui invaliderait cette décision

Si le Port confiait l'administration des habilitations à plusieurs personnes de
directions différentes, un profil livré modifié par l'une et supposé stable par
l'autre deviendrait un risque réel. Il faudrait alors non pas reverrouiller, mais
tracer la divergence : afficher sur chaque profil livré ce qui a été modifié
depuis la livraison.

## Alternatives écartées

**Garder le verrou et documenter la dérivation.** C'était la situation existante.
Elle demandait cinq gestes pour un, remplissait le catalogue de doublons, et
n'empêchait aucune des erreurs qu'elle prétendait prévenir.

**Ne déverrouiller que certains profils** — tous sauf `ADMIN`. La ligne aurait
été arbitraire : `AGENT_SESS` tient le registre confidentiel, ce qui est au moins
aussi sensible qu'administrer. Et la vraie protection n'est pas le profil, c'est
la dernière clef.

**Demander une confirmation écrite (motif) pour chaque case cochée sur un profil
livré.** Le journal enregistre déjà l'acteur, la date et le droit. Un motif que
personne ne relit ne fait que rendre le geste pénible — ce qui était le défaut
du verrou qu'on retire.

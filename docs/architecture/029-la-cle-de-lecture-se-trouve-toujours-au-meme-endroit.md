# 029 — La clé de lecture se trouve toujours au même endroit

*Statut : acceptée — 25 août 2026*

## Contexte

Les tableaux de bord portent cinq tracés écrits à la main — histogramme groupé,
histogramme à une série, courbe, anneau de répartition, nuage de points — et une
frise de congés. Chacun a été écrit à son heure, avec sa propre idée de l'endroit
où poser ce qui permet de le lire :

- `GrapheBarres` calait sa légende à gauche, sous le tracé, en `11 px` ;
- `GrapheColonnes` et `GrapheCourbe` **centraient** leur mention d'axe, en
  `9,5 px`, sans légende ;
- `NuageDePoints` posait la mention d'axe à gauche et sa réserve de lecture à
  droite, en `10,5 px`, dans une rangée à lui ;
- la frise des congés avait sa propre légende, en `10,5 px` semi-gras, séparée
  par un filet ;
- `GrapheRepartition` n'avait rien — ses étiquettes reliées font office de
  légende, ce qui est juste, mais il n'avait pas non plus où poser une unité.

Sur un écran qui empile quatre panneaux dans une grille, l'œil doit alors
chercher, panneau par panneau, où se trouve la clé. Ce n'est pas une faute de
goût : c'est un coût de lecture payé à chaque consultation.

Second manque, plus concret. Le glossaire des sigles (§3.12) existait en modale,
mais son bouton d'en-tête ne s'affichait **que sur les écrans sans fil
d'Ariane** — il partait avec les notifications et le profil, que les écrans de
saisie remplacent par le fil. Il disparaissait donc exactement là où les sigles
sont les plus denses : les fiches, les synthèses d'instance, les formulaires. Et
il ne connaissait de toute façon aucun sigle de structure : `DAG-MP` et `REP-NDJ`
n'y sont pas, alors que ce sont ceux qui arrêtent la lecture d'un tableau de bord.

## Décision

**Un seul pied de graphique, `PiedGraphe`, pour tous les tracés.** Il fixe
l'ordre une fois pour toutes : l'**identité** à gauche (la légende), la
**mention d'axe** à sa suite, la **note de lecture** à droite. Les cinq tracés et
la frise des congés le rendent, et ne composent plus leur pied eux-mêmes.

**Pas de légende pour une série unique.** Le seuil est à deux séries, et il est
appliqué *dans* `PiedGraphe`, pas chez l'appelant : une pastille seule n'apprend
rien que le titre du panneau ne dise déjà. `GrapheRepartition` reste sans légende
pour une autre raison — ses étiquettes sont reliées à leur part, ce qui est mieux
qu'un pavé de pastilles à rapprocher de teintes voisines.

**Le texte reste en encre.** Les valeurs, les libellés et les entrées de légende
portent les jetons de texte ; la couleur est portée par la pastille, à côté. La
répéter dans le texte brouille la lecture au lieu de l'aider.

**Le bouton du glossaire est présent sur tous les écrans**, y compris ceux qui
portent un fil d'Ariane, et y compris sur téléphone. Il est le seul outil système
dans ce cas, et pour une raison précise : un sigle incompris arrête la lecture là
où elle se trouve, et renvoyer le lecteur sur un autre écran la lui ferait perdre.

**Le glossaire connaît l'organigramme.** Une quatrième famille, « Organigramme »,
est versée depuis `/referentiels/structures` — ouvert à toute session
([ADR 007](007-referentiel-organigramme-sans-perimetre.md)) — et
non écrite dans `lib/glossaire.ts`. Les soixante-dix-sept sigles sont une donnée
administrée : les figer dans le code aurait fait mentir le glossaire au premier
remaniement. La définition d'une structure y dit son **rattachement**, parce que
c'est ce qu'on cherche : de quelle direction relève la division, pas ce qu'elle
fait. Le référentiel n'est demandé qu'à l'ouverture de la modale.

## Conséquences

- Un nouveau tracé n'a plus à décider où poser sa clé : il rend `PiedGraphe`.
- Les mentions d'axe des colonnes et de la courbe passent de centrées à alignées
  à gauche. C'est un déplacement visible, et c'est le but.
- La frise des congés perd sa légende propre. Sa grille de teintes
  (`TEINTES_ETAT`) étant faite de classes utilitaires et non de couleurs CSS,
  `SerieLegende` accepte les deux : `couleur` ou `classe`.
- Un sigle de structure retiré de l'organigramme disparaît du glossaire en même
  temps que du référentiel. C'est cohérent, mais cela veut dire qu'un sigle lu
  dans une archive ancienne peut n'être plus décodable — voir
  `docs/questions-ouvertes.md` si le besoin se confirme.
- Le glossaire ne décode toujours pas les sigles **au survol du tracé** : les
  étiquettes tronquées rendent leur libellé entier par `title`, mais l'intitulé
  complet d'un sigle se lit dans la modale. Poser l'intitulé au survol de chaque
  point aurait supposé que les routes de mesure servent l'intitulé à côté du
  sigle, ce qu'elles ne font pas — quatre schémas à élargir pour une infobulle.

## Alternatives écartées

**Une légende sur tous les tracés, série unique comprise.** Uniforme, et vide de
sens : « Exécution » sous un panneau intitulé « Exécution du plan d'actions ».

**Une page « Glossaire » dans la navigation.** On cherche un sigle *en lisant
autre chose*. Changer d'écran fait perdre ce qu'on lisait — c'est déjà la raison
pour laquelle le glossaire est une modale.

**Écrire les sigles de structures dans `lib/glossaire.ts`.** Soixante-dix-sept
constantes recopiées d'une table qui les porte déjà, et qui divergeraient au
premier arrêté d'organisation.

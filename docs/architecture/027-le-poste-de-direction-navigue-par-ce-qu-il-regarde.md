# 027 — Le poste de direction navigue par ce qu'il regarde

*Statut : acceptée — 25 août 2026*

## Contexte

La vue d'ensemble de la Direction générale (§3.1) était rendue dans la
disposition commune de l'espace de travail : une barre latérale de 238 px à
gauche, portant sept entrées de menu, et l'écran de lecture à droite. Sa
docstring l'assumait — « rien n'y est cliquable, rien n'y demande d'action.
C'est une lecture, pas un poste de travail ».

Deux choses ne tenaient pas ensemble. D'un côté un écran qui affiche sept
repères, cinq graphiques et deux cartes, c'est-à-dire quatorze chiffres dont
aucun n'ouvre ce qu'il recouvre. De l'autre un menu qui propose sept
destinations, dont aucune ne prolonge le chiffre qu'on vient de lire. Le
Directeur général qui remarque un écart d'exécution en recul n'a alors qu'une
option : deviner dans quelle entrée de menu se trouve le détail, et refaire le
filtrage à la main.

Un chiffre de pilotage dont on ne peut pas voir ce qu'il recouvre n'est pas un
chiffre de pilotage, c'est une affiche.

## Décision

**La session qui porte `VUE_DG` n'a pas de barre latérale, et la vue d'ensemble
devient le point d'entrée de tout son parcours.**

Trois pièces :

1. **`DispositionDirection`** remplace la disposition commune pour cette
   session — plein écran, aucun menu, aucun tiroir de navigation. L'aiguillage
   est dans `Disposition`, pas dans le routeur : la disposition est une route
   mère unique, et la dupliquer aurait dupliqué l'arbre entier des routes.
2. **Chaque repère, chaque graphique et chaque carte de la vue d'ensemble ouvre
   l'écran qui porte sa matière** — les activités, les obligations, les
   décisions, les relevés d'exploitation, les statistiques, le classement — avec
   le filtre qui correspond au bloc cliqué quand cet écran en accepte un.
3. **Un fil de retour** vers la vue d'ensemble s'affiche en haut de tout écran
   qui n'est pas elle. C'est le seul élément de navigation permanent de ce
   poste.

**Les destinations sont posées dans l'écran, pas servies par l'API.** La mesure
est une affaire de serveur ; l'écran où elle se détaille est une affaire de
front. Le rapprochement se fait par le libellé du repère : un libellé qui
changerait côté serveur fait tomber le lien, pas l'écran — et c'est le bon sens
de la panne.

**Un lien vers un écran que la session n'ouvre pas n'est pas posé.** Chaque
destination est conditionnée à sa permission (`ACT_LEC`, `DEC`, `EXP_LEC`,
`STAT`, `SCORE`). Le bloc reste alors simplement non cliquable : renvoyer sur le
garde de permission serait une impasse, et masquer le chiffre priverait d'une
mesure que la session a le droit de lire. C'est le même principe que la garde
large à contenu filtré ([ADR 009](009-garde-large-contenu-filtre.md)).

## Conséquences

- **Le poste de Directeur général devient un poste de consultation.** Les écrans
  qui n'étaient atteignables que par le menu ne le sont plus : le cockpit
  exécutif, la file de signature, la clôture, le registre du courrier, la
  synthèse d'instance, les dossiers et la recherche. C'est la conséquence
  voulue, et elle est écrite ici pour qu'on sache qu'elle a été vue : la
  contrepartie d'un écran d'accueil sans menu est qu'il devient la seule porte.
  Ouvrir l'une de ces destinations demandera de la raccrocher à un bloc de la
  vue d'ensemble.
- L'identité et la déconnexion ne passent pas par la barre latérale mais par
  l'en-tête d'écran (`EnTetePage`), qui reste en place partout. La retirer ne
  prive donc de rien d'autre que du menu.
- Aucun `TiroirNavigation` n'est monté : sur téléphone, l'en-tête n'affiche pas
  de bouton de menu. Il n'y a pas de menu à ouvrir, et c'est cohérent.
- Le registre des activités et celui des décisions amorcent leurs filtres sur
  l'URL, à l'ouverture seulement. Réécrire l'URL à chaque changement de filtre
  aurait rempli l'historique du navigateur d'états intermédiaires à dérouler un
  par un.
- L'entrée de menu `VUE_DG` reste dans `lib/navigation.ts` alors qu'elle ne
  s'affiche plus nulle part. Le menu et les routes se lisent ensemble : la
  retirer donnerait à croire que l'écran n'existe pas.

## Ce qui invaliderait cette décision

Le Directeur général doit signer, clore ou arbitrer depuis ce poste. La réponse
ne serait pas de rétablir la barre latérale, mais de poser les blocs manquants
sur la vue d'ensemble — une file de signature et une liste d'arbitrages sont des
mesures comme les autres, et elles y ont leur place.

Un second poste sans menu. La disposition est aujourd'hui choisie sur `VUE_DG` ;
si un autre poste la demandait, le critère deviendrait un attribut du profil et
non une permission particulière.

## Alternatives écartées

**Replier la barre en un bouton ☰.** Le menu reste, l'écran gagne en largeur, et
rien ne change au fond : les quatorze chiffres n'ouvrent toujours rien. Le
problème n'était pas la place prise par la barre, c'était l'absence de chemin
entre un chiffre et son détail.

**Ouvrir le détail dans un tiroir latéral, sans quitter la vue d'ensemble.**
Séduisant, mais il aurait fallu réécrire dans ce tiroir des listes qui existent
déjà — registre des activités, registre des décisions, relevés — avec la
certitude qu'elles finiraient par diverger de leur écran d'origine.

**Servir la destination de chaque repère depuis l'API.** Le serveur aurait
décidé de la carte des écrans du front. Une mesure ne connaît pas les pages qui
l'affichent, et l'ajout d'un écran aurait demandé une migration de schéma.

# 028 — Une liste de structures se cherche, elle ne se parcourt pas

*Statut : acceptée — 25 août 2026*

## Contexte

Les écrans qui laissent choisir une structure — tableau de bord de structure,
registre des activités, plan d'actions — le faisaient par `Pastilles` : une
rangée de boutons, un par option, la sélection en encre pleine. Le composant
avait été écrit pour des filtres courts : cinq états d'exécution, quatre
instances, trois natures de rapport. À cette taille, il est excellent — tout est
visible, un clic suffit, rien n'est caché.

Les structures ne sont pas un filtre court. Depuis le chargement de
l'organigramme réel ([ADR 025](025-l-organigramme-reel-se-charge-il-ne-se-migre-pas.md)),
la DSR en voit soixante-dix-sept. La rangée produisait alors deux défauts, et le
second est le plus grave :

1. **Elle encombre.** Soixante-dix-sept boutons occupent cinq à six lignes et
   repoussent hors de l'écran le tableau de bord qu'on est venu lire.
2. **Elle ment sur l'organigramme.** `DAG`, `DAG-MP` et `DAG-MP-MAR` s'affichent
   côte à côte, de même taille, dans le même gris : rien ne dit que la deuxième
   est dans la première et la troisième dans la deuxième. Le rattachement ne se
   lit que par la convention de nommage des sigles — c'est-à-dire par une
   habitude, pas par une donnée.

## Décision

**Là où les options sont des structures, le choix passe par `ChoixStructure` :
un menu déroulant, avec recherche, et l'indentation par rattachement.** Les
`Pastilles` restent partout ailleurs — cinq états se lisent d'un coup d'œil,
soixante-dix-sept structures non.

Trois points :

- **La recherche filtre sur le sigle et sur l'intitulé.** À cet endroit on
  cherche une structure qu'on connaît déjà ; on ne découvre pas l'organigramme.
- **L'arbre vient du référentiel** `/referentiels/structures`, ouvert à toute
  session ([ADR 007](007-referentiel-organigramme-sans-perimetre.md)). Aucune
  route de mesure n'est modifiée : les écrans continuent de servir la liste des
  sigles que le périmètre autorise, et le composant se charge de les remettre en
  place. C'est ce qui évite d'ajouter un champ d'organigramme à chaque réponse
  qui contient un sélecteur.
- **Le décalage affiché est le nombre d'ancêtres retenus**, jamais la profondeur
  absolue. Un service dont la direction n'est pas dans le périmètre se pose à la
  racine, et non trois crans à droite sous rien.

## Conséquences

- Le périmètre reste la seule source de ce qui est proposé. Le référentiel sert
  à **ordonner et à nommer**, jamais à élargir : un sigle absent de la liste
  servie par l'écran n'apparaît pas, quelle que soit sa place dans l'arbre.
- Un sigle absent du référentiel — structure retirée de l'organigramme mais
  encore portée par une mesure du mois — tombe à la fin de la liste, à plat. La
  taire l'aurait fait disparaître du sélecteur sans que personne ne comprenne
  pourquoi.
- Tant que le référentiel n'est pas arrivé, la liste s'affiche à plat et reste
  utilisable : c'est l'indentation qui manque, pas le choix.
- Le jeu d'essai du serveur de démonstration gagne `parentId`, qu'il n'avait
  jamais servi alors que le vrai serveur le sert. Sans lui, la démonstration
  affichait un organigramme plat là où l'application montre un arbre.

## Ce qui invaliderait cette décision

Un écran où l'on **découvre** l'organigramme plutôt que d'y chercher une
structure connue — l'administration du référentiel, par exemple. Là, l'arbre
déplié à demeure vaut mieux qu'un menu, et c'est déjà ce que fait l'écran
`Organisation`.

Un périmètre qui ne proposerait plus que deux ou trois structures à tout le
monde. Le menu déroulant deviendrait un clic de trop, et les pastilles
reprendraient l'avantage.

## Alternatives écartées

**Garder les pastilles en n'affichant que les directions.** Le point focal d'un
département ne trouverait plus sa propre structure dans la liste de ce qu'il a
le droit de voir.

**Un `<select>` natif, groupé par `<optgroup>`.** Il règle l'encombrement mais
pas la lecture : `optgroup` ne s'imbrique pas, et un organigramme à cinq niveaux
n'entre pas dans deux. Il n'accepte pas non plus de champ de recherche.

**Déduire le rattachement du sigle**, en coupant sur les tirets. `DAG-MP-MAR`
donne bien `DAG` puis `DAG-MP`, et cela aurait évité l'appel au référentiel.
Mais c'est une convention de nommage, pas une donnée : le jour où une structure
s'appelle `REP-YAO` sans qu'aucun `REP` existe, l'arbre affiché devient faux
sans que rien ne le signale.

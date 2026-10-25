# 020 — On désigne un agent par son identifiant, choisi dans un annuaire

*Statut : acceptée — 16 août 2026*

## Contexte

Le 16 août 2026, la création d'une activité échouait en 409 sur toutes les
tentatives d'un utilisateur qui découvrait l'application. Le corps de la réponse
faisait 81 octets, et le message était `Agent « S. Bamba » introuvable.` —
`S. Bamba` étant le **texte d'exemple** affiché en gris dans le champ, recopié
de bonne foi.

La cause n'était pas le placeholder. Le champ « Responsable de l'activité »
était une saisie libre, et le service appariait cette chaîne au `nom_complet`
de l'agent, au caractère près. `Yves Manga` passait ; `Y. Manga`,
`yves manga`, `Manga Yves` et `Yves  Manga` échouaient tous, avec le même
message et sans aucun moyen, depuis l'écran, de savoir quelle forme était
attendue. Le même motif existait à cinq autres endroits : le responsable d'une
tâche, celui d'une instruction, le président d'une séance, son rapporteur,
l'intérimaire d'une absence.

Il ne s'agissait pas d'un défaut de tolérance. Un appariement plus souple —
casse ignorée, espaces normalisés, initiales acceptées — aurait déplacé le
problème : deux agents homonymes existent au Port, et l'application aurait
alors désigné le mauvais **sans rien signaler**. La saisie libre ne pouvait
être réparée, seulement remplacée.

Ce qui manquait pour la remplacer, c'était un annuaire. Aucune route ne rendait
la liste des agents : le référentiel exposait les structures et les postes
([ADR 007](007-referentiel-organigramme-sans-perimetre.md)), pas les personnes.
Le front n'avait donc littéralement pas de quoi peupler un sélecteur — c'est
pourquoi le champ était libre.

## Décision

**Une désignation d'agent voyage par identifiant, et l'identifiant vient d'un
annuaire à garde large.**

1. **`GET /api/referentiels/agents` est déclarée `session_seule`.** Pas de
   permission, pas de `restreindre()`. C'est le raisonnement de l'ADR 007
   appliqué aux personnes : on désigne couramment quelqu'un qu'on ne « voit »
   pas au sens du périmètre — le chef de file d'une activité transverse, le
   rapporteur d'un point qui relève d'une autre direction. Borner l'annuaire au
   périmètre rendrait ces désignations impossibles, et c'est très exactement le
   mur que la saisie libre dissimulait.
2. **L'annuaire ne porte que l'identité de travail** : identifiant, nom complet,
   poste, structure. Garde large ne veut pas dire lot large. Pas d'adresse, pas
   de portée, pas d'habilitation, pas d'état de compte — rien qui transforme
   l'annuaire en cartographie des droits.
3. **Il ne rend que les agents actifs** (`Utilisateur.objects.actifs()`), et
   `_agent()` réapplique la même condition à l'écriture. La lecture guide, elle
   ne garde pas : un identifiant recopié d'un ancien écran doit être refusé par
   le service, pas seulement absent de la liste.
4. **Les saisies portent `…Id: int`**, jamais un nom : `responsableId`,
   `presidentId`, `rapporteurId`, `interimaireId`. Le nom reste en **sortie**,
   pour l'affichage. Une lecture rend `responsable` *et* `responsableId` : le
   premier s'écrit dans un tableau, le second réarme un formulaire d'édition.
5. **Le front ne réapprend rien au serveur.** `poste` et `structure` ont disparu
   de la saisie d'absence : le front les envoyait pour son propre affichage, le
   service ne les a jamais écrits, et ils se déduisent de l'agent. Depuis que
   le responsable se choisit dans un sélecteur, les deux côtés les tiennent de
   la même source.

## Conséquences

Le message d'erreur change de nature. `Agent « S. Bamba » introuvable.` disait
à l'utilisateur qu'il avait mal écrit, sans dire comment bien écrire.
`L'agent designe n'existe pas ou n'est plus actif.` (code `agent_inconnu`) ne
peut plus survenir qu'à deux conditions : le compte a été clos entre l'ouverture
de l'écran et l'envoi, ou l'appel ne vient pas de l'interface. Les deux méritent
un refus.

Le nom complet cesse d'être une clé. Il redevient ce qu'il aurait toujours dû
être : un libellé. On peut désormais corriger l'orthographe d'un patronyme en
base sans casser les formulaires ouverts.

`SelecteurAgent` (front) enveloppe le sélecteur natif et la requête d'annuaire
en un seul composant, avec une étiquette de la forme
`Yves Manga — Point focal (DSI)`. Le poste et la structure y figurent parce que
l'homonymie est réelle : c'est ce qui permet de choisir entre deux `Manga`.

Le coût est une requête d'annuaire par écran de saisie. Elle est mise en cache
par TanStack Query et le lot se compte en dizaines de lignes ; le jour où le
Port dépassera quelques centaines d'agents, il faudra une recherche serveur
plutôt qu'un `<select>`, et le composant est le seul endroit à reprendre.

## Ce qui invaliderait cette décision

Une exigence de **confidentialité de l'organigramme nominatif** — si le Port
décidait qu'un agent ne doit pas pouvoir énumérer les personnes hors de sa
direction. La garde large tomberait, et avec elle la possibilité de désigner
hors périmètre : il faudrait alors une recherche par nom rendant zéro ou un
résultat, sans énumération. C'est la même bascule que celle qui invaliderait
l'ADR 007, et elle se prendrait en même temps.

Une croissance de l'effectif qui rendrait la liste complète absurde à charger.
Le contrat d'API ne changerait pas — c'est le mode de sélection qui changerait.

## Alternatives écartées

**Rendre l'appariement de noms tolérant** (casse, espaces, initiales). Le moins
de code, et le plus dangereux : deux homonymes suffisent pour que
l'application désigne silencieusement la mauvaise personne. Une erreur qui se
signale vaut mieux qu'une erreur qui s'arrange.

**Borner l'annuaire au périmètre de l'appelant.** Cohérent avec le reste du
domaine, et inutilisable : la cotation, la présidence de séance et l'intérim
traversent tous les périmètres par construction. On aurait reconstruit le mur
qu'on venait d'abattre, en le déplaçant vers les cas transverses — c'est-à-dire
vers les cas qui comptent.

**Conserver le nom en saisie et n'ajouter le sélecteur qu'au front.** L'écran
aurait été réparé, l'API serait restée fausse : tout appel direct, tout script
d'import, toute reprise ultérieure aurait retrouvé le même piège intact.

## Voir aussi

- [ADR 007](007-referentiel-organigramme-sans-perimetre.md) — le référentiel de
  l'organigramme ne passe pas par le périmètre
- [ADR 009](009-garde-large-contenu-filtre.md) — garde large, contenu filtré
- [pièges](../../../docs/pieges.md) — « Agent introuvable » à la création d'une activité
- [questions ouvertes](../../../docs/questions-ouvertes.md) — A53, tranchée par cet ADR

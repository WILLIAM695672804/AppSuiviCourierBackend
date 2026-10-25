# 021 — L'organigramme tient sous une seule permission

*Statut : acceptée — 17 août 2026*

## Contexte

Deux permissions se partageaient l'organigramme depuis le socle :

- `ADM_ORG`, portée par le profil `ADMIN`, ouvrait les niveaux hiérarchiques,
  les postes de travail et les affectations datées ;
- `ADM_STR`, portée par le profil `DSR`, ouvrait la seule inscription des
  structures — directions, filiales, succursales.

Le partage venait du descriptif fonctionnel, qui confie le référentiel des
structures à la Division du suivi et de la relance (§3.3) et l'organigramme à
l'administrateur fonctionnel (§3.9). Deux paragraphes, deux acteurs, deux
écrans : celui de la DSR dans son espace de travail
(`/gouvernance/structures`), celui de l'administrateur dans la zone
d'administration (`/organisation`).

Le découpage ne tenait pas à l'usage, parce que **créer une structure n'est pas
un geste isolé** : `creer_structure()` écrit la structure *et* ouvre son poste
responsable, vacant, rattaché au poste responsable de la structure mère. Il
fallait donc, dans la même minute :

1. inscrire la structure — `ADM_STR`, la DSR ;
2. nommer quelqu'un au poste ainsi ouvert — `ADM_ORG`, l'administrateur.

La DSR ajoutait des directions dont elle ne pouvait désigner le responsable, et
l'administrateur nommait dans des structures qu'il ne pouvait pas créer. La
colonne « Responsable » du référentiel restait à « Non désigné » jusqu'à ce que
l'autre main intervienne, sans que rien à l'écran ne dise qu'il fallait
l'appeler.

Le constat vient de l'usage, pas d'une relecture du code : c'est la DSR qui
inscrivait les structures, alors que ce geste relève de l'administration.

## Décision

**L'organigramme entier — structures, niveaux, postes, affectations — s'écrit
sous `ADM_ORG`, et `ADM_STR` disparaît.**

1. **La route déménage** : `POST /gouvernance/structures` devient
   `POST /organisation/structures`, dans le routeur qui écrit déjà l'ossature.
   Le service part avec elle, de `gouvernance.services` vers
   `noyau.organisation.services` — l'objet écrit appartenait déjà au socle.
2. **La permission est supprimée du référentiel**, pas seulement retirée au
   profil. Une permission que personne ne porte et qu'aucune route n'exige est
   un piège : elle se réattribue un jour « pour dépanner », et rouvre la porte.
   La migration refuse de s'appliquer si une étape de circuit l'exige encore.
3. **La DSR garde la lecture, et elle seule.** Le référentiel des structures
   est ouvert à toute session authentifiée ([ADR 007](007-referentiel-organigramme-sans-perimetre.md)) :
   son écran reste, sous `REL`, avec ce que l'administration ne montre pas —
   délai moyen de réponse et courriers en cours, structure par structure. Ce
   qui disparaît de cet écran, c'est le bouton.
4. **L'écran d'administration gagne un onglet « Structures »**, placé en
   premier : l'ordre des onglets suit celui de la création — une structure,
   les postes qu'elle porte, les agents qui les occupent.

## Conséquences

- Le geste complet — créer une structure, pourvoir son poste responsable — se
  fait dans un seul écran, sans changer d'acteur.
- La DSR perd l'autonomie que lui donnait le §3.3 sur ce point précis : ajouter
  une structure passe désormais par une demande à l'administrateur fonctionnel.
  C'est le coût assumé de la décision, et il est visible : l'écran de la DSR le
  dit en toutes lettres.
- Le pilier `gouvernance` perd une permission et un service ; sa docstring
  n'annonce plus que trois permissions.
- Une base déjà installée perd la ligne `profil_permission` de la DSR : les
  comptes concernés voient l'entrée de menu changer de contenu à la prochaine
  connexion, sans erreur ni écran blanc — la route de lecture, elle, n'a jamais
  demandé de permission.

## Ce qui invaliderait cette décision

Une note écrite du Port confiant explicitement l'inscription des structures à
la DSR, en connaissance du couplage avec le poste responsable. La réponse ne
serait alors pas de recréer `ADM_STR` telle quelle, mais de donner à la DSR de
quoi faire le geste **entier** — inscription et affectation du responsable —
c'est-à-dire de lui ouvrir `ADM_ORG` sur son périmètre.

Un second cas : si l'institution se met à créer des structures assez souvent
pour que le passage par l'administrateur devienne un goulot. Le signal serait
mesurable — des créations de structures groupées en fin de mois, plusieurs
jours après la décision qui les a ouvertes.

## Alternatives écartées

**Déplacer `ADM_STR` vers le profil `ADMIN`.** Un changement d'une ligne, qui
laissait deux permissions et deux écrans pour un seul organigramme. La question
« pourquoi celle-ci et pas celle-là ? » se serait reposée au premier ajout de
route, et l'écran de la DSR aurait gardé un bouton que plus personne n'aurait
pu presser.

**Garder les deux permissions et laisser la DSR affecter le responsable.** Cela
revenait à lui donner `ADM_ORG` sous un autre nom — donc les niveaux, les
postes et toutes les affectations de l'institution. Le §3.9 réserve cette main
à l'administrateur, et l'institution a tenu à ce que les deux mains soient
distinctes.

**Faire de l'inscription une demande soumise à validation.** Un circuit
d'approbation pour un geste qui se produit quelques fois par an : le coût de
construction et d'exploitation dépassait le problème.

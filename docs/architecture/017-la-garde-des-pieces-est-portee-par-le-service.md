# 017 — La garde des pièces jointes est portée par le service, pas par le décorateur

*Statut : acceptée — 14 août 2026*

## Contexte

`piece_jointe` est générique : `objet_type` / `objet_id`, comme `evenement`.
C'est ce qui permet d'attacher un fichier à une activité, à un dossier ou à une
demande d'usager sans créer trois tables.

Partout ailleurs dans le dépôt, une route déclare la permission qu'elle exige
dans son décorateur : `auth=exige(PERM.ACT_SAI)`. La règle est écrite dans
`CLAUDE.md`, et son oubli ne produit **aucune erreur** — juste une fuite.

Une route générique de dépôt ne peut pas s'y conformer. La permission qu'il
faut porter pour joindre une pièce dépend de l'objet auquel on la rattache :
`ACT_SAI` pour une activité, `DOS_INS` pour un dossier, `EXT` pour une demande
d'usager. Et l'objet est nommé dans le **corps** de la requête, que `exige()` ne
lit pas — il s'exécute avant que le corps soit désérialisé.

La visibilité pose la même question une seconde fois : porter `ACT_SAI` ne dit
rien du droit d'écrire sur l'activité n° 156, qui dépend du périmètre. Et le
portail ne se restreint pas par périmètre du tout (ADR 013).

## Décision

Les routes de `/api/pieces/*` déclarent `auth=session_seule`, et **toute** la
garde est portée par `noyau.pieces.services._cible_accessible`, appelée par
chaque service — dépôt, liste, téléchargement, retrait.

Ce que chaque type d'objet exige est déclaré une fois dans
`noyau/pieces/rattachement.py` : un registre `{objet_type: Rattachement}` où
`Rattachement` porte la permission exigée et une fonction rendant les objets de
ce type **déjà restreints** pour l'agent.

Un `objet_type` absent du registre est refusé en 409. Une permission manquante
et un objet hors périmètre sont refusés en 404, tous deux — jamais 403 (D5).

## Pourquoi

Une pièce jointe n'a pas de droits propres : ce sont ceux de son objet. Le seul
endroit où cette phrase peut s'appliquer est celui qui connaît l'objet, et le
décorateur ne le connaît pas.

Le registre est une fonction et non un couple de champs (`modele`, `champ de
périmètre`) parce que le portail n'entre pas dans ce moule : ses comptes n'ont
ni structure, ni poste, ni périmètre, et lui en fabriquer un serait *plus*
permissif que de n'en donner aucun. La fonction `_demandes` filtre par
`deposant`, comme tout le pilier.

## Conséquences

- `session_seule` compte désormais **quatre** usages dans le dépôt, tous
  documentés dans `noyau/habilitation/dependances.py`. C'est une liste à tenir
  courte : chaque entrée est un endroit où la relecture du décorateur ne suffit
  plus à savoir qui passe.
- Ajouter un type rattachable est une entrée dans le registre. Ce n'est jamais
  une seconde route de dépôt.
- Le test `test_sans_la_permission_du_pilier_le_depot_est_refuse` et
  `test_hors_perimetre_le_depot_est_refuse` ne sont pas décoratifs : ils sont
  la seule vérification de ce que le décorateur ne dit plus.
- La route déclarative `POST /activites/{id}/pieces`, qui n'inscrivait qu'un
  nom et un poids en attendant le téléversement réel, n'a plus d'appelant. Elle
  est conservée pour que les fiches de vie déjà écrites restent explicables.

## Ce qui invaliderait cette décision

- Si django-ninja permettait un jour à une dépendance d'authentification de lire
  le corps désérialisé de la requête, la garde redeviendrait déclarative et ce
  registre perdrait sa raison d'être.
- Si le nombre de types rattachables dépassait la dizaine avec des règles
  franchement divergentes — un type qui exige deux permissions, un autre qui
  dépend de l'état de l'objet — le registre deviendrait un langage, et il
  vaudrait mieux que chaque pilier expose sa propre vérification.

## Alternatives écartées

**Ne rien vérifier dans la route générique.** C'est une fuite en écriture, et
pire : une pièce déposée sur un objet qu'on ne voit pas devient lisible par
tous ceux qui le voient.

**Une route de dépôt par pilier.** Six routes qui font le même travail, dont
cinq finiront par diverger sur le plafond de taille, la liste des extensions ou
le calcul de l'empreinte. Le versionnement de RF-GED-04, réimplémenté six fois,
serait juste cinq fois.

**Passer l'`objet_type` dans le chemin plutôt que dans le corps**
(`POST /pieces/activite/156`) pour qu'`exige()` puisse le lire. Le décorateur ne
lit pas non plus les paramètres de chemin au moment où il s'exécute, et cela
n'aurait de toute façon rien réglé pour la visibilité, qui demande une requête.

## Voir aussi

- [013](013-le-portail-ne-passe-pas-par-restreindre.md) — pourquoi le registre
  déclare une fonction et non un champ de périmètre.
- [009](009-garde-large-contenu-filtre.md) — le cas voisin : garde large,
  contenu filtré, pour un écran partagé.
- `docs/questions-ouvertes.md`, A49 et A50 — le plafond de taille et la liste
  des extensions, tous deux en hypothèse.

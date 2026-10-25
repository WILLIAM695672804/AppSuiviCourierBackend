# ADR 006 — Une seule table d'engagement, trois origines

**Statut** : accepté, 12 août 2026
**Contexte** : conception du pilier gouvernance

## Le problème

Le front de gouvernance décrit trois objets sur trois écrans :

| Écran | Type | Champs |
|---|---|---|
| Registre des décisions | `Decision` | référence, instance, séance, objet, échéance, état, avancement, structures chargées |
| Filiales | `PrescriptionFiliale` | référence, entité, objet, session d'origine, échéance, avancement, état |
| Représentations | `RecommandationExterne` | référence, organisation, objet, émise le, échéance, structure pilote, avancement, état |

**Ce sont les mêmes champs.** Ce qui les distingue n'est pas leur nature mais
leur **origine** : une instance du PAD, l'organe de gestion d'une filiale, une
organisation extérieure. Le suivi, lui, est identique — un objet, une échéance,
une ou plusieurs structures internes chargées, un avancement, un état.

Le front le dit d'ailleurs lui-même pour l'une des trois : « la recommandation,
qui engage une structure interne **exactement comme une décision d'instance** ».

## La décision

**Une seule table, `engagement`, avec une colonne `origine`.**

Elle est obtenue en renommant `decision_reunion` — livrée avec le pilier
activités pour le §19 — et en l'étendant. Trois clefs étrangères nullables et
mutuellement exclusives portent la provenance : `seance_id`,
`organe_gestion_id`, `organisation_externe_id`.

Les tables satellites suivent : `engagement_structure` (les structures chargées,
rang 1 = pilote), `engagement_jalon`, `engagement_observation`.

## Pourquoi

**Trois tables jumelles auraient triplé chaque règle.** Le calcul de l'état, de
l'avancement consolidé, du feu et de la relance est le même pour les trois. Les
écrire trois fois, c'est garantir qu'un jour deux écrans afficheront deux
chiffres — le projet a déjà payé cela avec les deux définitions du retard (A2).

**Le précédent existe au dépôt, deux fois.** `instruction_activite` porte une
colonne `origine` qui distingue instruction verbale et décision du DG plutôt que
deux tables jumelles. Et le pilier activités a étendu `relance` d'une colonne
`activite_id` au lieu de créer une seconde table de relances : « une relance
reste une relance ».

**Le lien avec les activités est conservé.** `instruction_activite` et
`decision_effet` référencent la table renommée. Une décision du CODIR qui
suspend une activité reste **la même ligne** que celle que la gouvernance suit,
et c'est exactement ce que le domaine décrit.

## Pourquoi renommer plutôt que garder `decision_reunion`

Parce que le nom serait devenu faux. Une recommandation d'une organisation
portuaire n'est pas une « décision de réunion », et un nom qui ment coûte plus
cher qu'un renommage : il fait hésiter à chaque lecture, et finit par faire
créer la table jumelle qu'on voulait éviter.

Le renommage est sûr : cinq fichiers du dépôt la référencent, tous écrits par
nous, tous couverts par des tests. `Activite.decision_reunion` conserve son nom
de champ côté Python — c'est bien une décision de réunion **dans ce contexte** —
et pointe vers `engagement` par `db_column`.

## Ce que la décision n'emporte pas

**Les séances ne sont pas unifiées avec les organes de filiales.** Une séance du
CODIR et une session du conseil d'administration d'une filiale se ressemblent,
mais la DSR n'y joue pas le même rôle : elle tient le secrétariat de l'une et
prépare seulement le dossier de l'autre. Les champs diffèrent réellement
(participants et ordre du jour d'un côté, état de préparation du dossier de
l'autre). Unifier là serait de la généralisation gratuite.

**Le planning des congés reste distinct du registre de disponibilité.** Le front
insiste : l'un enregistre une absence décidée, l'autre arbitre des souhaits
avant qu'ils ne le deviennent. Deux objets, deux moments.

## Conséquences

- La migration `noyau/0003` renomme et étend ; `activite/modeles.py` suit.
- Une contrainte `CHECK` garantit qu'une et une seule origine est renseignée :
  un engagement sans provenance ne serait rattachable à aucun écran.
- `engagement.avancement` est **calculé** depuis `engagement_structure`, par
  déclencheur, comme `activite.avancement_calcule` l'est depuis les tâches.

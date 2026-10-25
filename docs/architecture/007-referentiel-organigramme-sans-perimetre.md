# ADR 007 — Le référentiel de l'organigramme se lit sans périmètre

*Statut : accepté — 13 août 2026*

## Contexte

La règle du dépôt est sans exception : « une route déclare `auth=exige(PERM.…)`,
et appelle `restreindre()` dès qu'elle renvoie des données ». Elle protège
contre une fuite silencieuse : l'oubli ne produit aucune erreur, il montre
simplement à un agent ce qui concerne une autre direction.

`GET /referentiels/structures` est le premier endpoint qui ne peut pas s'y
plier. Sept écrans le lisent — cotation d'un courrier, enregistrement, rédaction
d'un départ, recherche, statistiques, signalement d'écart, et le référentiel de
la DSR lui-même. Ce n'est pas un écran de consultation : c'est la liste dans
laquelle on choisit **la structure vers laquelle on cote**.

Deux gardes étaient possibles, et aucune ne tient :

- `exige(PERM.ADM_STR)` fermerait la liste à tout le monde sauf à la DSR. Plus
  personne ne pourrait coter.
- `restreindre()` réduirait la liste au périmètre de l'agent. Or coter, par
  définition, c'est s'adresser à une structure **hors** de son périmètre. Un
  chef de service ne verrait que son service, et ne pourrait plus rien
  transmettre.

## Décision

`GET /referentiels/structures` porte `auth=session_seule` et n'appelle pas
`restreindre()`. Toute session ouverte lit l'organigramme en vigueur en entier.

Trois bornes encadrent la dérogation :

1. **Elle porte sur l'organigramme seul.** Structures, et le nom du responsable
   déduit du poste occupé. Rien de ce qui s'y rattache — courriers, décisions,
   activités, scores — ne se lit ainsi.
2. **Elle ne s'étend pas par prétérition.** Une nouvelle route sous
   `/referentiels` ne l'hérite pas : elle doit se justifier ou porter sa
   permission.
3. **Aucun chiffre d'activité ne sort de cette route.** `delaiMoyenJours` et
   `courriersEnCours` sortent à `null` et `0`. Le jour où le pilier courrier
   les alimentera, ils devront être servis ailleurs, sous périmètre — un
   compteur de courriers en cours par direction est une information de charge,
   pas un référentiel.

## Conséquences

`session_seule`, jusqu'ici réservé à `/moi`, `/deconnexion` et aux délégations
d'un responsable sur lui-même (§3.4), acquiert un quatrième usage documenté. Le
commentaire de `noyau/habilitation/dependances.py` le mentionne.

Ce que l'on accepte de divulguer : un agent connecté connaît la liste des
directions, filiales et succursales du Port, avec le nom de leur responsable.
C'est un organigramme — il est affiché dans les couloirs.

Ce que l'on refuse d'y ajouter : les chiffres. Le point 3 est la vraie borne ;
c'est celle qui sera tentée en premier, parce que la donnée est à portée de
requête et que l'écran de la DSR a déjà une colonne pour l'accueillir.

# 039 — Le cabinet cote au nom du Directeur général

28 août 2026. **Tranche la question [A75](../../../docs/questions-ouvertes.md)**, ouverte le matin même.

## Contexte

Le chef de service du Cabinet du Directeur général, connecté, ne voyait **aucun**
des 61 courriers du registre.

Le code appliquait exactement la règle de visibilité. Aucune de ses portes ne
s'ouvrait pour ce compte : zéro courrier dont le chef de file relève du
sous-arbre du cabinet, zéro cotation vers ce sous-arbre, aucune désignation
nominative, aucune session d'enregistrement rattachée. Son profil, *Responsable
de structure*, ne porte ni `ENR` ni `COT_DEL`.

Ce n'était pas un défaut de mise en œuvre : c'était une règle fausse. Elle
supposait que le cabinet est une structure comme une autre, qui reçoit des
courriers cotés vers elle.

**L'arbitrage, rendu en toutes lettres le 28 août 2026 :**

> « C'est chez moi que l'on enregistre et que l'on cote les ordres du directeur,
> car le directeur ne fait pas ça. »

## Décision

Un profil `CABINET` — *Cabinet du Directeur général* — porté par les comptes
rattachés à la structure `CAB`, en portée **`toutes`**.

**`COT_DEL` et non `COT`.** Les deux ouvrent la même route. `COT` est portée par
l'autorité qui cote ; `COT_DEL` par celui qui saisit la cotation d'un autre — et
le service distingue `decide_par` de `saisi_par`. C'est toute la question ici :
la décision reste celle du Directeur général, la frappe est celle du cabinet.
Donner `COT` au cabinet aurait inscrit le chef de service comme décideur au
registre. C'est faux, et un registre faux ne se rattrape pas.

**Portée `toutes`, parce que la permission sans la portée ne sert à rien.** `ENR`
dit ce que l'agent a le droit de faire, la portée dit sur quoi. Le cabinet en
portée `sous_arbre` aurait pu enregistrer un courrier qu'il n'aurait pas revu
ensuite — c'est-à-dire l'écran vide qui a motivé l'arbitrage.

**Pas de `CONF`.** Le registre confidentiel a ses propres tenants
([ADR 024](024-la-serrure-du-confidentiel-ne-ferme-pas-son-propre-registre.md)), et
rien dans l'arbitrage ne dit que le cabinet en est. Le cabinet voit donc 58
courriers là où le Directeur général en voit 61. La serrure du confidentiel est
posée avant les portes, et la portée `toutes` ne l'ouvre pas.

**Pas de `CLO`.** Clore un courrier n'est pas le coter. Le cabinet ouvre le
trajet, il ne le referme pas.

**`RESP` n'est pas retiré.** Les permissions s'additionnent : le chef de service
reste responsable de sa structure, et garde `COT` pour ce que le cabinet décide
en propre.

## Ce qui a été écarté

- **Une porte « avant cotation »** — le cabinet voit ce qui n'est pas encore
  coté, et le perd ensuite. Séduisant sur le papier ; mais on ne prépare pas la
  cotation d'un courrier pour cesser de savoir ce qu'il est devenu, et le
  cabinet aurait perdu de vue ce qu'il vient lui-même de coter.
- **Rattacher le cabinet à une session d'enregistrement.** Aucun développement,
  mais c'est la même portée obtenue par un chemin qui ment sur sa raison : le
  rattachement à un registre est l'acte d'habilitation d'un agent de session
  (ADR 024), et le cabinet n'en est pas un.

## Conséquences

La migration `0021` rattrape les comptes existants : c'est délibéré. Poser la
règle dans le seul semis aurait suffi pour une base neuve et laissé la base
réelle dans l'état qui a motivé l'arbitrage.

**Le rattrapage vise `CAB` seule, pas son sous-arbre.** Le Service du courrier
central et les deux secrétariats y sont rattachés, et ce sont des agents de
session : leur habilitation est le rattachement à un registre, pas la portée.
Un premier jet a élargi leur périmètre à `toutes` — une règle de sécurité
échangée contre une autre, sans que personne ne l'ait demandé. Il a fallu le
défaire à la main.

## Ce qui reste ouvert

- **Le confidentiel.** Le cabinet du Directeur général en traite-t-il ? La
  question n'a pas été posée, et la réponse par défaut est la plus fermée.
- **Les autres cabinets.** Le Directeur général adjoint a un secrétariat, pas un
  cabinet. Si un second cabinet apparaît, c'est la structure `CAB` codée en dur
  dans la migration qu'il faudra revoir — le profil, lui, se réattribue.

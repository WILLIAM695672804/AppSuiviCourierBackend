# ADR 009 — Un écran d'accueil partagé : garde large, contenu filtré

*Statut : accepté — 13 août 2026*

## Contexte

`GET /administration/tableau-de-bord` sert un écran unique à quatre postes
distincts : l'administrateur fonctionnel (`ADM_HAB`), l'administrateur de
l'organigramme (`ADM_ORG`), le poste d'audit (`AUDIT`) et l'administrateur
technique (`ADM_TEC`). Aucun de ces postes ne porte les permissions des trois
autres — le §3.9 et le §3.12 les séparent délibérément : qui distribue les
droits ne doit pas être qui tient les journaux.

La règle du dépôt veut qu'une route nomme la permission qu'elle exige. Elle ne
dit pas laquelle nommer quand la réponse contient quatre blocs qui relèvent de
quatre permissions différentes.

Trois montages étaient possibles :

- **Exiger les quatre.** L'accueil de l'administration devient inaccessible à
  tous les postes réels, et seul un compte cumulant les quatre — qui n'existe
  pas dans l'institution — l'ouvrirait.
- **Exiger l'une quelconque, sans filtrer le contenu.** L'administrateur de
  l'organigramme reçoit les accès signalés du journal d'audit. Rien ne le
  signale : l'écran, lui, cache bien le bloc.
- **Quatre routes, une par bloc.** Le front en fait quatre appels, l'écran
  clignote à chaque changement de période, et les quatre blocs — qui se lisent
  ensemble — arrivent séparément.

## Décision

La route porte `auth=exige(PERM.ADM_HAB, PERM.ADM_ORG, PERM.AUDIT,
PERM.ADM_TEC)` — `exige()` est un **ou** — et **le service remplit chaque bloc
selon ce que le compte porte réellement**. Un bloc non autorisé sort vide, pas
absent : le schéma de réponse est le même pour tout le monde.

Le filtre vit dans `noyau/administration/lecture.py::tableau_de_bord`, à côté
des requêtes qu'il conditionne, et non dans `api.py` : c'est une règle de ce
qui se lit, pas une règle de routage.

## Conséquences

Le front garde ses propres gardes (`usePermission`) et continue de piloter son
affichage ; elles ne protègent rien, elles évitent un bloc vide. La protection
est au serveur.

Un bloc ajouté à cette réponse doit décider de sa permission **au moment où on
l'ajoute**. C'est le point faible du montage : l'oubli ne produit aucune erreur.
Les tests le couvrent bloc par bloc (`test_sans_AUDIT_les_journaux_ne_sortent_pas`,
`test_les_anomalies_de_l_organigramme_ne_sortent_pas_sans_ADM_ORG`) et tout
nouveau bloc doit venir avec le sien.

`restreindre()` n'est pas appelé, pour la même raison qu'en traçabilité : le
tableau de bord d'une institution est institutionnel, et un total réduit au
périmètre de son lecteur n'apprend rien à personne. La garde repose donc
entièrement sur la permission.

## Ce qui invaliderait cette décision

Un cinquième bloc dont la permission recouperait mal les quatre autres — par
exemple un bloc lisible par un poste qui ne porte aucune des quatre. Il faudrait
alors élargir la garde une fois de plus, et la liste des permissions acceptées
finirait par ne plus rien exiger du tout. À ce moment, découper l'écran en
plusieurs routes redevient le bon montage.

De même si un bloc devenait coûteux à calculer : le filtre évite aujourd'hui le
calcul (les fonctions ne sont pas appelées), mais une réponse qui porterait dix
blocs dont deux servis obligerait à revoir le découpage.

## Alternatives écartées

**Exiger les quatre permissions** — ferme l'accueil à tous les postes réels.

**Une permission dédiée `ADM_BORD`** — ajouterait une neuvième permission
d'administration à distribuer, sans répondre à la question : elle dirait qui
ouvre l'écran, pas qui voit quel bloc.

**Quatre routes** — techniquement plus propre, mais les quatre blocs se lisent
ensemble : « trois cents opérations » ne veut rien dire sans « et douze
structures sur quinze n'en ont fait aucune ».

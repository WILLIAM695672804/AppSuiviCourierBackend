# ADR 016 — Une hypothèse ne se tranche qu'en citant sa source

**Statut.** Acceptée — 14 août 2026.
**Portée.** `noyau/parametres/services.py`, `noyau/parametrage/api.py`, neuvième
onglet de l'écran de paramétrage.

## Contexte

La table `parametre` porte les règles de gestion du système : délais, seuils,
plafonds. Une bonne part d'entre elles sont marquées `hypothese` — la conception
les a inventées faute de réponse du métier, et `docs/questions-ouvertes.md` en
tient la liste avec, pour chacune, qui doit trancher (ADR 005).

Jusqu'ici, **aucune route ne lisait ni n'écrivait cette table**. Seul
`noyau/parametres/service.py` la consultait, pour le compte du code applicatif.
Trancher une question ouverte se faisait donc par un `UPDATE` en SQL.

Trois conséquences, par gravité croissante :

1. l'arbitrage du client passait par le développement, à son rythme ;
2. rien ne garantissait qu'il laisse une trace — ni qui avait décidé, ni sur
   quel document ;
3. rien n'empêchait de faire passer une règle en `acte` **sans source**, ce qui
   revient à donner à une invention l'étiquette d'une décision. C'est pire que
   l'invention assumée : l'hypothèse annonce ce qu'elle est, le faux acte non.

Le troisième point est le vrai sujet. La consigne permanente du projet — « ne
pas changer une règle marquée `hypothese` en base sans arbitrage écrit » — était
adressée à l'humain, et rien dans le code ne la faisait respecter.

## Décision

**La source est une condition d'écriture, portée par le service, et non un champ
de formulaire parmi d'autres.**

Deux gestes distincts, sur deux routes, plutôt qu'un `statut` modifiable :

| Geste | Route | Ce qu'il exige |
|---|---|---|
| corriger | `PATCH /parametrage/regles-metier/{cle}` | rien sur une hypothèse ; une source sur un acte |
| trancher | `POST /parametrage/regles-metier/{cle}/arbitrage` | **une source, toujours** |

Quatre règles en découlent.

**1. Corriger une hypothèse est libre.** C'est une invention de la conception ;
l'ajuster ne fait que remplacer une invention par une autre, ce que le statut
annonce déjà. Exiger une justification ici aurait produit des sources bidon.

**2. Modifier un acte exige de citer la décision qui le change.** Sans quoi le
seuil arbitré redevient une supposition tout en gardant l'étiquette d'un
arbitrage — la situation exacte que cet ADR existe pour empêcher.

**3. Trancher exige la source, sans exception ni valeur par défaut.** La chaîne
est nettoyée puis testée non vide : `"   "` est refusé comme `""`.

**4. Un acte ne redevient jamais une hypothèse.** Il n'existe aucune route pour
cela, et `trancher_regle` refuse une règle déjà actée. Une décision qui change se
remplace par une autre décision, avec sa propre source — pas par un retour à
l'incertitude, qui effacerait qu'un arbitrage a eu lieu.

Trancher efface `a_trancher_par` : garder le nom ferait réclamer à l'écran un
arbitrage déjà rendu.

## Pourquoi

Parce qu'une règle que seul un développeur peut changer n'est pas une règle
paramétrable, quel que soit le nom de la table — et parce que la distinction
entre `hypothese` et `acte` ne vaut que si le code la défend. Une distinction
qui repose sur la discipline de celui qui écrit le SQL n'aura tenu que le temps
de la première urgence.

Le choix des deux routes fait le travail : la source est obligatoire **par la
forme de l'API**, pas par une validation qu'on peut oublier de rappeler.

## Conséquences

**Le cache se vide après le commit, jamais dedans.**
`parametres.service.valeur()` met en cache par processus. Vider avant le commit
ouvre une fenêtre où une autre requête repeuple le cache avec l'ancienne valeur,
encore seule visible en base — et le serveur applique alors l'ancien seuil
jusqu'au redémarrage. Deux serveurs derrière un répartiteur appliqueraient deux
règles différentes sans que rien ne le signale. Un test le vérifie sur le chemin
complet, de la route à `service.valeur()`.

`transaction.on_commit` aurait été le mécanisme idiomatique, mais il ne se
déclenche pas sous les tests non transactionnels de pytest-django : le test qui
protège ce point n'aurait rien protégé.

**La valeur est validée contre `type_valeur` à l'écriture.** Sans ce contrôle,
`int('4O')` lève à la *lecture*, dans le calcul d'un délai, à des kilomètres de
la saisie qui l'a causée — et l'écran d'origine ne montre rien d'anormal.

**`docs/questions-ouvertes.md` ne se met plus à jour tout seul.** L'écran permet
désormais de trancher sans toucher au dépôt ; la fiche de la question, elle,
reste dans le fichier. Le journal (`regle_tranchee`, avec sa source) est
l'enregistrement qui fait foi ; la section *Tranchées* du fichier est une reprise
à faire à la main, et c'est le prix assumé de la décision.

**Le nombre d'hypothèses devient un indicateur.** L'onglet l'affiche en tête —
« 12 règles sur 27 sont des hypothèses ». C'est la mesure de ce qui reste à
arbitrer, lisible par celui qui doit arbitrer.

## Ce qui invaliderait cette décision

Si un arbitrage devait engager plusieurs directions — un seuil que la DSR
propose et que le CODIR valide — la source unique ne suffirait plus, et il
faudrait le workflow à deux acteurs écarté ci-dessous. Le signe précurseur sera
une source qui dit « proposition de… » plutôt que « décision de… ».

Si le volume des règles dépassait ce qu'un écran peut montrer d'un coup — au-delà
de la centaine — l'affichage « hypothèses en tête » cesserait de suffire et il
faudrait un filtre par statut et par domaine.

## Alternatives écartées

**Un champ `statut` modifiable comme un autre, dans un `PATCH` générique.**
Écarté parce qu'il aurait rendu les quatre règles impossibles à exprimer :
`statut = acte` sans source aurait été une saisie valide.

**Un workflow de validation à deux acteurs** — l'un propose, l'autre approuve.
Écarté comme disproportionné aujourd'hui : `ADM_PAR` est déjà une permission
rare, et le journal enregistre qui a tranché. Ajouter une étape aurait surtout
garanti que les arbitrages restent en attente.

**Laisser le SQL.** Écarté : c'est l'état de fait qu'on corrige.

## Voir aussi

- [ADR 005 — Les règles se paramètrent, elles ne se codent pas](005-regles-parametrables.md)
- `docs/questions-ouvertes.md`, dont cet ADR ouvre la sortie

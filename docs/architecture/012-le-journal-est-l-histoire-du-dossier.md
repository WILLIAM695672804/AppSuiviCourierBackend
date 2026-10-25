# ADR 012 — Le journal du noyau est l'histoire du dossier

*13 août 2026 — acceptée*

## Contexte

Le pilier « dossiers à instruire » (§3.6, §3.7) doit rendre trois choses que le
descriptif nomme explicitement :

- le **circuit complet** sur la fiche d'instruction, avec les étapes franchies
  et celles qui restent ;
- le **retour à une étape antérieure** avec son motif, sans rien perdre du
  chemin parcouru (RF-BPM-06) ;
- les **versions successives** d'une pièce, pour pouvoir dire sur quoi la
  décision a été prise (RF-GED-04).

Deux tentations se présentaient, et elles reviennent à la même : ajouter au
pilier ses propres tables d'historique et de pièces, à côté de celles du socle.

## Décision

**Le dossier n'a pas de table d'événements.** Son historique *est* le journal
du noyau : `evenement`, avec `objet_type = 'dossier'` et `objet_id` = la clé du
dossier. Le franchissement d'étape se lit dans `donnees->>'etapeApres'`, l'état
« Retourné » se lit du dernier événement, et la fiche d'instruction reconstitue
son fil à partir de là.

**Le dossier porte en revanche ses propres pièces** : `piece_dossier` et
`version_piece_dossier`, chaînées par `piece_precedente_id`, plutôt que la
`piece_jointe` du socle.

**Le circuit est figé à cinq étapes** — qualification, instruction, validation,
notification, clos — et ne passe pas par le moteur `circuit` du socle.

## Pourquoi

### Une seule histoire

Une table `evenement_dossier` aurait produit deux récits du même objet. L'un
dirait « affecté à la DAF le 3 mars », l'autre « aucun événement ». Il ne s'agit
pas d'un risque théorique : les deux tables auraient été alimentées par des
chemins différents (le service pour l'une, le journal pour l'autre), et la
première écriture qui oublie l'une des deux crée un dossier dont l'histoire
dépend de l'écran qu'on ouvre. La table `evenement` est partitionnée, indexée
sur `(objet_type, objet_id)`, et déjà lue par la traçabilité et l'audit : la
question « qu'est-il arrivé à cet objet ? » a une seule réponse dans ce dépôt.

### Mais des pièces à part

La `piece_jointe` du socle est ancrée sur `courrier_id`. Le pilier courrier
n'existe pas en Django, et une pièce de dossier n'a pas toujours de courrier
d'origine — un dépôt direct n'en a aucun. Y accrocher les pièces de dossier
aurait supposé soit une colonne nullable qui vide la contrainte de son sens,
soit un courrier fantôme créé pour la forme.

Le versionnement pèse dans le même sens : RF-GED-04 demande de garder les
versions précédentes d'une pièce d'instruction, ce que le socle ne prévoit pas
pour les pièces de courrier. Les deux besoins ne sont pas les mêmes, et les
confondre aurait fait porter à la table du courrier un versionnement dont il n'a
pas l'usage.

### Le moteur `circuit` du socle est inutilisable ici

`instance_circuit` référence `cotation_structure` — donc le courrier. Et
`circuit_regle` sélectionne son circuit par **sens** et **nature de courrier**.
Un dossier ouvert en dépôt direct n'a ni l'un ni l'autre. Le brancher aurait
supposé d'inventer un courrier pour chaque dossier, ou d'ajouter au moteur une
seconde façon de sélectionner ses règles — c'est-à-dire de le réécrire.

Cinq étapes figées ne sont pas une régression : le §3.7 les nomme, elles ne
varient pas par typologie dans le descriptif, et le jour où elles varieront, le
moteur du socle sera de toute façon à revoir pour l'ancrage.

## Conséquences

- Toute écriture du pilier dossiers **doit** inscrire son événement : ce n'est
  pas une bonne pratique de traçabilité ici, c'est la seule source de la fiche.
  Un service qui l'oublie produit un dossier sans histoire — pas un dossier dont
  l'histoire est incomplète ailleurs.
- Les événements de dossier portent un `donnees` structuré (`etapeAvant`,
  `etapeApres`, `reference`). Ces clés sont lues par `lecture.py` : les renommer
  casse le circuit affiché, sans erreur ni test rouge côté écriture.
- L'archivage scelle les `version_piece_dossier`, pas les `piece_jointe`.
- Si le pilier courrier arrive un jour avec ses propres pièces, les deux tables
  coexisteront. C'est assumé : elles ne portent pas le même objet.

## Ce qui invaliderait cette décision

- **Le volume.** La table `evenement` porte toute la traçabilité de
  l'institution. Si la lecture de la fiche d'instruction devient lente malgré la
  partition et l'index `(objet_type, objet_id)`, une vue matérialisée du fil de
  chaque dossier serait le premier recours — mais elle resterait une projection,
  pas une seconde source.
- **Des étapes qui varient par typologie.** Si le Port autonome de Douala
  confirme que l'instruction d'une autorisation d'occupation du domaine ne suit
  pas le même circuit qu'une réclamation, les cinq étapes figées ne tiennent
  plus. Il faudra alors un moteur — et la question de réutiliser ou non celui du
  socle se posera à nouveau, dans un contexte où il aura peut-être été détaché
  de `cotation_structure`.
- **Une exigence légale de journal immuable propre au dossier.** Si un texte
  impose au fonds d'archives un registre distinct de celui de l'application, il
  ne s'agira plus d'un doublon mais de deux objets différents.

## Alternatives écartées

**Une table `evenement_dossier`.** Écartée : deux récits du même objet, et
l'audit aurait dû interroger deux sources pour répondre à une question.

**Réutiliser `piece_jointe` avec un `courrier_id` nullable.** Écartée : une
contrainte qui accepte `null` n'est plus une contrainte, et le versionnement
aurait pesé sur les pièces de courrier sans leur servir.

**Brancher le moteur `circuit`.** Écartée : il est ancré sur le courrier par
`cotation_structure` et sélectionne par sens et nature de courrier. Voir
ci-dessus.

## Voir aussi

- [ADR 003](003-django-proprietaire-du-schema.md) — le schéma appartient à Django.
- [ADR 010](010-la-matrice-se-recalcule.md) — rien de calculable n'est stocké.
- [ADR 011](011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) — le pilotage lit
  désormais l'instruction des dossiers ; la moitié de [A30](../../../docs/questions-ouvertes.md)
  est fermée.

# 019 — Un rapport porte sur une période close

*Statut : acceptée — 14 août 2026*

## Contexte

Le pilotage rendait déjà six restitutions : le cockpit, le tableau de bord
d'une structure, celui des trois périmètres, les statistiques annuelles, les
analyses croisées, la note de synthèse. Toutes répondent à la même question —
**où en sommes-nous aujourd'hui** — et toutes changent d'un matin à l'autre.

L'écran D-03 en demandait une septième, d'une autre nature : un *rapport
périodique*, sur une période et un périmètre choisis, exportable. La tentation
était de le construire comme les autres : les mêmes mesures, avec un filtre de
dates posé par-dessus.

Elle était fausse, et pour une raison qui ne se voit qu'à l'usage. Un rapport
se transmet. Il est édité, imprimé, joint à un ordre du jour, cité en séance.
S'il est calculé « à ce jour », le rapport de mars édité en avril et le rapport
de mars réédité en décembre ne portent pas les mêmes chiffres — et le second a
raison. Personne ne peut alors vérifier le premier, ni le contester : le
document a cessé d'être un document.

## Décision

Un rapport porte sur une période **close**, et sur elle seule.

1. **Les bornes commandent les mesures.** `pilotage/periodes.py` résout la
   période demandée en un couple de dates, et `pilotage/rapports.py` ne mesure
   qu'entre ces dates. Les mesures d'état — l'avancement moyen, les activités à
   l'heure — sont prises **à la fin de la période**, jamais à la date du jour.
2. **Une obligation est rattachée à son échéance, pas à son dépôt.** Une
   production due en mars et déposée en mai reste une production de mars, en
   retard. La rattacher au mois du dépôt aurait fait disparaître le retard du
   rapport de mars — et un retard qui s'efface tout seul n'est jamais corrigé.
3. **Une période non close est ramenée, pas refusée.** Demander le trimestre en
   cours rend le trimestre précédent, avec `periodeRamenee` à vrai ; l'écran
   l'affiche. C'est le raisonnement de l'[ADR 009](009-garde-large-contenu-filtre.md)
   appliqué au temps : un lien partagé la veille d'une clôture ne doit pas
   rendre 400 à qui n'a rien fait de mal.
4. **L'export est servi par le serveur.** Le CSV est produit côté serveur, et
   `GET /pilotage/rapports/export` inscrit un accès de type `export` au journal.
   C'est la **seule** lecture du pilotage qui se trace : sortir une donnée du
   système est un acte au sens du §3.12, alors qu'ouvrir un tableau de bord est
   une navigation.

## Conséquences

Le pilotage gagne un module de calendrier (`periodes.py`) et quelques mesures
bornées dans `mesures.py`. Ces mesures s'ajoutent aux existantes plutôt que de
les remplacer : les deux questions coexistent, et c'est bien qu'elles portent
des noms différents.

`dossier.lecture.instruction_dans_le_delai` accepte désormais une borne basse
(`depuis`). Sans elle, le compte reste cumulatif — ce qu'attendent les tableaux
de bord.

Un CSV assemblé par le navigateur aurait été plus simple à écrire et n'aurait
laissé **aucune trace**. C'est précisément ce qu'un audit cherche et ne
trouverait pas ; le surcoût d'un export serveur se paye une fois.

Les périodes sont **civiles** — janvier à mars, janvier à décembre. L'exercice
budgétaire du Port pourrait ne pas commencer en janvier ; faute de source, la
question reste ouverte (A52).

## Ce qui invaliderait cette décision

Une source qui fixerait l'exercice budgétaire du Port sur un découpage non
civil : les bornes changeraient, et avec elles la définition de « période
close ». Le calcul, lui, resterait le même — c'est pourquoi les bornes vivent
dans un seul module.

Une demande d'**archiver** un rapport signé, aussi. Aujourd'hui rien n'est figé
en base : le rapport est recalculé à chaque demande, et il est reproductible
parce que ses bornes le sont, pas parce qu'on en garde une copie. Le jour où
l'institution voudra opposer un rapport à un tiers, il faudra une pièce et une
empreinte ([ADR 017](017-la-garde-des-pieces-est-portee-par-le-service.md)) —
et ce sera une autre décision.

## Alternatives écartées

**Réutiliser le tableau de bord avec un filtre de dates.** Le moins de code, et
la mauvaise réponse : les mesures d'état auraient continué de bouger, et deux
éditions du même rapport auraient différé sans que rien ne le signale.

**Refuser une période non close en 400.** Défendable en théorie ; en pratique,
c'est l'écran d'un agent qui casse le 1er du mois parce qu'un lien traînait dans
un courriel. L'ADR 009 a déjà tranché ce genre d'arbitrage dans l'autre sens.

**Fabriquer le CSV côté navigateur.** Plus simple, plus rapide, et sans aucune
trace. Le §3.12 signale toute sortie de données quel que soit son volume : un
export invisible au journal aurait vidé cette exigence de son contenu.

## Voir aussi

- [ADR 009](009-garde-large-contenu-filtre.md) — garde large, contenu filtré
- [ADR 011](011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) — « non mesuré » n'est pas zéro
- [questions ouvertes](../../../docs/questions-ouvertes.md) — A52, l'exercice budgétaire

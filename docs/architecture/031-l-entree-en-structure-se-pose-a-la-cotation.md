# 031 — L'entrée en structure se pose à la cotation, elle ne se saisit pas

24 août 2026. S'appuie sur la
[012](012-le-journal-est-l-histoire-du-dossier.md) et la
[022](022-le-registre-est-une-porte-de-visibilite.md).

## Contexte

Le cahier des charges demande que, « pour les structures, le suivi soit géré par
leur bureau d'ordre : suivi de l'entrée et de la sortie de la structure ». Le
Port a précisé la lecture : **le bureau d'ordre d'une structure, c'est son point
focal** — pas un poste nouveau, celui qui existe déjà et porte le profil
`POINT_FOCAL`.

Il manquait donc deux choses, et deux seulement : un registre des passages, et
la permission d'y écrire.

Restait à décider **quand un courrier entre** dans une structure. Deux dates se
présentaient :

- la date où le point focal le **saisit** — ce que fait un bureau d'ordre
  papier ;
- la date où le courrier lui est **coté** — ce que la base sait déjà.

La première est celle qu'on écrit spontanément. Elle a un défaut qu'on ne voit
qu'à l'usage : une structure lente à ouvrir son courrier voit son délai de
traitement se raccourcir d'autant, puisque le compteur ne démarre qu'au moment
où elle veut bien le démarrer. Le temps mort du bureau d'ordre — celui que la
DSR cherche précisément à mesurer — disparaît de la mesure qui devait le rendre.

## Décision

L'entrée d'un courrier dans une structure est **posée par le moteur**, au moment
où la cotation à cette structure est écrite : un déclencheur
`cotation_structure_passage` sur `cotation_structure` insère la ligne dans
`passage_structure`. Elle n'est jamais saisie.

Le point focal **accuse réception** — un second horodatage, distinct de
l'entrée — puis **prononce la sortie**, avec un motif obligatoire.

L'écart entre `entre_le` et `accuse_le` est le temps mort du bureau d'ordre. Il
est mesuré parce qu'il n'est pas déclaré.

## Conséquences

- Un passage existe pour toute cotation, y compris celles écrites avant cette
  décision : la migration les rattrape. Aucun courrier coté n'est hors registre.
- `cotation_structure_id` est **unique** dans `passage_structure` : une même
  cotation ne peut pas ouvrir deux passages. Une structure cotée deux fois sur
  le même courrier a bien deux passages — c'est le cas voulu, un aller-retour.
- Le point focal reçoit `BO_STR` **et** `AFF`. Un bureau d'ordre qui reçoit sans
  pouvoir remettre au collaborateur laisse le courrier sur la table.
- La sortie exige un motif (`reponse`, `retour`, `transmission`, `cloture`,
  `autre`), garanti par un `CHECK`, pas seulement par le service. Un registre de
  sorties sans motif ne se relit pas.
- Le registre du voisin est **fermé** : lire le bureau d'ordre d'une structure
  hors de son périmètre rend 404 (D5), pas 403.
- Coût : deux horodatages là où le métier en voyait un. L'écran doit expliquer
  la différence, sans quoi « entré » et « accusé » se lisent comme un doublon.

## Ce qui invaliderait cette décision

Que le Port confie le bureau d'ordre d'une structure à un poste distinct du
point focal — un secrétariat de direction, par exemple. La permission `BO_STR`
existe justement pour que ce déplacement soit une affaire de profil, pas de
code ; mais la phrase « le bureau d'ordre c'est le point focal » deviendrait
fausse et devrait être réécrite ici.

Ou qu'un courrier puisse entrer dans une structure **sans cotation** — remis de
la main à la main, déposé au guichet de la direction. Le déclencheur ne le
verrait pas, et le registre serait incomplet sans que rien ne le signale. Il
faudrait alors une entrée saisie, à côté de l'entrée posée, et les distinguer.

## Alternatives écartées

**Faire saisir l'entrée par le point focal.** Écarté pour la raison ci-dessus :
la mesure du délai serait devenue flatteuse pour la structure qui traîne, ce qui
est exactement l'inverse de ce que la DSR demande.

**Déduire les passages du journal, sans table.** L'ADR 012 dit que la fiche de
vie est le journal ; on aurait pu s'y tenir. Mais `evenement` est partitionnée
et sans contrainte d'unicité exploitable : garantir « un seul accusé par
passage » aurait demandé de relire l'historique à chaque écriture. Le registre
est un **état courant**, pas une histoire ; il a droit à sa table.

**Réutiliser `circuit_etape`.** La table existe et elle est vide : le trajet
réel d'un courrier n'a jamais été communiqué (A24). Y brancher le bureau d'ordre
aurait fait dépendre une règle connue d'une règle qui ne l'est pas.

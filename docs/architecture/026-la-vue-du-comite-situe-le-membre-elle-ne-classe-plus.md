# 026 — La vue du Comité situe le membre, elle ne classe plus

*Statut : acceptée — 25 août 2026*

## Contexte

La vue d'ensemble du Comité de direction ouvrait sur un histogramme intitulé
« Score global des directions » : une colonne par direction classée, servie par
le champ `scoreParStructure`. C'était le premier panneau de l'écran, et
`pilotage/vue_comite.py` le justifiait ainsi — le Comité est le conseil des
directeurs, il délibère sur les directions les unes en face des autres.

Le raisonnement tenait tant que les directions se comptaient sur une main. Il ne
tient plus depuis que l'organigramme réel est chargé ([ADR 025](025-l-organigramme-reel-se-charge-il-ne-se-migre-pas.md)) :
soixante-dix-sept structures sur cinq niveaux. Combien entrent au classement ne
se décide pas ici — c'est le drapeau `ligne_statistiques` du niveau
hiérarchique, et il est administré. Mais il suffit qu'un administrateur classe
un étage un peu fin pour que le panneau, qui occupe un tiers de largeur dans une
grille de trois, passe de six colonnes à trente. Alors les sigles se
chevauchent, les barres deviennent des traits, et le membre ne retrouve plus la
sienne — le graphique n'est plus lu, il est traversé du regard.

Un directeur ouvre pourtant cet écran avec une question précise, et une seule :
**où est ma direction, et est-ce qu'elle monte ?**

## Décision

**Le premier panneau montre la position de la direction du membre — son score
et son rang — et non plus le classement colonne par colonne.**

Le champ `scoreParStructure` disparaît de la réponse `/comite/vue-ensemble`. Il
est remplacé par `positionMembre`, servi par `pilotage.vue_comite._position_membre` :
sigle, libellé, score global, feu, rang, rang du mois précédent, effectif classé
et moyenne du collège. Il sort à `null` à deux titres — le membre ne dirige
aucune structure, ou la sienne n'entre pas au classement du mois — et l'écran le
dit alors en toutes lettres plutôt que d'afficher un rang inventé.

**Le classement entier reste calculé.** Il alimente les repères, le score moyen
et la dispersion : ce qui change est ce que la réponse *expose*, pas ce qu'elle
mesure.

**La comparaison n'est pas perdue, elle change de forme.** Elle passe dans les
deux séries mensuelles qui existaient déjà — le score moyen du collège et
l'écart entre extrêmes. Elles répondent à « le collège progresse-t-il ? » et
« se disperse-t-il ? » sans dépendre du nombre de directions ni de la largeur de
l'écran, ce qu'un histogramme à trente colonnes ne saura jamais faire.

## Conséquences

- La restitution du Comité reste **institutionnelle par son calcul** et devient
  **personnelle par son premier panneau**. La dérogation au cloisonnement par
  structure ne s'élargit pas : elle se réduit, la réponse n'exposant plus les
  scores nominatifs des autres directions.
- Un membre qui veut le classement complet passe par la matrice de scoring
  (`/performance/classement`), qui est faite pour cela : un tableau trié se lit
  à trente lignes, un histogramme non.
- `test_le_comite_voit_toutes_les_directions_pas_seulement_la_sienne` est
  remplacé par `test_le_membre_voit_le_score_et_le_rang_de_sa_direction`, qui
  vérifie en outre que `scoreParStructure` **n'est plus servi** — un champ
  retiré du schéma mais laissé dans la vue serait passé inaperçu.
- Le serveur de démonstration du front suit le même contrat.

## Ce qui invaliderait cette décision

Une consigne écrite du Comité demandant à délibérer sur le classement affiché en
séance. La réponse ne serait pas de rétablir l'histogramme, mais de servir un
**tableau** trié et paginé : c'est la forme qui supporte le nombre.

Un resserrement du périmètre classé — si `ligne_statistiques` ne portait plus
que sur les directions métier, l'histogramme redeviendrait lisible. La décision
resterait défendable pour autant : dix colonnes se lisent, mais un score et un
rang se lisent plus vite. Et le périmètre classé peut s'élargir à nouveau demain,
sans que personne ne rouvre cet écran.

## Alternatives écartées

**Garder l'histogramme et n'y afficher que les dix premières directions.** Un
classement tronqué met en évidence exactement ceux qui n'ont pas besoin de l'être
et efface ceux qui décrochent. Et le membre dont la direction est onzième ne voit
plus rien du tout.

**Garder l'histogramme en le rendant défilable.** Le graphique redevient lisible,
mais la question du directeur — où suis-je ? — demande alors de faire défiler
jusqu'à se trouver. Un écran de restitution ne se fouille pas.

**Mettre la colonne du membre en évidence par la couleur.** C'est ce qui était
fait, en substance, par la phrase sous le graphique. Une colonne surlignée parmi
trente colonnes larges de deux pixels reste illisible : le problème n'était pas
l'identification, c'était la densité.

# 042 — La note de travail est une table à part, distincte du fil d'observations

*acceptée — 28 août 2026*

## Contexte

Le pilier suivi devait servir l'écran C-01, qui porte une carte « Mes notes de
traitement », sous-titrée dans le front : **« Note privée · visible par ma
hiérarchie »**. Le dossier montre par ailleurs, comme la fiche, le fil
d'observations du courrier.

Or le fil d'observations obéit à une règle arbitrée par le Port le 26 août
2026, et écrite telle quelle dans `services.publier_observation` : **tout
lecteur écrit, tout lecteur lit, jamais modifiable**. La table `observation` ne
porte donc ni colonne de visibilité, ni colonne de modification — l'absence est
la règle, pas un oubli.

L'économie apparente consistait à ajouter une colonne `privee` à
`observation_courrier` et à faire porter les deux usages par la même table. Un
booléen contre une table : le calcul semblait fait.

Il ne l'était pas. Poser `privee` sur la table qui porte l'arbitrage, c'est
défaire l'arbitrage dans la table qui l'incarne. Six mois plus tard, personne ne
saurait plus dire si le fil du Port est public par principe ou public par
défaut, et la première demande d'évolution — « on pourrait masquer une
observation ? » — trouverait la colonne déjà là, prête à dire oui.

## Décision

Les notes de traitement vivent dans une table `note_traitement`, distincte de
`observation_courrier`. Elle porte `privee BOOLEAN NOT NULL DEFAULT TRUE`, un
auteur, un texte et une date de publication — rien qui permette de la modifier.

Une note privée se lit par son auteur et par les lecteurs dont la portée couvre
la structure de l'auteur ; `courrier.suivi._notes_lisibles()` est le seul
endroit où cette règle s'écrit. Une note ouverte se lit par tout lecteur du
courrier, comme une observation.

Ni l'une ni l'autre n'inscrit d'événement au journal. Pour la note privée, la
raison est directe : l'événement aurait annoncé à toute la fiche de vie
l'existence d'un texte que la fiche de vie ne montre pas — la trace aurait
trahi ce que la note protège. La note ouverte suit sa jumelle, faute de quoi
l'absence d'événement serait elle-même un indice.

## Conséquences

Le dossier de traitement affiche deux fils côte à côte, et cela demande d'être
dit à l'écran : les notes portent « privée » ou « ouverte » sur chaque ligne, et
pas seulement en tête de carte — une note écrite privée hier se relit à côté
d'une note ouverte, et rien d'autre ne les distingue.

Deux tables à interroger là où une aurait suffi. Le coût est réel et il est
borné : le dossier ne charge qu'un courrier à la fois.

La règle de lecture est portée par une fonction, donc testable ; c'est ce que
`test_une_note_privee_ne_sort_pas_de_la_hierarchie` éprouve. L'échec de cette
règle ne provoque aucune erreur — juste un texte de travail lu par qui ne
devait pas. C'est exactement le genre de défaut qu'un test doit tenir, parce que
l'usage ne le révélera jamais.

En portée `toutes` — le CODIR, la DSR — les notes privées sont lisibles. C'est
assumé : une note de travail n'est pas un secret, c'est un brouillon. Le
confidentiel, lui, reste fermé par `visibles()` en amont, et cette décision n'y
touche pas.

## Ce qui invaliderait cette décision

Si le Port revenait sur l'arbitrage du 26 août et demandait que le fil
d'observations lui-même puisse porter des lignes restreintes, les deux tables
auraient la même forme et la même règle : il faudrait alors les fusionner, et
cette décision n'aurait plus d'objet.

De même si le Port demandait qu'une note privée laisse une trace visible dans la
fiche de vie — « untel a pris une note » sans le texte. La note deviendrait un
acte, et un acte s'inscrit au journal.

## Alternatives écartées

**Une colonne `privee` sur `observation_courrier`.** Écartée pour la raison
développée en contexte : elle défait dans la table l'arbitrage que la table
porte.

**Une note stockée hors base, côté client.** Écartée sans hésiter : une note qui
disparaît au changement de poste n'est pas tenue, et l'agent le découvre le jour
où il en a besoin.

**Réserver les notes à l'agent affecté.** Écartée parce que le responsable qui
ouvre le dossier de son agent avant de le relancer a précisément besoin de lire
où il en est. C'est le sens de « visible par ma hiérarchie » : la note privée
est privée vis-à-vis des autres structures, pas vis-à-vis de la sienne.

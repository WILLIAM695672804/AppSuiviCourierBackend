# 040 — La file d'affectation est un onglet du registre

*acceptée — 28 août 2026*

## Contexte

Le client a redit le 28 août 2026 le trajet d'un courrier arrivé :

> « Lorsque l'on cote à une structure, c'est au directeur de la structure ou son
> secrétariat que l'on cote, puis il affecte (cote de nouveau) à un agent de sa
> structure. »

Deux gestes, donc, et deux tables : la **cotation** désigne une *structure*
(`cotation_structure`), l'**affectation** désigne une *personne*
(`affectation`). Le pilier portait bien les deux, et la visibilité les honorait :
un courrier coté à la DSR était visible du directeur de la DSR.

Il n'était visible nulle part **en tant que travail à faire**. Le registre
comptait six onglets, dont « Qui m'est affecté » — ce qui m'est affecté à moi,
personne. Rien ne disait « ce que ma structure vient de recevoir et que je dois
distribuer ». L'écran `/affectations`, intitulé « Courriers à affecter », ouvrait
sur la vue `tous` : il promettait la file dans son titre et montrait le registre
entier. Le directeur qui venait d'être coté relisait cinquante lignes pour
retrouver la sienne, et concluait — c'est ce qui est arrivé — que la cotation
n'était pas parvenue.

## Décision

Le registre porte un septième onglet, `aAffecter` : **coté à l'une de mes
structures, et pas encore affecté à une personne chez moi**. L'écran
`/affectations` s'ouvre dessus. L'onglet ne s'affiche qu'à qui porte `AFF`.

Les structures retenues sont celles que la portée rend visibles
(`structures_visibles`), et non la seule structure de rattachement : un
secrétariat de direction en portée `sous_arbre` doit voir arriver ce qui est coté
à sa direction — c'est précisément lui qui distribue. En portée `toutes`, où le
périmètre ne borne plus rien, on retombe sur le sous-arbre de la structure de
rattachement : « tout ce qui traîne au Port » n'est la file de personne.

Une affectation prise dans une *autre* structure cotée ne vide pas ma file : le
filtre ne regarde que les affectations prises **dans mes structures**. Un
courrier coté à la DAF et à la DSR, que la DAF a distribué, reste à distribuer à
la DSR.

## Conséquences

- Le trajet du courrier est lisible de bout en bout à l'écran : « Non cotés » →
  « À affecter » → « Qui m'est affecté ».
- L'onglet est un **filtre**, comme les six autres, et non une étape : un
  courrier peut être à la fois « À affecter » et « Hors délai ».
- L'absence d'affectation se cherche depuis `Affectation` et jamais par un
  `__isnull=True` porté par la relation — sinon tout courrier serait à affecter
  dès son enregistrement. Voir `docs/pieges.md`.
- Les courriers clôturés sont écartés : un courrier clos ne se distribue plus.
- Le compteur de l'onglet coûte une requête d'anti-jointure de plus par
  chargement du registre. L'index de `affectation.cotation_structure_id` la
  porte.

## Ce qui invaliderait cette décision

Si l'affectation cessait d'être nominative — si le Port décidait que la cotation
à une structure vaut prise en charge par son chef, sans second geste — la file
n'aurait plus d'objet et l'onglet devrait disparaître avec elle.

De même, si une structure se mettait à distribuer par lots hors de
l'application (cahier papier remonté a posteriori), la file afficherait un
retard qui n'existe pas.

## Alternatives écartées

**Un écran autonome « Distribution »**. Le registre est déjà l'écran de travail :
trois écrans qui montrent le même tableau avec trois questions différentes se
tiennent mieux qu'un quatrième à apprendre. C'est le choix fait pour la cotation.

**Borner la file à la seule structure de rattachement.** Cela aurait exclu le
secrétariat de direction, qui est justement celui qui distribue au nom du
directeur.

**Rendre `affectes` symétrique** — y verser aussi ce qui est à affecter. Les deux
listes n'appellent pas le même geste : l'une se traite, l'autre se distribue.
Les confondre aurait fait un onglet dont on ne sait pas quoi faire.

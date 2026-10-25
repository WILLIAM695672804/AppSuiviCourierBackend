# 048 — La tâche à réaliser n'a pas d'attributaire

*Statut : acceptée — 10 septembre 2026*

## Contexte

L'[ADR 047](047-l-activite-est-portee-par-des-structures.md) a fermé la
responsabilité individuelle par le haut : une activité est portée par sa
structure porteuse et, le cas échéant, par des structures associées ; l'agent
n'y subsiste qu'en point focal facultatif.

Le formulaire d'ajout d'une tâche, lui, n'avait pas bougé. Il continuait de
demander « à quel agent cette tâche est-elle attribuée », champ obligatoire,
pré-rempli avec le responsable de l'activité. L'exigence, telle qu'elle a été
posée le 10 septembre 2026 :

> Lorsqu'on veut ajouter une tâche à réaliser pour une activité, je vois que
> l'on demande toujours à quel agent est attribuée cette tâche. Il faut retirer
> ça : la tâche sera uniquement reliée à l'activité.

Ce n'est pas un détail d'écran. Une tâche pèse dans `avancement_calcule` — c'est
le déclencheur `tache_avancement` qui le calcule au prorata des poids. Un agent
nommé sur chaque ligne rouvrait par le bas ce que l'ADR 047 venait de fermer par
le haut : l'avancement d'une activité institutionnelle se serait relu comme la
somme des performances de six agents nommés, et la question « qui n'a pas fait
sa part » aurait de nouveau eu une réponse individuelle.

La colonne `tache.responsable_id` existe depuis `0001_activite.sql`, nullable
dès l'origine, sans index, lue nulle part ailleurs que dans la projection de la
fiche. Aucun écran « mes tâches », aucune relance, aucun filtre de périmètre ne
s'appuie dessus : la portée `propre` filtre sur `activite.responsable_id`, pas
sur celui de la tâche.

## Décision

Une tâche se rattache à son activité, et à rien d'autre. Le formulaire ne
demande plus d'agent, `SaisieTache` ne porte plus `responsableId`, et
`ajouter_tache` crée la tâche avec `responsable` nul. La fiche n'affiche plus
d'agent sous une tâche : elle affiche l'échéance et le poids.

**La colonne reste en base**, et la sortie `TacheSortie.responsable` avec elle.
Les tâches créées jusqu'au 10 septembre 2026 portent un agent ; un `DROP COLUMN`
effacerait la réponse à « qui s'en occupait ? » pour un gain nul — la colonne ne
coûte rien à qui ne l'écrit plus.

Le champ n'est pas refusé, il est ignoré : `SaisieTache` ne le déclare plus,
Pydantic écarte l'excédent. Un poste resté sur l'ancienne version du front
continue de créer ses tâches, sans attributaire.

Rien de ceci ne vaut pour l'**instruction verbale ni pour la décision du DG** :
le §17 exige nommément quatre attributs, dont le responsable. Une instruction
est un engagement daté pris par quelqu'un ; une tâche est une décomposition du
travail d'une structure. Les deux objets ne se confondent pas.

## Conséquences

L'avancement ne change pas d'un point : il se calcule sur `etat` et `poids`, que
l'attributaire soit nul ou non. Aucune reprise de données, aucune migration.

Ce que l'application perd : la capacité de dire, dans une activité portant douze
tâches, laquelle revient à qui. C'est assumé — cette répartition est un acte de
management interne à la structure, que la plateforme n'a jamais eu vocation à
tenir, et qu'elle tenait mal (le champ était pré-rempli, donc rarement corrigé).

Ce que l'application garde : la mémoire. Les tâches antérieures continuent de
sortir avec leur agent, lisible en base et par l'API, invisible à l'écran. Un
champ conservé et non affiché est une dette assumée, pas un oubli : le
commentaire du modèle et celui du schéma le disent, et cet ADR en porte la date.

## Ce qui invaliderait cette décision

Un écran « mes tâches », c'est-à-dire une file de travail personnelle : le jour
où un agent doit ouvrir la plateforme pour savoir ce qu'il a à faire, il faut un
attributaire, et la colonne est déjà là. Ce serait alors un objet différent de
la « tâche à réaliser » du §15, qui décompose une activité et n'organise le
travail de personne.

Une exigence de traçabilité individuelle qui viendrait de l'audit interne ou du
contrôle de gestion, demandant qui a coché quelle tâche. Elle se satisferait
d'ailleurs mieux du journal — l'événement `activite_modifiee` porte déjà
l'acteur — que d'une colonne d'affectation.

## Alternatives écartées

**Rendre le champ facultatif au lieu de le retirer.** C'est l'état antérieur à
cette décision : il était déjà nullable au moteur, et c'est le formulaire qui le
rendait obligatoire. Le laisser en saisie facultative aurait produit un plan à
deux régimes — des structures qui nomment, des structures qui ne nomment pas —
et la question « pourquoi celle-ci n'a-t-elle personne ? » se serait posée à
chaque revue.

**Attribuer la tâche à une structure plutôt qu'à un agent**, sur le modèle de
l'ADR 047. Une table `tache_structure`, ou une clé vers `structure`. Écarté :
les structures responsables sont déjà portées par l'activité, et une tâche
rattachée à une structure qui ne répond pas de l'activité serait un rattachement
sans visibilité — la tâche apparaîtrait dans une activité invisible à qui en
répond. Si le besoin se confirme, il se traitera comme une répartition interne
des structures déjà associées, pas comme un rattachement neuf.

**Supprimer la colonne.** Retenu par personne : la table `tache` n'est pas
volumineuse, la colonne est nullable, et l'invalidation logique est déjà la
règle du produit — on ne détruit pas ce qui a été vrai.

# 025 — L'organigramme réel se charge, il ne se migre pas

*Statut : acceptée — 19 août 2026*

## Contexte

La planche « Organigramme du PAD Proposé », dressée par la Direction générale le
10 novembre 2025, a été communiquée. C'est l'un des trois documents que les
décisions de cadrage classaient comme réellement bloquants : « sans lui, les
périmètres restent théoriques ». Le jeu d'essai de `semer.py` le disait
lui-même, en tête de fichier — son arbre de quatorze structures était « une
approximation de travail, conçue pour exercer les quatre portées de périmètre,
et rien d'autre ».

La planche décrit une institution de **soixante-dix-sept structures**, sur cinq
niveaux : un conseil d'administration, une direction générale, un cabinet et
ses sept unités, cinq divisions rattachées au directeur général avec leurs
cellules, trois représentations extérieures, et dix directions métier qui
descendent jusqu'au département.

Le modèle du noyau était prêt à la recevoir — `Structure` porte un arbre
historisé, `Poste` porte la hiérarchie, `AffectationPoste` porte l'histoire des
agents. Restait à décider **par quel geste** ces données entrent en base.

Trois candidats se présentaient, et le choix n'est pas indifférent : une donnée
de référence qui entre par le mauvais chemin devient impossible à corriger.

## Décision

**L'organigramme réel entre par une commande d'exploitation,
`charger_organigramme`, alimentée par une transcription versionnée. Il n'entre
ni par une migration, ni par le semis de démonstration.**

1. **La transcription est un fichier source**,
   `noyau/organisation/donnees/organigramme_pad.py`. Elle ne contient aucune
   règle : une ligne par boîte de la planche, et des commentaires `# LECTURE`
   partout où le tracé laissait un doute. Elle est relisible à côté du PDF, ce
   qu'un `INSERT` de soixante-dix-sept lignes n'aurait pas été.

2. **La migration ne crée aucune structure.** La migration `0017` ne fait que
   rendre le socle capable d'en accueillir : elle élargit les natures admises de
   cinq à douze, et sème les deux rangs manquants — directeur adjoint et
   sous-directeur — sans lesquels les deux tiers de la planche n'avaient pas
   d'étage où se poser.

3. **La commande crée, et ne modifie jamais.** Quand une structure en vigueur
   diverge de la transcription, elle le signale et passe. Corriger une structure
   veut dire clore la ligne en vigueur, en inscrire une nouvelle, reprendre ses
   postes et ses affectations — c'est le principe 1 de
   `organisation/modeles.py`, et c'est un geste que l'écran d'administration sait
   faire sous le nom de quelqu'un.

4. **Elle ne nomme personne.** Tous les postes ouverts sont vacants. Affecter un
   agent reste le monopole de `services.affecter()`, seul point du dépôt
   autorisé à écrire `utilisateur.poste` ([ADR 015](015-l-affectation-a-un-poste-est-datee.md)).

5. **La nature et le rang sont deux colonnes.** La planche les superpose : le nom
   de la boîte dit ce qu'est la structure, sa couleur dit le rang de son
   responsable. Le Cabinet du Directeur général est une boîte blanche — rang de
   chef de service — et un Département est saumon — rang de sous-directeur. Les
   confondre reclasserait la moitié de l'institution.

## Conséquences

- La bascule du jeu d'essai vers le référentiel réel est un geste explicite,
  `--cloturer-absentes`, qui **refuse de clore une structure dont un poste est
  pourvu**. Un agent rattaché à une structure close verrait son périmètre ne
  plus rien rendre, sans aucune erreur — exactement la panne silencieuse que le
  socle passe son temps à éviter.
- La portée `sous_arbre` passe de deux à cinq niveaux de profondeur. La récursion
  est en SQL depuis l'origine et n'en souffre pas, mais les jeux de test qui
  vérifiaient un périmètre sur un arbre plat ne vérifient plus la même chose.
- **Le point d'entrée du courrier se déplace.** Le Service du courrier central
  relève du Cabinet du Directeur général, et non de la Direction générale
  directement. Tout ce qui remonte « au niveau supérieur » depuis le bureau
  d'ordre remonte désormais au Cabinet.
- Les sigles sont inventés, faute d'en trouver un seul sur la planche
  ([A59](../../../docs/questions-ouvertes.md)). Ils se corrigeront en rejouant la
  commande, tant qu'aucune donnée réelle n'y renvoie.
- `semer.py` reste, inchangé, avec son organigramme fictif. Les deux ne doivent
  jamais peupler la même base ; la commande de chargement le rappelle et sait
  faire le ménage.

## Ce qui invaliderait cette décision

Une réorganisation du Port assez fréquente pour que le chargement redevienne un
geste courant. Le signal serait mesurable : plusieurs passages de
`charger_organigramme` par an, avec à chaque fois une liste de divergences que
personne ne reprend à l'écran. Il faudrait alors donner à la commande le droit
de clore et de réinscrire — c'est-à-dire lui confier l'historisation, ce que
cette décision lui refuse.

Un second cas : si le Port se dote d'un annuaire faisant autorité, exportant
structures **et** agents. Le chargement deviendrait une synchronisation
périodique, avec ses conflits et son sens de circulation à trancher — un autre
problème, qui mériterait sa propre décision.

## Alternatives écartées

**Une migration de données.** C'est la voie qui demande le moins de travail : un
`RunPython`, et l'organigramme est là partout, sans que personne ait à lancer
quoi que ce soit. Elle a été écartée pour trois raisons. Une migration
s'applique **partout**, y compris sur les bases de test qui n'ont rien demandé.
Elle ne se rejoue pas : le jour où un sigle change, il faut une seconde
migration qui défait la première, et une base restaurée d'une sauvegarde
ancienne rejouerait les deux dans l'ordre. Et surtout, une migration est un
objet **figé** — le dépôt en fait une règle absolue pour les décisions
d'architecture — alors que l'organigramme d'une institution est ce qu'il y a de
plus vivant.

**Étendre `semer.py`.** Un seul chemin d'entrée pour l'organigramme, réel ou
fictif. Refusé parce que les deux commandes n'ont pas le même contrat :
`semer` crée des comptes dont le mot de passe est public et refuse de tourner
hors développement ; le chargement du référentiel a vocation à tourner en
production. Les réunir aurait produit une commande dont la moitié des options
est interdite selon le contexte, c'est-à-dire une commande qu'on finit par
lancer avec `--force`.

**Un import de fichier depuis l'écran d'administration.** La forme la plus
souple, et celle qui n'a pas de destinataire : l'organigramme se charge une
fois, à l'installation. Construire un écran d'import, son format de fichier, sa
prévisualisation et ses messages d'erreur pour un geste unique aurait coûté
davantage que la donnée elle-même.

**Déduire le rang de la nature.** « Une Division est dirigée par un directeur
adjoint » aurait évité une colonne. C'est faux sur la planche même : les cinq
divisions rattachées au Directeur général sont bleues — rang de directeur — et
les divisions internes aux directions métier sont vertes. La même nature, deux
rangs, et aucune règle pour les départager autre que le rattachement.

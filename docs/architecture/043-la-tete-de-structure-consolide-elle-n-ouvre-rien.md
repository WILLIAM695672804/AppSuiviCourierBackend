# 043 — La tête de structure consolide l'affichage, elle n'ouvre aucun accès

*Statut : acceptée — 31 août 2026*

## Contexte

Le 31 août 2026, l'utilisateur a demandé quatre changements qui, énoncés
séparément, décrivaient tous la même chose :

> « les activités d'un département (sous-structure) font partie de celui de la
> structure, donc seul le directeur de cette structure peut voir les détails
> des sous-structures, et la DSR et autres supérieurs peuvent voir la vue
> d'ensemble de la structure — plus de distinction entre les structures et les
> sous-structures d'un point de vue DSR et DG. »

L'application faisait l'inverse. Le classement de la matrice de performance
rendait **quarante-six lignes** au Directeur général : chaque cellule, chaque
secteur, chaque service comparé aux autres. Le tableau était juste et
inutilisable — un directeur général ne demande pas si la cellule courrier de la
DSI fait mieux que le secteur pilotage de la DAF ; il demande comment se tient
la DSI. La distinction que l'écran ne faisait pas, c'est celle entre
l'**étage où l'on mesure** et l'**étage où l'on compare**.

Trois autres symptômes venaient du même manque. La relance automatique
s'adressait au responsable de l'activité — l'agent lui-même — au lieu du chef
de structure ; le portefeuille de relance du courrier n'affichait aucun
interlocuteur ; le planning des congés s'arrêtait aux directeurs alors qu'un
chef de structure planifie pour ses agents.

Le socle n'avait pas de mot pour dire « l'étage direction ». `Structure.parent`
donne le père, la portée `sous_arbre` donne les descendants, mais rien ne
nommait le point où un département cesse d'être lui-même pour se compter dans
sa direction. Chaque écran l'aurait donc réinventé, et différemment.

Un piège s'est présenté à la définition : la Direction générale **n'est pas la
racine** de l'organigramme. La planche inscrit le Conseil d'administration
au-dessus d'elle. Définir la tête comme « enfant direct de la racine » désignait
la Direction générale et faisait remonter le Port entier sous une tête unique —
c'est ce que la première version a fait, sur les soixante-dix-sept structures.

## Décision

**Toute structure porte une tête, matérialisée en base ; la tête gouverne le
regroupement des lignes, et rien d'autre.**

1. **`structure.tete_id` est une colonne dérivée**, posée par le déclencheur
   `structure_tete_apres_ecriture` (migration 0024) et jamais écrite depuis
   l'ORM. La tête d'une structure est son ancêtre situé juste sous le plus haut
   ancêtre non-`Organe` : dix directions, cinq divisions, le Cabinet et trois
   représentations — dix-neuf en tout. Une tête est sa propre tête.

2. **`noyau/organisation/tete.py` est le seul endroit qui répond aux quatre
   questions** : à quel étage une structure se compte (`tete_de`), qui la dirige
   (`responsable_de`), à qui la relance s'adresse (`responsable_a_relancer`),
   et si un agent lit le Port par têtes (`consolide`). Les tableaux passent par
   `regrouper()` ou `champ_regroupement()`, jamais par un `values("structure")`
   recopié.

3. **La consolidation n'ouvre aucun accès.** Elle décide de la façon dont les
   lignes sont *groupées et nommées* ; le périmètre décide de ce qui est *lu*.
   Un `restreindre()` reste obligatoire sur toute route qui rend des données,
   et la décision D5 — hors périmètre, 404 — est inchangée. Deux agents à
   consolidation identique et périmètre différent voient deux tableaux
   différents.

4. **Le score d'une tête se recalcule sur son sous-arbre**, il ne moyenne pas
   les scores de ses départements. Une moyenne de moyennes donne autant de poids
   à une cellule de trois agents qu'à un département de quarante.

5. **La relance s'adresse au responsable de la tête**, en remontant l'arbre si
   le poste est vacant. Faute de destinataire jusqu'à la racine, la relance
   n'est **pas émise** et un événement `relance_sans_destinataire` est inscrit :
   une relance envoyée dans le vide fait croire que l'escalade a eu lieu.
   L'émetteur, lui, ne change pas — la relance reste un geste de la DSR, et le
   profil `RESP` ne gagne pas `REL`.

## Conséquences

- Le Directeur général et la DSR lisent dix-neuf lignes là où ils en lisaient
  quarante-six. Le détail par sous-structure reste accessible au directeur de
  la tête, et à lui seul.
- `matrice.py` travaille désormais sur une **liste** d'identifiants de
  structures (`structure_id = ANY(%s)`) et non sur un identifiant unique. Tout
  critère ajouté doit suivre la même signature, sans quoi il mesurera la tête
  seule et laissera ses départements hors du score.
- Toute lecture qui itère des structures doit poser
  `select_related("…__structure__tete")`. `tete_de()` rend `structure.tete` et
  non une requête à la main, précisément pour que cet indice serve ; l'oublier
  ne casse rien et coûte une requête par ligne.
- `poste.est_responsable` et son index unique partiel imposent **un seul poste
  responsable en cours par structure**. Un organigramme réel qui en présenterait
  deux échouera à l'import plutôt que d'en désigner un au hasard.
- Deux règles sont posées en `hypothese` faute de source écrite : le
  rattachement du Cabinet et des représentations à l'étage des directions (A80)
  et la remontée de la relance en cas de poste vacant (A81). Elles sont
  inscrites dans `docs/questions-ouvertes.md`.

## Ce qui invaliderait cette décision

- **Un deuxième niveau de consolidation.** Si le Port se dote de pôles
  regroupant plusieurs directions, une tête unique par structure ne suffit plus
  et il faudra un étage paramétrable plutôt qu'une colonne dérivée.
- **Une direction sans directeur durablement.** La remontée à la racine reste
  supportable tant qu'elle est exceptionnelle. Si elle devient l'ordinaire, la
  relance atterrira toujours au même bureau et cessera d'être une escalade.
- **Un organigramme à profondeur variable sous la Direction générale.** La
  définition suppose que l'étage « direction » est *un* niveau. Une direction
  rattachée à une autre direction rendrait la tête ambiguë.

## Alternatives écartées

**Calculer la tête à la lecture, par une remontée récursive.** Correct, mais
une requête récursive par ligne de tableau. Le classement de la matrice en
aurait fait quarante-six. La colonne dérivée coûte un déclencheur et rend la
tête jointe.

**Déduire la tête de la portée du périmètre.** C'était mélanger l'accès et
l'affichage : ce qu'un agent a le droit de voir aurait dépendu de la façon dont
on le lui montre. La règle 1 de `perimetre/portee.py` l'interdit, et pour cause
— un changement d'écran serait devenu un changement de droits.

**Élargir le périmètre de la DSR et du DG à `toutes` et filtrer à l'affichage.**
Ils l'ont déjà ; ce n'était pas le problème. Le problème était la granularité
des lignes, pas leur nombre.

**Moyenner les scores des départements pour obtenir celui de la direction.**
Écarté par arbitrage explicite de l'utilisateur le 31 août 2026 : une moyenne
de moyennes donne à une cellule de trois agents le poids d'un département de
quarante, et le classement récompenserait le fait d'avoir beaucoup de petites
structures.

# ADR 013 — Le portail restreint par déposant, pas par périmètre

*14 août 2026 — acceptée*

## Contexte

Le pilier « portail usagers » (§3.13) ouvre trois capacités à des comptes qui
n'appartiennent pas à l'institution : déposer une demande et la suivre, régler
ses notifications, échanger dans le cadre d'un marché ou d'une convention.

Le dépôt a une règle générale, écrite dans `CLAUDE.md` : *une route déclare
`auth=exige(PERM.…)` et appelle `restreindre()` dès qu'elle renvoie des
données*. Elle a été posée pour les agents, et `restreindre()` la met en œuvre à
partir de deux colonnes : la structure de l'objet, et l'agent qui en répond. Le
périmètre du compte — `propre`, `structure`, `sous_arbre`, `toutes` — décide
ensuite de ce qu'il voit.

Un usager du portail n'a ni structure, ni poste, ni périmètre. La question
n'était donc pas de savoir *comment* appliquer `restreindre()` ici, mais si le
faire aurait un sens.

## Décision

**Le portail ne passe pas par `restreindre()`.** Sa restriction est
`deposant = utilisateur` pour les demandes et `partenaire = utilisateur` pour
les échanges, écrite dans `portail/lecture.py` — dans `demandes_de()`, par où
passe *toute* lecture du pilier, et dans `echanges()`.

**Les comptes du portail ne portent aucun périmètre.** Le semis n'en pose pas,
et c'est délibéré : un usager n'a rien à voir dans l'organigramme du port.

**Une demande qui n'est pas la sienne répond 404**, jamais 403 — la décision D5
du cadrage, appliquée ici avec une raison de plus.

## Pourquoi

### `restreindre()` aurait été plus permissif, pas plus sûr

Un compte sans périmètre ne voit rien (règle 3 de `noyau/perimetre/portee.py`) :
le portail aurait été vide. La correction évidente aurait été de poser un
périmètre sur chaque usager — et là est le danger. Un périmètre `structure`
posé par mégarde sur un compte externe, ou un rattachement à une direction fait
pour « que ça marche », aurait ouvert à cet usager **les demandes de tous les
autres** dont la structure instructrice est la même. La restriction serait
devenue une propriété du compte, modifiable par l'administration des
habilitations, au lieu d'une propriété de la donnée.

`deposant = utilisateur` n'est pas administrable. Il n'y a pas de réglage qui
l'élargisse.

### Le 404 n'est pas une politesse

Sur les écrans internes, le 404 de `HorsPerimetre` évite de dire à un agent
qu'un dossier existe hors de son périmètre. Sur un portail ouvert au public,
l'enjeu change d'échelle : un 403 sur `/portail/demandes/4213` confirmerait
l'existence de la demande 4213, et il suffirait d'énumérer les identifiants pour
dresser la volumétrie de l'institution — voire, en croisant avec les dates de
réponse, sa charge et ses retards.

### Le vocabulaire est une contrainte technique, pas un choix éditorial

Aucune table ni aucun libellé du pilier ne porte « cotation », « structure
pilote » ni « étape ». Ce n'est pas de la courtoisie : les mots de l'institution
décrivent son organisation interne, et les exposer à l'extérieur revient à
publier son organigramme fonctionnel. La frise du suivi porte quatre étapes là
où l'instruction en compte cinq, pour la même raison — la distinction entre
qualification et instruction ne regarde pas le demandeur.

## Conséquences

- **Toute lecture du pilier doit partir de `demandes_de()`.** Une requête qui
  attaquerait `DemandeUsager.objects` directement contournerait la seule
  restriction qui existe, et ne produirait aucune erreur — juste une fuite. Le
  test `test_un_usager_ne_voit_que_ses_propres_demandes` l'attrape ; rien
  d'autre.
- **Le pilier est exclu de la règle générale de `CLAUDE.md`.** Il faut le
  savoir en le lisant, d'où cet ADR et la docstring en tête de `portail/api.py`.
- **Un usager ne peut pas être rendu « lecteur d'une structure ».** Si le métier
  demande un jour qu'un partenaire voie les demandes de sa filiale, cela ne se
  fera pas par un périmètre : il faudra une notion de mandat entre comptes
  externes, qui reste à concevoir.
- Le compte externe du semis n'a pas de structure : tout code qui suppose
  `utilisateur.structure_id` non nul casse sur lui. C'est un bon filet.

## Ce qui invaliderait cette décision

- **Un guichet unique interne.** Si un agent d'accueil devait déposer une
  demande *pour* un usager — au comptoir, par téléphone — le déposant ne serait
  plus le titulaire. Il faudrait alors distinguer « déposé par » et « pour le
  compte de », comme le journal du noyau le fait déjà pour `acteur_id` et
  `agit_pour_id`.
- **Une représentation légale.** Un cabinet qui suit les demandes de plusieurs
  entreprises, un groupe qui consolide celles de ses filiales : la restriction
  cesse d'être « moi » et devient « ceux que je représente ». C'est un mandat,
  pas un périmètre, et il devra être daté et révocable.
- **Une obligation de publicité.** Si un texte impose de publier certaines
  demandes — enquête publique, marché en cours d'attribution — le 404 devient
  faux pour cette catégorie. Il faudra alors une exception explicite, portée par
  la donnée et non par le compte qui lit.

## Alternatives écartées

**Poser un périmètre `propre` sur chaque usager.** Écartée : `propre` restreint
par *agent*, c'est-à-dire par la colonne qui désigne l'instructeur d'un dossier.
Un usager n'instruit rien. Le faire passer par là aurait fonctionné par accident,
et aurait cassé le jour où la colonne d'agent change de sens.

**Ajouter une portée `deposant` au socle.** Écartée : elle n'aurait servi qu'à
un pilier, tout en ajoutant un cas à `restreindre()` — la fonction la plus
sensible du dépôt, dont chaque branche supplémentaire est un risque pour tous
les autres piliers.

**Un second `NinjaAPI` monté sur un autre chemin.** Écartée pour ce premier
état : elle isolerait mieux (cookie de session distinct, CSRF séparé, pas de
route interne accessible par erreur) mais dupliquerait l'authentification et les
gardes. À reconsidérer si le portail est un jour exposé sur un domaine public
séparé — c'est le moment où l'isolement au niveau du réseau prendra le pas sur
celui du code.

## Voir aussi

- [ADR 009](009-garde-large-contenu-filtre.md) — garde large, contenu filtré.
  Le portail est l'inverse : garde étroite (`EXT` seule), contenu déjà réduit à
  un seul titulaire.
- [ADR 010](010-la-matrice-se-recalcule.md) — rien de calculable n'est stocké.
  L'état d'une demande et celui d'un échange en sont deux applications.
- [ADR 011](011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) — une mesure
  absente sort à `null`.
- [ADR 014](014-la-supervision-mesure-ce-que-le-serveur-traverse.md) — livrée le
  même jour, sur la même exigence de ne rien inventer.

# 022 — Le registre est une porte de visibilité

*Statut : acceptée — 17 août 2026*

## Contexte

La règle de visibilité a été énoncée par le client le 11 août 2026, mot pour
mot :

> On voit ce à quoi on est rattaché — sa structure, plus ce sur quoi on a été
> coté ou désigné. Tout le reste est invisible, sauf permission explicite de
> consolidation.

Trois portes, donc : rattachement, cotation ou désignation, consolidation.
`noyau.perimetre.portee.restreindre()` en tient une seule — le rattachement par
la structure — et la docstring de `noyau/perimetre/designation.py` annonçait
depuis le 12 août que les deux autres relèveraient du pilier courrier.

Au moment d'écrire ces deux portes, un trou est apparu, et il est structurel :
**un courrier qui vient d'être enregistré n'est coté à personne.**
`structure_chef_file_id` est nul, `cotation` est vide, aucune affectation
n'existe. Aucune des trois portes ne s'ouvre.

Conséquences, si l'on s'en tient à la lettre des trois portes :

- l'agent de session qui enregistre un courrier reçoit un **404** sur la fiche
  vers laquelle l'écran le redirige — la seule action possible après
  l'enregistrement ;
- l'onglet « Non cotés » du registre est **vide par construction**, alors que
  c'est l'onglet de travail du service courrier : ce sont exactement les
  courriers qu'il faut faire coter ;
- les quatre indicateurs du registre — arrivés aujourd'hui, en attente de
  cotation, délai moyen de cotation, hors délai — portent tous sur des courriers
  non encore cotés. Ils vaudraient zéro en permanence.

Le trou ne vient pas de la règle du client : il vient de ce que la règle décrit
**la circulation d'un courrier coté**, et qu'elle ne dit rien du registre
lui-même. Or le registre existe, il est décrit au §4.2, et il porte déjà une
mécanique d'habilitation complète — `session`, `utilisateur_session`,
`lit_toutes_sessions`, et une contrainte d'exclusion du moteur qui garantit
qu'un agent n'est rattaché qu'à une session à la fois.

`docs/accueil/02-le-domaine.md` le dit d'ailleurs sans en tirer la conséquence :

> **cloisonner les corbeilles** — un agent n'est rattaché qu'à **une seule**
> session à la fois […]. Un agent du registre « Arrivée » ne voit pas la
> corbeille « Confidentiel ».

« Ne voit pas celle-là » suppose qu'il voit la sienne.

## Décision

**Le rattachement à une session d'enregistrement est une quatrième porte de
visibilité, indépendante du périmètre de structure.**

1. **La porte ouvre le registre entier de la session**, sans considération de
   périmètre : un agent rattaché au registre « Arrivée » voit les courriers
   arrivés, y compris ceux cotés à des directions hors de son périmètre. C'est
   ce qu'est un registre — le service courrier tient le cahier.
2. **Elle ne s'étend pas aux autres sessions**, sauf `lit_toutes_sessions`, que
   seule la session confidentielle porte au socle. La propriété reste en donnée
   et non en code : le §4.2 la donne « selon les habilitations définies », et
   elle doit pouvoir être retirée sans livraison.
3. **Elle est étroite en pratique.** La session n'est pas un axe d'habilitation
   général : seuls les agents du service courrier en ont une. Un directeur n'est
   rattaché à aucune session et voit ses courriers par la porte de la cotation.
4. **La confidentialité n'est pas une porte : c'est une serrure.** Un courrier
   `confidentiel` exige la permission `CONF` — « Accéder aux courriers
   confidentiels », c'est le libellé de la permission au socle. La serrure est
   posée **avant** les quatre portes, et aucune ne l'ouvre : la portée `toutes`
   consolide sans lever le secret. Décision de cadrage D5, filtrage au niveau
   des données.
5. **Un seul point d'application** : `courrier.visibilite.visibles()`. Aucune
   lecture du pilier ne pose son filtre elle-même, pour la même raison que
   `restreindre()` existe — un filtre recopié à la main est un filtre qui sera
   oublié au prochain endpoint.

## Conséquences

- L'agent de session voit ce qu'il enregistre, et l'onglet « Non cotés » a du
  contenu. Le registre fonctionne comme un registre.
- Un agent du service courrier voit passer des objets de courriers qui
  concernent des directions dont il n'est pas. **C'est déjà le cas sur papier**,
  et c'est la contrepartie assumée du registre central : la confidentialité
  d'un courrier sensible se traite par la session `confidentiel` et la
  permission `CONF`, pas en aveuglant le service courrier.
- La visibilité du courrier ne se déduit plus de `restreindre()` seul. Toute
  route du pilier appelle `visibles()`, qui l'englobe ; les autres piliers
  continuent d'appeler `restreindre()` directement.
- `distinct()` devient obligatoire sur les lectures : les portes traversent
  `cotation_structure` et `affectation`, et un courrier coté à trois structures
  visibles sortirait trois fois — donc compterait trois fois dans le total du
  registre.

## Ce qui invaliderait cette décision

Une note du Port disant qu'un agent du service courrier ne doit **pas** voir
l'objet des courriers qu'il enregistre pour d'autres directions. La réponse ne
serait alors pas de refermer la porte — le registre deviendrait inutilisable —
mais de multiplier les sessions : une par direction, chacune avec son compteur
et sa corbeille. Le schéma le permet sans modification ; l'exploitation, elle,
changerait de nature.

Second cas : si `CONF` finissait par être portée par la moitié des comptes, la
serrure ne fermerait plus rien. Le signal est mesurable — un décompte des
comptes portant `CONF` dans le rapport d'habilitation.

## Alternatives écartées

**Faire de `cree_par` la porte manquante.** L'agent verrait ce qu'il a
enregistré lui-même. Une ligne de code, et l'onglet « Non cotés » ne montrerait
à chacun que ses propres saisies : un agent absent, et ses courriers
disparaissent du registre jusqu'à leur cotation. Le registre est un cahier
partagé, pas une liste personnelle.

**Traiter le courrier non coté comme visible de tous.** Le trou se refermait
sans nouvelle porte, mais la période avant cotation — celle où l'objet est en
clair et où rien n'est encore décidé — devenait la plus ouverte du cycle de vie.
L'inverse de ce que demande D5.

**Rendre `structure_chef_file_id` non nul, égal à la structure de l'agent qui
enregistre, jusqu'à la cotation.** La porte du rattachement suffisait alors.
Mais la colonne signifie « qui coordonne la réponse », et la remplir avant toute
décision aurait fait apparaître le service courrier comme chef de file de chaque
courrier arrivé — dans le registre, dans les statistiques par structure, et dans
le délai moyen de réponse de la DSR.

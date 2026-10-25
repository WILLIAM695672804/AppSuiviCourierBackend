# 047 — L'activité est portée par des structures, pas par un agent

*Statut : acceptée — 9 septembre 2026*

## Contexte

L'exigence, telle qu'elle a été posée :

> On n'affecte pas un agent à une activité, c'est la structure qui est affectée
> à une activité. Par défaut c'est la structure qui enregistre qui est affectée,
> mais il peut y avoir plusieurs structures : on doit pouvoir, en plus de la
> structure par défaut, ajouter une autre structure responsable de l'activité.

Le modèle livré tenait la moitié de cette phrase sans la dire ainsi.

**Ce qui tenait.** La structure porteuse n'a jamais été une colonne
d'`activite` : elle vient du plan d'actions annuel (`paa.structure_id`), et
c'est déjà d'elle que dépendent la visibilité, le taux du plan et les agrégats.
La relance du §16 vise déjà le directeur de cette structure, jamais l'agent
nommé sur l'activité.

**Ce qui ne tenait pas.**

1. `activite.responsable_id` était `NOT NULL` : toute activité exigeait un agent
   nommé, et cet agent passait pour celui qui « répond » de l'activité — ce que
   l'écran affichait sous l'intitulé « Responsable ».
2. Une activité ne pouvait relever que d'une seule structure. Une action
   transverse — la dématérialisation, qui engage la DSI, la DSR et le contrôle
   de gestion — n'avait aucun moyen de le dire, sinon en l'écrivant en toutes
   lettres dans l'objectif, où rien ne peut la lire.
3. La conséquence était une **fermeture** : la direction associée à une activité
   ne la voyait pas dans son registre, ne pouvait ni y poser une tâche, ni y
   déclarer un avancement, ni y verser une pièce.

## Décision

**La responsabilité d'une activité est institutionnelle.** Elle se lit sur des
structures ; le nom d'un agent devient un point focal facultatif.

| élément | ce qu'il dit |
|---|---|
| `paa.structure_id` | la structure **porteuse** — celle dont le plan tient l'activité. Inchangée, et jamais dupliquée sur `activite` |
| `activite_structure` | les structures **associées**, en sus de la porteuse. Retrait logique (`invalide_le`), unicité partielle sur les lignes en vigueur |
| `activite.responsable_id` | le **point focal** : la personne qu'on appelle. Devenu nullable |

Trois règles complètent le schéma :

**La porteuse ne se choisit pas.** Elle est celle du plan de l'agent qui
enregistre. La proposer au choix laisserait croire qu'on inscrit une activité au
plan d'une autre direction ; le serveur refuse d'ailleurs de la voir figurer
parmi les associées — deux vérités sur le rattachement en feraient une fausse.

**Une structure associée voit et déclare.** `restreindre()` accepte désormais
plusieurs chemins de structure, combinés par OU : `plan__structure` ou
`structures_associees__structure`. Puisque toute écriture métier passe par
`_visibles()` — c'est ce que `_activite_ecrivable()` garantit —, la même ligne
ouvre la lecture et l'écriture. Une co-responsabilité invisible au registre de
la co-responsable n'aurait été qu'une mention décorative.

**Le périmètre de l'agent ne borne pas le choix des associées.** Une activité
transverse associe précisément une direction que le point focal ne lit pas.
Même raison qu'à l'[ADR 020](020-le-responsable-se-designe-par-identifiant.md)
pour l'annuaire des agents : désigner n'est pas lire. Associer une structure lui
**ouvre** la visibilité ; c'est le geste demandé, pas un effet de bord à
prévenir.

**Et la période se saisit au mois.** Décision prise dans le même mouvement,
parce qu'elle porte sur le même formulaire : un plan d'actions annuel s'écrit
« de mars à décembre ». Le quantième était inventé à chaque saisie, et deux
activités identiques se retrouvaient décalées de quinze jours sans que cela
veuille rien dire. Les colonnes restent des `DATE` — le retard, l'avancement
attendu et les agrégats se calculent au jour — et le serveur pose la borne :
premier jour du mois au début, dernier à la fin.

## Conséquences

- **L'inscription au plan ne change pas.** Une activité reste inscrite au seul
  plan de sa porteuse. Les agrégats (`agregat_activite_jour`), le taux du plan
  et les tableaux de bord continuent de compter par `paa.structure_id` : pas de
  double comptage, et une activité transverse ne gonfle pas deux directions.
- **La relance ne change pas non plus.** Elle vise le directeur de la porteuse.
  Escalader chez trois directions à la fois n'escalade nulle part.
- La notification de recalibrage (ADR 030) visait `activite.responsable`, qui
  peut désormais être `NULL` : elle vise le point focal quand il existe, et sinon
  le responsable de la structure porteuse. Poste de tête vacant, personne n'est
  notifié — l'événement au journal reste la trace.
- En portée `propre`, un agent ne voit que les activités dont il est le point
  focal. Une activité sans point focal lui est donc invisible. C'est cohérent :
  cette portée existe pour les instructeurs, pas pour les porteurs d'activité.
- Le filtre par structure du registre suit la même définition que la
  visibilité — porteuse **ou** associée —, sans quoi choisir sa propre structure
  aurait masqué les activités dont on est co-responsable.
- `restreindre()` gagne une forme d'appel : un chemin qui traverse une table de
  rattachement se donne avec ses conditions, `(chemin, {filtres})`, pour qu'elles
  portent sur la **même jointure**. Les poser dans un `filter()` séparé viserait
  une autre ligne de la table de rattachement et exclurait des activités
  parfaitement visibles — l'erreur a été commise puis corrigée en écrivant ceci.
- La session (`GET /moi`) rend désormais `structureSigle` : la modale doit
  écarter la porteuse de son sélecteur, et ne la connaissait que par son libellé.
- Les activités déjà saisies gardent leur point focal et leur quantième. Aucune
  reprise de données : la colonne s'ouvre, le format d'entrée s'élargit.

## Ce qui invaliderait cette décision

**Un arbitrage qui donnerait un rang aux structures.** Le courrier a un chef de
file ; l'activité n'en a pas ici — la porteuse tient le plan, les associées sont
à égalité entre elles. Si le suivi demande demain « laquelle rend compte », c'est
une colonne de rang sur `activite_structure`, et la question du destinataire de
la relance se rouvre.

**Une activité inscrite à plusieurs plans.** Ce serait un autre modèle : le
double comptage devient à traiter partout — agrégats, taux, classements — et
`paa.structure_id` cesse d'être la vérité unique du rattachement.

**Une exigence de quantième.** Si une activité doit un jour démarrer le 15, le
mois ne suffit plus et la saisie repasse à la date pleine — sans que le stockage
change, puisqu'il n'a jamais cessé d'être une date.

## Alternatives écartées

**Garder l'agent responsable obligatoire et n'ajouter que les structures.** La
demande dit l'inverse : « on n'affecte pas un agent ». Laisser le champ
obligatoire aurait maintenu à l'écran un « Responsable » que le modèle ne
reconnaît plus comme tel.

**Supprimer complètement le point focal.** Écarté à l'arbitrage : quelqu'un
décroche le téléphone, et l'annuaire de l'activité a une valeur propre. Il
devient facultatif, il ne fonde plus rien.

**Écrire la porteuse dans `activite_structure` comme les autres.** Elle serait
alors dite deux fois — par le plan et par la table —, et rien ne garantirait
qu'elles disent la même chose. C'est le défaut que l'en-tête du modèle
`Activite` proscrit depuis le premier jour.

**Un rattachement purement déclaratif, sans effet sur la visibilité.** Une
mention sur la fiche que personne ne peut lire depuis la direction concernée :
elle aurait donné l'apparence de la co-responsabilité sans rien en changer.

**Supprimer les rattachements retirés.** Un `DELETE` efface la question de
savoir qui répondait de l'activité au trimestre précédent. L'invalidation
logique la garde lisible, au prix d'une unicité partielle.

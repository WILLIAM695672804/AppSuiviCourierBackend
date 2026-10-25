# Module « habilitation »

**État : fait et testé.** Authentification par session, résolution des droits,
délégations, et l'administration en lecture **et en écriture**.

## Il n'y a pas de rôle

Le mot n'existe nulle part dans le code, volontairement. Ce qu'un autre logiciel
appellerait un rôle est ici la combinaison de deux axes indépendants :

> **Les permissions disent QUOI. Le périmètre dit SUR QUELLES DONNÉES.**

`ACT_SAI` autorise à saisir une activité — pas à dire lesquelles. Un point focal
saisit celles de sa structure, la DSR voit tout l'établissement. Même permission,
deux ensembles de lignes.

S'y ajoute la **délégation**, qui accorde temporairement des permissions
nommément énumérées. Voir
[ADR 002](../architecture/002-permissions-hors-django-auth.md).

## Les fichiers

| Fichier | Rôle |
|---|---|
| `modeles.py` | `Permission`, `Profil`, `Delegation` et leurs tables de liaison |
| `resolution.py` | `permissions_de()` — profils **plus** délégations en cours |
| `dependances.py` | `exige(PERM.X)`, la garde des routes, et la classe `PERM` |
| `services.py` | les règles : ce module décide |
| `schemas.py` | entrées / sorties, en camelCase |
| `api.py` | les routes, montées sur `/api/habilitations` |
| `../perimetre/portee.py` | le second axe — `restreindre()` |

## Les routes

| Route | Garde |
|---|---|
| `POST /api/connexion` | **aucune** — on ne peut pas exiger une session pour en ouvrir une |
| `POST /api/deconnexion`, `GET /api/moi` | session |
| `GET /habilitations/utilisateurs`, `/profils`, `/perimetres`, `/sessions` | `ADM_HAB` |
| `GET /habilitations/utilisateurs/{id}` (la fiche) | `ADM_HAB` |
| `POST /habilitations/utilisateurs` (création) | `ADM_HAB` |
| `PATCH /habilitations/utilisateurs/{id}`, `/{id}/etat` | `ADM_HAB` |
| `PATCH /habilitations/profils/{id}/permissions` | `ADM_HAB` |
| `POST`/`DELETE /habilitations/utilisateurs/{id}/profils[/{profil}]` | `ADM_HAB` |
| `PATCH /habilitations/utilisateurs/{id}/perimetre` | `ADM_HAB` |
| `POST`/`DELETE /habilitations/sessions/{id}/agents[/{agent}]` | `ADM_HAB` |
| `GET /habilitations/delegations` (le registre complet) | `ADM_HAB` |
| `GET /habilitations/delegations/miennes`, `/possible` | session |
| `POST /habilitations/delegations`, `DELETE .../{id}` | session |

Les routes de session sont montées **à la racine** de l'API, pas sous `/auth` :
le front appelle `/api/moi`. Le préfixe eût été plus joli ; il aurait aussi
fallu le corriger le jour du branchement.

**Pourquoi les délégations n'exigent pas `ADM_HAB`.** Le descriptif fonctionnel
§3.4 veut qu'un responsable pose et retire les siennes « sans avoir à demander à
quiconque ». Ce qui borne le geste n'est pas une permission d'administration,
c'est la règle ci-dessous.

## Les quatre règles

**On ne délègue que ce que l'on possède.** Sans ce contrôle, la délégation
devient une escalade de privilèges : il suffirait de se déléguer ce qu'on n'a
pas. Vérifié dans `declarer_delegation()`.

**Une délégation n'accorde que ce qu'elle énumère.** Jamais les droits du
titulaire en bloc. Le bénéficiaire d'une délégation de signature ne récupère pas
le droit de coter.

**Un profil `systeme` ne se modifie pas.** Les quinze profils livrés portent le
cloisonnement voulu par le descriptif fonctionnel. L'administrateur crée les
siens.

**Toute écriture inscrit un événement.** Distribuer des droits sans trace est
exactement ce que RNF-TRACE-01 interdit. Le filet
`test_toute_route_d_ecriture_inscrit_un_evenement` le vérifie sur toute route de
mutation.

## Les étendues délégables

Le front ne fait pas choisir des permissions une à une : il propose une
**étendue** — « Signature », « Cotation ». C'est un regroupement de permissions,
et le serveur seul énumère celles que le titulaire peut réellement déléguer.

**Ces regroupements sont une hypothèse.** RF-BPM-04 exige « la délégation
temporaire de tâches et de signature » sans dire quels gestes vont ensemble.
Ils sont dans `services.ETENDUES`, et inscrits en
[A15](../../../docs/questions-ouvertes.md).

Règle de construction : **au moins un profil livré porte l'intégralité de chaque
étendue.** Une étendue que personne ne détient en entier figurerait dans la liste
sans jamais être proposable. C'est arrivé à la première rédaction — « Signature »
y valait `(VAL, CLO)`, or le Directeur général porte `VAL` et non `CLO`. Clôturer
un courrier n'est pas le signer : c'est le Service Courrier Central qui clôture.

## Ce qui est déduit, jamais stocké

L'**état** d'une délégation — active, programmée, close — se calcule depuis les
dates. Une colonne d'état serait fausse le lendemain de son écriture, sans
qu'aucune écriture ne survienne.

L'**étendue** d'une délégation existante se retrouve depuis les permissions
enregistrées. Si aucun regroupement ne correspond exactement — parce que la liste
a changé depuis — on affiche les codes plutôt que de mentir sur ce qui a été
délégué.

## Le catalogue de périmètres n'est pas une table

Le premier abord des écrans trompe : ils montrent quatre périmètres nommés, ce
qui ressemble à un référentiel administrable. Ce n'en est pas un. Chaque compte
de démonstration du front porte `perimetre: { portee, structureId }` — la table
`perimetre` exactement. Les quatre entrées de l'écran **sont les quatre
portées**, présentées avec un libellé.

`GET /perimetres` renvoie donc les quatre portées, toujours les quatre, même
celles que personne ne porte : une portée qui disparaîtrait de l'écran faute de
titulaire ne serait plus attribuable. `id` y est un identifiant de référentiel,
stable, et non une clef de ligne.

Les deux options `voirConfidentiel` et `statistiquesAgregees` sont **constatées**
depuis les permissions `CONF` et `STAT` des agents concernés : vrai si *tous* les
portent. C'est descriptif, cela n'invente aucune règle.

`lectureClotures` reste faux. Aucune permission n'y correspond — `CLO` est
« clôturer un courrier », une action, pas une lecture. Inventer la permission
manquante reviendrait à remplacer une invention par une autre.
→ [A14](../../../docs/questions-ouvertes.md)

## Les deux écarts restants avec le front

Les écrans sont branchés, mais deux formes qu'ils attendent n'existent pas au
modèle, et **rien n'a été inventé pour combler** :

1. **L'état « invité ».** Il n'existe pas : la base porte `actif` et
   `invalide_le`, rien qui distingue un compte jamais activé. `vue=invitations`
   renvoie une liste vide. C'est un circuit entier qui manque, pas une colonne.
2. **`courriersEnCours`** est compté en SQL direct : la table `courrier` existe
   au schéma mais aucun modèle ne la couvre, et ouvrir le pilier courrier pour un
   compteur serait disproportionné.

## Ce qui est administrable

Tout ce qui compose ce qu'un autre logiciel appellerait « le rôle de quelqu'un »
se pose désormais par l'API, sous `ADM_HAB`, avec un événement au journal.

| Écriture | Route |
|---|---|
| Créer un compte | `POST /utilisateurs` |
| État civil, affectation | `PATCH /utilisateurs/{id}` |
| Suspendre / rétablir | `PATCH /utilisateurs/{id}/etat` |
| Permissions d'un profil | `PATCH /profils/{id}/permissions` |
| Poser / retirer une délégation | `POST` et `DELETE /delegations` |
| Attribuer / retirer un profil à un agent | `POST` et `DELETE /utilisateurs/{id}/profils` |
| Changer la portée d'un agent | `PATCH /utilisateurs/{id}/perimetre` |
| Rattacher / détacher un agent d'une session | `POST` et `DELETE /sessions/{id}/agents` |

**Rien n'est effacé.** Le périmètre change en clôturant l'ancien (`valide_au`) et
en ouvrant un nouveau ; le profil et le rattachement à une session se datent
(`retire_le`). Une habilitation supprimée sans trace est exactement ce que
`RNF-TRACE-01` interdit : on doit pouvoir dire qui avait quoi, et quand.

**Un garde-fou, pas une règle métier.** On ne peut pas se retirer à soi-même sa
dernière attribution portant `ADM_HAB` : qui s'exclut de l'administration des
habilitations ne peut plus s'y réadmettre, et si c'était le dernier
administrateur, plus personne ne le peut.

**L'exclusivité de session n'est pas contrôlée en Python.** Un agent ne tient
qu'une session courrier à la fois, et c'est une contrainte `EXCLUDE USING gist`
du moteur. Le service la devance uniquement pour que le refus soit lisible — il
ne la remplace pas.

## Créer un compte : quatre décisions

**Le profil et la portée sont obligatoires, et posés dans le même appel.** Un
compte sans profil ne peut rien ; un compte sans périmètre ne voit rien
(règle 3 de `perimetre/portee.py`). Créer un compte « nu » produirait un agent
qui se connecte, n'obtient que des listes vides, et fait chercher la panne
partout ailleurs. Les trois écritures sont atomiques.

**Le mot de passe est facultatif et provisoire.** `RF-ADM-02` délègue
l'authentification à l'annuaire ; la colonne `mot_de_passe` n'existe que le temps
de la bascule ([ADR 004](../architecture/004-session-cookie-sans-jeton.md)). Omis,
le compte existe et attend le SSO — il ne peut pas ouvrir de session. Le journal
enregistre lequel des deux cas s'est produit (`acces_local`).

**Le poste doit relever de la structure.** Aucune contrainte de base ne
l'interdit, et un « chef de service » de la DAF rattaché à la DSI fausserait en
silence toute portée `structure`.

**Il n'y a pas de route de suppression, et ce n'est pas un oubli.** Effacer un
compte effacerait qui a signé quoi. On suspend (`PATCH /{id}/etat`), ce qui laisse
en place profils, périmètre et signatures. Rien à purger côté sessions : `SessionAuth`
relit `is_active` à chaque requête, donc le compte suspendu est refusé au premier
appel suivant.

Deux garde-fous techniques, qu'aucun document ne porte :

- **on ne suspend pas son propre compte** — ce serait fermer la porte de
  l'extérieur en laissant la clef dedans ;
- **on ne mute pas un agent dont le périmètre est borné sur son ancienne
  structure.** Le déplacer d'office reviendrait à décider d'un droit à la place
  de l'administrateur ; ne rien faire lui laisserait la vue de son ancien
  service, sans que rien ne le signale. On exige donc les deux gestes, dans
  l'ordre qu'on veut.

## Quand vous y touchez

C'est la zone la plus dangereuse du projet. Une erreur ici ne casse rien
visiblement : elle donne des droits à quelqu'un, et personne ne le voit.

Les tests de `test_habilitation_api.py` ne vérifient pas que les routes
répondent — ils vérifient qu'elles **refusent**. Toute modification s'accompagne
d'un test qui échoue avant et passe après. Sans exception.


## Le registre affiche, la fiche administre

Deux formes coexistent pour un même compte, et la confusion coûterait cher.

`UtilisateurLigne` sert le **registre** : il joint les profils en une chaîne
(« Point focal · Administrateur »), ce qui se lit mais ne s'administre pas — on
ne retire pas un profil dont on n'a que le libellé. `FicheCompte`
(`GET /utilisateurs/{id}`) porte les identifiants, la portée en vigueur, la
structure sur laquelle elle s'appuie, la session courrier et `accesLocal`.

`accesLocal` mérite son nom : il dit qu'un mot de passe est posé, **jamais sa
valeur**. C'est la seule information d'administration qu'on puisse tirer d'un
haché, et le front en fait un avertissement — un compte sans accès local existe
et ne peut pas se connecter, ce que rien d'autre à l'écran ne révélerait (A20).

## Ce que le front en fait

Les écrans d'habilitation sont branchés depuis le 13 août 2026. Trois partis
pris s'y lisent, et ils viennent tous du serveur :

**Le formulaire de création impose profil et portée**, comme le service. Le
rendre plus permissif produirait des comptes qui se connectent et n'obtiennent
que des listes vides.

**Le panneau d'un agent n'a pas de bouton « Enregistrer » global.** Chaque geste
— attribuer un profil, le retirer, poser une portée, suspendre — est un appel et
un événement. Les regrouper derrière une seule validation rendrait illisible la
trace de ce qui a changé.

**L'onglet « Périmètres » ne modifie rien.** Ses quatre cases sont désactivées :
trois sont des permissions portées par les profils, la quatrième n'a aucune
source (A14). Le périmètre se pose agent par agent, dans sa fiche. Des cases
cochables y auraient laissé croire qu'on modifie un catalogue qui n'existe pas.

Les messages d'erreur métier remontent **tels quels** à l'écran, via
`messageDErreur()`. Ils sont rédigés pour l'agent : les remplacer par un
« l'opération a échoué » générique jetterait l'information qui permet de s'en
sortir.

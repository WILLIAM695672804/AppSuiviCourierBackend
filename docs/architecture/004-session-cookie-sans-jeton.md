# 004 — Session par cookie, sans jeton

**Statut :** acceptée · **Date :** 11 août 2026

## Contexte

Le front est déjà écrit. Son client HTTP appelle avec
`credentials: "include"`, ne pose aucun en-tête `Authorization`, et ne stocke
rien dans `localStorage`. Son garde de route (`ExigeSession`) redirige vers la
page de connexion sur **401**.

L'application est un intranet : un seul front, un seul backend, même
déploiement, sur site. Il n'y a pas d'application mobile, pas de client tiers,
pas de consommateur externe.

Par ailleurs, le schéma livré porte une table `utilisateur` dont les colonnes
sont en français — `mot_de_passe`, `derniere_connexion`, `identifiant_annuaire`,
`actif`, `invalide_le` — et RF-ADM-02 prévoit à terme une délégation de
l'authentification à l'annuaire (SSO/OIDC).

## Décision

**Session Django par cookie, protection CSRF, aucun jeton.**

- Le cookie de session est `HttpOnly`, `SameSite=Lax`, et `Secure` en
  production. Il est donc inaccessible au JavaScript — y compris à un script
  injecté.
- La protection CSRF est portée par `SessionAuth` de django-ninja, qui
  l'applique depuis la version 1.0. Ne pas passer `csrf=True` à `NinjaAPI` :
  l'argument n'existe plus et lève un `TypeError`.
- Une `AuthenticationError` sort en **401**, pas en 403, pour que le garde du
  front redirige au lieu d'afficher un écran vide.
- `AUTH_USER_MODEL = "noyau.Utilisateur"`, avec
  `AUTHENTICATION_BACKENDS = ["noyau.identite.authentification.BackendAnnuaire"]`.

### `Utilisateur` n'hérite pas de `AbstractBaseUser`

Il ne le peut pas : les champs entreraient en collision avec ceux du schéma
livré (`password` contre `mot_de_passe`, `last_login` contre
`derniere_connexion`). C'est donc un `models.Model` ordinaire qui **implémente à
la main** l'interface attendue par Django : `is_authenticated`, `is_anonymous`,
`is_active`, `get_username`, `set_password`, `check_password`,
`get_session_auth_hash`.

### Le point de bascule SSO est isolé

`BackendAnnuaire` fait déjà les deux : si le compte porte un
`identifiant_annuaire` et que le SSO est actif, il n'authentifie rien — c'est le
connecteur OIDC qui prendra le relais ; sinon il vérifie le mot de passe local.

La colonne `mot_de_passe` est une **dette assumée et datée** : le jour de la
bascule, la seconde branche disparaît et la colonne est vidée pour tous. Voir
[question ouverte A9](../../../docs/questions-ouvertes.md).

Le backend ne dit jamais laquelle des deux vérifications a échoué : une réponse
différenciée permettrait d'énumérer les comptes.

## Conséquences

- Rien de sensible dans `localStorage`, donc aucun vol de session par XSS.
- En développement, le front (`:5173`) et le backend (`:8000`) sont sur des
  origines différentes : `CSRF_TRUSTED_ORIGINS` et le CORS avec
  `credentials` doivent être réglés — c'est fait dans `reglages/dev.py`. En
  production, tout est servi sous la même origine et la question disparaît.
- Le backend est **avec état** : les sessions vivent en base. À l'échelle du PAD
  ce n'est pas un sujet, et cela permet la révocation immédiate — qu'un JWT ne
  permet pas sans réintroduire un état.
- Une API pour un client non-navigateur demanderait un autre mécanisme. Ce
  besoin n'existe pas ; s'il apparaît, il fera l'objet d'une décision.
- Toute route déclare son authentification. `/auth/deconnexion` l'avait oubliée —
  c'est le filet `test_toute_route_porte_une_authentification` qui l'a trouvée,
  avant toute revue humaine.

## Ce qui invaliderait cette décision

- Une application mobile ou un client tiers à authentifier.
- Un déploiement multi-domaines où le cookie ne pourrait plus être posé.
- La bascule SSO, qui ne remet pas en cause le cookie mais **supprime** la
  branche mot de passe local : ce jour-là, cette décision se met à jour par une
  nouvelle.

## Alternatives écartées

**JWT.** Le front n'en veut pas — il n'a nulle part où le mettre en sécurité.
`localStorage` est lisible par tout script injecté ; un cookie `HttpOnly` ne
l'est pas. Et la révocation immédiate, indispensable pour un agent dont on
retire les droits, ramènerait une liste de révocation, c'est-à-dire l'état qu'on
prétendait supprimer.

**Jeton d'API par utilisateur.** Utile pour des intégrations serveur à serveur.
Aucune n'est prévue ; à traiter le jour où l'une le sera.

**SSO tout de suite.** C'est la cible (RF-ADM-02), mais le connecteur OIDC est un
chantier à part et dépend de la DSI. Il fallait pouvoir ouvrir une session en
attendant, en développement comme en démonstration.

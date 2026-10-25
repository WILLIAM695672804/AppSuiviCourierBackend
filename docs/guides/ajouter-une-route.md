# Ajouter une route

Le geste le plus courant du projet. Sept points, dans l'ordre, et aucun n'est
facultatif.

Route de référence, courte et complète : `noyau/identite/api.py`.

## 1. Le squelette

```python
# activite/api.py
from ninja import Router

from noyau.habilitation.dependances import PERM, exige

routeur = Router()


@routeur.post("/{identifiant}/suspension", auth=exige(PERM.DEC), response=FicheActivite)
def suspendre(request, identifiant: int, saisie: SaisieSuspension):
    """Suspend une activité — §17. Une activité suspendue n'accepte plus d'avancement."""
    return services.suspendre(request.auth, identifiant, saisie)
```

Deux contraintes de ninja pèsent sur **chaque** route, et la première va contre
la convention française du projet. Elles n'en sont pas moins obligatoires.

**Le premier paramètre s'appelle `request`, en anglais.** Ninja ne le reconnaît
que par son nom. Appelé `requete`, il devient un paramètre de query string
obligatoire et la route répond 422 « Field required » à chaque appel — sans
qu'aucune erreur ne survienne au démarrage. C'est l'API de la bibliothèque,
comme `self` ; c'est la seule exception à la règle du français.

**Il n'est pas annoté.** Ninja construirait un schéma Pydantic pour
`HttpRequest`, qui n'est pas sérialisable, et le serveur ne démarrerait plus.

`request.auth` porte l'utilisateur : c'est ce que renvoie notre garde.

## 2. `auth=` — la permission

`auth=exige(PERM.DEC)` : session ouverte **et** au moins une des permissions
citées. Plusieurs codes sont acceptés (`exige(PERM.COT, PERM.COT_DEL)`) et
valent « au moins une », comme `usePermission` côté front.

Les codes sont dans la classe `PERM` de `noyau/habilitation/dependances.py`, en
miroir de la table `permission` et de
`frontend/src/types/habilitation.ts`. Ajouter une permission, c'est donc trois
endroits — et une migration.

`session_seule` existe, mais **pour `/auth/moi` uniquement**. Toute autre route
nomme la permission qu'elle exige.

Une route sans `auth=` est une route ouverte : le test
`test_toute_route_porte_une_authentification` la refusera, et il aura raison.

## 3. `restreindre()` — le périmètre

**La permission ne dit pas sur quelles données.** Dès que la route renvoie plus
d'un objet nommément désigné :

```python
from noyau.perimetre.portee import restreindre

requete_sql = restreindre(
    Activite.objects.all(),
    utilisateur,
    champ_structure="structure",
    champ_agent="responsable",  # obligatoire si la portée `propre` a un sens ici
)
```

Deux pièges, tous deux volontaires :

- `structures_visibles()` renvoie **`None`** pour la portée `toutes` — « aucune
  restriction », pas « aucune structure ». Le traiter comme une liste vide
  fermerait l'accès aux seuls profils qui doivent tout voir.
- `restreindre()` **lève `ValueError`** si la portée `propre` est demandée sans
  `champ_agent`. Retourner la requête inchangée reviendrait à tout montrer.

Pour un objet unique, on récupère puis on vérifie, et on lève `HorsPerimetre` —
qui sort en **404**, pas en 403 (décision D5).

Oublier `restreindre()` ne produit **aucune erreur**. C'est le risque le plus
sérieux du projet. Relisez-le avant d'ouvrir la revue.

## 4. La règle dans un service, pas dans la route

Une route **valide, appelle, sérialise**. Rien d'autre. Les règles vivent dans
`services.py`, où elles sont testables sans HTTP et réutilisables par une tâche
Celery.

Si votre route dépasse une dizaine de lignes, la règle a fui dedans.

## 5. Le journal

Toute écriture métier inscrit un événement :

```python
from noyau.journal.service import inscrire

inscrire(
    objet_type="activite",
    objet_id=activite.pk,
    type_evenement="suspension",
    libelle="Activité suspendue",
    acteur=acteur,
    agit_pour=titulaire,
)
```

`agit_pour` n'est pas facultatif quand une délégation est active. Voir
[traçabilité](../tracabilite.md).

## 6. Les erreurs

| Situation | Ce qu'on lève |
|---|---|
| une règle refuse le geste | `ErreurMetier("…")` → 409 |
| l'objet n'est pas dans le bon état | `EtatInvalide("…")` → 409 |
| l'objet existe mais n'est pas visible | `HorsPerimetre()` → 404 |
| la saisie est mal formée | rien : Pydantic → 422 |

Le message est affiché **tel quel** à l'agent. Il est en français, il dit ce qui
bloque et ce qui débloquerait. « Conflit d'état » n'apprend rien à personne.

Les gestionnaires sont déjà posés dans `config/api.py` ; les sous-classes de
`ErreurMetier` sont prises en charge sans rien déclarer.

## 7. Les schémas

Dans `schemas.py`, deux familles séparées : `SaisieXxx` en entrée, `XxxSortie`
en sortie. Ne renvoyez jamais un schéma d'entrée.

**Sortie en camelCase.** Le front porte des interfaces TypeScript écrites à la
main (`avancementAttendu`, `structureSigle`) ; la base est en `snake_case`. Les
schémas ninja sont le seul endroit où les deux se croisent, et il vaut mieux que
ce soit un seul endroit.

La forme de référence est celle que le front attend déjà :
`frontend/src/features/<pilier>/api.ts`. Quand vous hésitez, c'est elle qui
tranche.

## 8. Monter le routeur

Dans `config/api.py`, **et nulle part ailleurs** :

```python
from activite.api import routeur as routeur_activite

api.add_router("/activites", routeur_activite, tags=["Activites"])
```

## Avant d'ouvrir la revue

- [ ] `auth=` nomme une permission
- [ ] `restreindre()` appelé, ou une raison écrite de ne pas l'appeler
- [ ] la règle est dans un service
- [ ] toute écriture inscrit un événement
- [ ] un test qui échoue sans le code et passe avec
- [ ] `make verifier` passe
- [ ] si la route change un comportement décrit ailleurs, la page correspondante
      est modifiée **dans le même diff**

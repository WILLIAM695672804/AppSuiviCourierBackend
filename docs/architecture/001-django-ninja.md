# 001 — django-ninja plutôt que Django REST Framework

**Statut :** acceptée · **Date :** 11 août 2026

## Contexte

Le backend est imposé : Python et Django (choix du client). Reste à choisir la
couche API.

Le front existe déjà, entièrement, en mode démo. Il consomme des formes JSON
précises, décrites par des types TypeScript. Le risque principal du projet n'est
donc pas d'écrire l'API : c'est de la faire **diverger** de ce que le front
attend déjà.

DRF est la solution par défaut de l'écosystème. Sa description d'API passe par
des sérialiseurs, et sa documentation OpenAPI par une bibliothèque tierce
(`drf-spectacular`) qui infère le schéma — avec les approximations que cela
suppose.

## Décision

Nous utilisons **django-ninja** pour l'API HTTP.

Une seule instance `NinjaAPI`, déclarée dans `config/api.py`, montée sur `/api`
par `config/urls.py`. Pas de préfixe de version dans l'URL : le front et le
backend sont déployés ensemble, sur site, par la même équipe.

Les entrées et sorties sont décrites par des schémas Pydantic, dans le
`schemas.py` de chaque module.

## Conséquences

- L'OpenAPI est **dérivé des annotations de type**, pas inféré. Ce qui est
  publié sur `/api/docs` est ce que le code fait.
- La validation d'entrée est celle de Pydantic : elle sort en 422, et
  `config/api.py` la met en forme.
- L'authentification est portée par le paramètre `auth=` de chaque route. C'est
  explicite et lisible, mais rien n'oblige à le remplir — d'où le filet
  `test_toute_route_porte_une_authentification`, qui rend l'oubli impossible.
- Nous perdons ce que DRF apporte et que ninja n'a pas : les vues génériques, le
  routeur automatique, la pagination intégrée, l'API navigable. Aucun ne nous
  manque : les routes de ce projet sont des gestes métier (« coter »,
  « suspendre », « relever un indicateur »), pas du CRUD. Une vue générique
  n'aurait rien à générer.
- Moins de ressources en ligne qu'avec DRF. C'est un coût réel pour un
  développeur qui arrive.

## Ce qui invaliderait cette décision

- Le besoin d'exposer l'API à des consommateurs externes versionnés
  indépendamment (le préfixe de version deviendrait nécessaire, et la question
  du cadre se rouvrirait).
- L'arrivée d'un volume important de vraies ressources CRUD, où les vues
  génériques de DRF paieraient.
- L'abandon de django-ninja en amont.

## Alternatives écartées

**DRF.** Plus lourd pour un gain nul ici, et sa documentation OpenAPI est
inférée alors que nous avons besoin qu'elle soit exacte : c'est le contrat avec
un front déjà écrit.

**FastAPI à côté de Django.** Deux serveurs, deux couches d'authentification,
deux façons d'accéder à la base. Le coût d'exploitation, sur site, ne se
justifiait pas.

**Vues Django nues.** Sérialisation et validation à la main sur plusieurs
dizaines de routes : c'est exactement là que naissent les divergences avec le
front.

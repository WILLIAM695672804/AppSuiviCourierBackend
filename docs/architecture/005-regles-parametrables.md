# 005 — Les règles sans source vivent en base, marquées « hypothèse »

**Statut :** acceptée · **Date :** 11 août 2026

## Contexte

En reprenant le pilier « activités », un écart a été constaté entre ce que les
documents demandent et ce que le prototype fait.

Les documents disent **quoi** suivre : rattachement à un axe stratégique,
avancement, indicateurs, tâches, plan d'actions annuel, relances (§15 à §20 du
cahier des charges). Ils ne disent nulle part **comment** :

- comment se calcule l'avancement *attendu* à une date donnée ;
- à partir de quel écart une activité est « en retard » ;
- ce qui rend une activité « critique » ;
- comment se calcule le taux d'atteinte d'un indicateur.

Le prototype répond aux quatre. Ces réponses ont été **inventées par la
conception** : interpolation linéaire, seuil de 10 points, retard *plus*
contrainte échue, progression de la référence vers la cible. Aucune n'a de
source.

Le danger n'est pas qu'elles soient fausses — il faut bien décider quelque chose
pour livrer. Le danger est qu'**elles deviennent indiscernables des règles
fondées**. Six mois plus tard, personne ne saura que le 10 est arbitraire, et
il sera défendu comme une exigence du client.

## Décision

Toute règle de gestion **sans source documentaire** est stockée dans la table
`parametre`, avec :

- `statut` valant `'acte'` ou `'hypothese'` ;
- `source` — la référence, pour ce qui est acté ;
- `a_trancher_par` — **qui** doit décider, pour ce qui ne l'est pas.

Une contrainte de base impose le second :

```sql
CONSTRAINT parametre_hypothese_a_un_responsable
  CHECK (statut = 'acte' OR a_trancher_par IS NOT NULL)
```

Une hypothèse sans responsable désigné ne serait jamais tranchée — c'est
exactement ce qui est arrivé aux quatre premières.

Le code lit ces valeurs par `noyau/parametres/service.valeur(cle, defaut)`, avec
un cache module. **Aucun de ces nombres n'est écrit en dur dans une règle.**

Chaque hypothèse a son entrée dans
[questions ouvertes](../../../docs/questions-ouvertes.md) (A1 à A4), avec ce
qu'elle coûtera si la réponse arrive tard.

### Ce que la table contient aujourd'hui

| Clé | Valeur | Statut | Tranché par |
|---|---|---|---|
| `activite.mode_avancement_attendu` | `lineaire_jours_ouvres` | hypothèse | DSR + contrôle de gestion |
| `activite.seuil_retard_points` | `10` | hypothèse | DSR |
| `activite.criticite_exige_contrainte` | `true` | hypothèse | Direction générale |
| `activite.mode_taux_indicateur` | `reference_vers_cible` | hypothèse | Contrôle de gestion |
| `activite.axes_strategiques` | `A1\|A2\|A3` | **acte** | — (communication DG du 11 août 2026) |

Le contraste est l'essentiel : la dernière ligne porte une source, les quatre
premières portent un nom de décideur.

## Conséquences

- Un arbitrage se traduit par une mise à jour de ligne, pas par une livraison.
- La question « d'où sort ce chiffre ? » a une réponse, en base, consultable par
  l'administrateur fonctionnel comme par le développeur.
- Écran d'administration à prévoir (`ADM_PAR`), avec `statut` et
  `a_trancher_par` **affichés** : un paramètre modifiable dont on ignore le
  statut est plus dangereux qu'un nombre en dur, parce qu'on le change sans
  savoir ce qu'on remet en cause.
- Un léger coût de lecture : une règle ne se lit plus dans le code seul. Le cache
  module l'assume côté performance.
- **Limite assumée :** changer un paramètre change le calcul des données
  **passées**. Un historique d'états « en retard » calculé au seuil de 10 n'est
  pas comparable à un historique calculé à 5. Si le besoin d'historiser les
  valeurs de paramètres apparaît, il fera l'objet d'une décision.

## Ce qui invaliderait cette décision

- Les quatre hypothèses tranchées et devenues des `'acte'` sourcés : la table
  garderait alors son utilité de paramétrage, mais le mécanisme de statut
  perdrait sa raison d'être — et il faudrait vérifier qu'il ne sert plus à
  masquer de nouvelles inventions.
- Un besoin de règles variables **par structure** ou par année : la table est
  aujourd'hui globale, et il faudrait la revoir plutôt que d'y encoder des clés
  composées à la main.

## Alternatives écartées

**Les valeurs en dur, avec un commentaire.** C'est ce que faisait le prototype.
Le commentaire ne survit pas à la première refactorisation, et le nombre devient
une exigence par prescription.

**Un fichier de réglages Python.** Mieux qu'en dur, mais un arbitrage métier
demanderait alors une livraison — et la question « qui doit trancher ? » n'aurait
toujours pas de place où s'écrire.

**Attendre les réponses avant d'implémenter.** Le projet serait à l'arrêt. Les
questions sont posées ; en attendant, on livre en disant clairement ce qu'on a
supposé.

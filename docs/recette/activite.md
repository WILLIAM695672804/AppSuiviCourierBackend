# Recette — pilier « activités »

Ce qu'un testeur fonctionnel vérifie avant de valider une livraison du pilier.
Écrit pour être exécuté par quelqu'un qui ne lit pas le code.

Chaque scénario dit **avec quel compte** se connecter : la moitié des défauts de
ce projet ne se voient qu'en changeant d'utilisateur.

Statut : **à exécuter dès que le pilier existe.** Rien n'est encore livré côté
backend.

## Comptes nécessaires

| Rôle dans les tests | Profil | Ce qu'il doit avoir |
|---|---|---|
| Point focal A | point focal | `ACT_SAI`, portée `structure`, structure A |
| Point focal B | point focal | `ACT_SAI`, portée `structure`, structure B |
| Directeur | directeur | portée `structure_et_descendants` sur A |
| Autorité | — | `DEC` |
| DSR | attaché DSR | `REL`, portée `institution` |
| Contrôle de gestion | DCG | `ACT_VAL` |

## 1. Déclaration

- [ ] Le point focal A crée une activité : l'axe stratégique est une **liste
      déroulante de trois entrées**, jamais un champ libre.
- [ ] L'énoncé officiel complet de l'axe s'affiche sur la fiche, pas seulement le
      libellé court.
- [ ] L'activité créée apparaît au plan d'actions de la structure A.
- [ ] Le point focal A déclare un avancement de 30 % : la fiche de vie porte
      l'événement, avec son nom et l'horodatage.

## 2. Visibilité — le plus important

- [ ] Le point focal **B** ne voit pas l'activité de la structure A. Ni dans une
      liste, ni par recherche.
- [ ] **Par l'URL directe** de l'activité de A, le point focal B obtient
      « introuvable » — et non « accès interdit ». La différence n'est pas
      cosmétique : « interdit » confirmerait que l'activité existe.
- [ ] Le **directeur** de A voit les activités de A et celles de ses divisions.
- [ ] La **DSR** voit tout.
- [ ] Le sélecteur de structure ne propose que les structures accessibles — et
      forcer une autre structure dans l'URL ne montre rien de plus.

## 3. Suspension

- [ ] Le point focal A **ne peut pas** suspendre : le bouton est absent, et
      l'appel direct est refusé.
- [ ] L'autorité suspend avec un motif : le motif est visible sur la fiche.
- [ ] Le point focal A tente de déclarer un avancement : refus, avec un message
      **en français, compréhensible**, disant que l'activité est suspendue.
- [ ] L'activité suspendue n'apparaît plus comme critique.
- [ ] Après reprise, la déclaration d'avancement redevient possible.

## 4. Retard et criticité

- [ ] Une activité dont l'avancement est très inférieur à l'attendu remonte
      comme **en retard**.
- [ ] Elle ne devient **critique** qu'en portant en plus une instruction non
      levée échue ou une tâche non faite échue.
- [ ] Une activité réalisée n'est jamais critique.
- [ ] Le cockpit de la DG affiche les activités critiques et l'alerte associée.
- [ ] **Le lendemain, sans qu'aucune saisie n'ait eu lieu**, les états ont
      changé : c'est le recalcul nocturne. S'il ne tourne pas, seules les
      activités que quelqu'un a touchées paraissent en retard — et le défaut est
      invisible en test manuel sur une seule journée.

## 5. Indicateurs et tâches

- [ ] Ajout d'un indicateur avec référence et cible ; le taux d'atteinte
      s'affiche.
- [ ] Un relevé daté modifie le taux, et le relevé précédent reste consultable.
- [ ] **Indicateur décroissant** (un délai à réduire) : à vérifier explicitement.
      Le calcul actuel ne traite pas ce cas et affiche un taux faux —
      [A4](../../../docs/questions-ouvertes.md). Ce n'est pas une régression à
      signaler mais un arbitrage attendu ; c'est ici pour qu'on ne le découvre
      pas en production.
- [ ] Une tâche échue non faite apparaît comme contrainte échue.

## 6. Instructions et relances

- [ ] L'autorité rattache une instruction avec échéance ; elle apparaît sur la
      fiche.
- [ ] La levée est tracée : par qui, quand.
- [ ] La DSR relance ; la date de dernière relance s'affiche.
- [ ] Le point focal ne peut pas relancer.

## 7. Plan d'actions annuel

- [ ] Le point focal soumet le plan de sa structure.
- [ ] Le plan apparaît à la DCG dans « plans à valider ».
- [ ] Validation, puis renvoi d'un autre plan avec motif : le motif remonte à la
      structure.
- [ ] Le point focal **ne voit pas** l'écran de validation.
- [ ] Un plan déjà soumis ne se soumet pas deux fois : message clair.

## 8. Traçabilité

- [ ] Chaque geste des sections précédentes a laissé un événement sur la fiche de
      vie, dans l'ordre chronologique.
- [ ] Sous **délégation** : la fiche de vie montre le bénéficiaire **et** le
      titulaire au nom de qui il agit. Une seule des deux identités est un
      défaut bloquant.

## 9. Le reste

- [ ] Session expirée : redirection vers la connexion, **pas** d'écran vide.
- [ ] Pièce jointe : dépôt, téléchargement, et une pièce d'une autre structure
      reste inaccessible.
- [ ] Les libellés, messages d'erreur et intitulés sont en français, accentués.

## À signaler comme question, pas comme défaut

Un écart entre le backend et ce que décrivent les jeux de données de
`frontend/src/lib/demo/` n'est pas automatiquement un bug : le front a été
construit contre eux, ils sont débranchés depuis l'ADR 008, et certaines règles
qu'ils appliquaient n'ont jamais été arbitrées. Consigner dans
[questions ouvertes](../../../docs/questions-ouvertes.md).

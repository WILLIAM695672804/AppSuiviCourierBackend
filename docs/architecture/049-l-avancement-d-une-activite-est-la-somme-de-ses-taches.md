# 049 — L'avancement d'une activité est la somme de ses tâches

*Statut : acceptée — 11 septembre 2026. Déplace le recalibrage de
l'[ADR 030](030-le-taux-declare-et-le-taux-retenu-sont-deux-choses.md) de
l'activité vers la tâche, et remplace le poids et l'échéance dont parlait
l'[ADR 048](048-la-tache-n-a-pas-d-attributaire.md). Ni l'un ni l'autre n'est
réécrit.*

## Contexte

Jusqu'au 10 septembre 2026, une tâche était **binaire** — `etat` à `a_faire`
ou `faite` — et pesait de 1 à 10 (`poids`). Le déclencheur calculait
`avancement_calcule` au prorata des poids des tâches faites, et la modale de
déclaration demandait en outre un pourcentage sur l'activité elle-même. Une
tâche à moitié réalisée ne comptait pour rien ; un taux saisi sur l'activité
pouvait contredire les tâches cochées à côté. Deux grandeurs pour un même fait.

La demande, posée le 11 septembre 2026, fait de l'avancement une grandeur
**dérivée** :

- **RG-1** — une activité compte une ou plusieurs tâches, saisies à sa création ;
- **RG-2** — chaque tâche a une valeur prévue, en pourcentage de l'activité, de
  0 à 100 ;
- **RG-3** — la somme des valeurs prévues vaut exactement 100, contrôlée à la
  création et à toute modification de la liste ;
- **RG-4** — l'avancement se déclare sur une tâche : activité → tâche →
  déclaration ;
- **RG-5** — la valeur obtenue s'exprime dans l'échelle de l'activité : prévue
  30, déclarée 15, la tâche apporte 15 points ;
- **RG-6** — la valeur obtenue cumulée ne dépasse pas la valeur prévue ;
- **RG-7** — l'avancement de l'activité est la somme des valeurs obtenues ;
- **RG-8** — la période d'une tâche est un intervalle de mois, sans jour, et
  sans saisie d'année ;
- **RG-9** — cet intervalle est contenu dans celui de l'activité.

Quatre points ont été tranchés avec la demande : la déclaration est
**cumulative** ; l'avancement propre d'une tâche vaut obtenue / prévue × 100 ;
l'existant est **repris en SQL** ; plus aucune saisie directe ne porte sur
l'activité.

Restait le recalibrage de l'ADR 030, posé sur l'activité. L'arbitrage, dans les
mots de l'utilisateur : « le recalibrage se fera maintenant sur les tâches,
parce qu'il faut que la somme des valeurs obtenues soit égale à la valeur de
l'activité ». Un taux retenu sur l'activité ne se répartit sur aucune tâche, et
la somme des tâches cesserait d'égaler ce que la fiche affiche.

## Décision

**La tâche porte les grandeurs, l'activité en fait la somme.** Migration
`0010_avancement_par_taches` (`sql/0004_avancement_par_taches.sql`) :

- `tache.valeur_prevue` — la part, `]0 ; 100]` au centième
  (`tache_valeur_prevue_bornee`) ;
- `tache.valeur_obtenue` — la déclaration cumulée, `[0 ; valeur_prevue]`
  (`tache_valeur_obtenue_plafonnee`) ;
- `tache.valeur_recalibree`, `recalibrage_motif`, `recalibre_le`,
  `recalibre_par` — le recalibrage de la DSR, plafonné et motivé
  (`tache_recalibrage_plafonne`, `tache_recalibrage_motive`) ;
- `tache.valeur_retenue` — colonne générée, `COALESCE(valeur_recalibree,
  valeur_obtenue)` ;
- `tache.date_debut`, `date_fin` — premier et dernier jour d'un mois
  (`tache_periode_au_mois`).

Le déclencheur `maj_avancement_activite()` pose `activite.avancement_calcule`
à la somme des valeurs obtenues, et `avancement_recalibre` à la somme des
valeurs retenues dès qu'une tâche au moins est recalibrée — `NULL` sinon.
`avancement_retenu` reste la colonne générée qu'elle était : tableaux de bord,
scoring et criticité continuent de lire la même colonne, sans une ligne changée.

**RG-3 vit dans le service, pas au moteur.** Passer de 50/50 à 30/70 transite
par une somme fausse ; une contrainte immédiate refuserait tout redécoupage, et
une contrainte différée lèverait au `COMMIT`, hors du point où le service
traduit une `IntegrityError` en 409 — l'agent recevrait une erreur 500. Le
service valide donc la liste **entière** avant la première écriture (code
`somme_taches`). Le moteur garde `activite_avancement_borne` en filet.

**Les routes suivent.** `POST /activites` exige `taches` ;
`POST /activites/{id}/taches` remplace la liste entière, avec motif (événement
`activite_taches_modifiees`) — l'ajout unitaire disparaît, puisque la somme ne
se contrôle que sur la liste ; `POST /activites/{id}/avancement` prend
`{tacheId, valeurObtenue, observation}` ; `POST /activites/{id}/recalibrage`
prend `{tacheId, valeur, motif}`, `valeur` à `null` levant le recalibrage. Les
mois transitent en `AAAA-MM` : le sélecteur du front ne propose que ceux de
l'activité et porte l'année, qui ne se saisit donc pas.

**Cinq règles ont été ajoutées sans figurer dans la demande**, parce que la
demande les rendait nécessaires :

1. la valeur prévue est **strictement** positive — une tâche à 0 ne pèserait
   rien et serait « faite » dès sa création ;
2. une tâche qui a déjà avancé (obtenue ou retenue non nulle) **ne se retire
   pas** (`tache_avancee_retiree`) : ses points disparaîtraient de l'activité
   sans déclaration ni recalibrage ;
3. la valeur prévue ne descend pas **sous ce que la tâche a obtenu**
   (`valeur_prevue_sous_obtenue`), sans quoi RG-6 serait violée a posteriori ;
4. la période d'une activité ne se **resserre** pas si des tâches en
   sortiraient (`tache_hors_periode`) ;
5. un recalibrage **tient** malgré une nouvelle déclaration : la valeur retenue
   reste celle de la DSR tant qu'elle ne l'a pas levée.

## Conséquences

**La reprise transforme l'existant sans rien perdre de ce qu'il affirmait** :

- les parts valent `round(100 × poids / Σ poids, 2)`, le reliquat d'arrondi
  allant à la dernière tâche (33,33 / 33,33 / 33,34) ;
- une tâche `faite` obtient sa part, une tâche `a_faire` zéro ;
- une activité sans tâche en reçoit une, « Exécution de l'activité », à 100,
  dont la valeur obtenue reprend l'avancement antérieur ;
- la période d'une tâche commence au mois de début de l'activité et finit au
  mois de son échéance, ramenée dans la période de l'activité — ou au mois de
  fin de l'activité, faute d'échéance ;
- un recalibrage d'activité se répartit sur les tâches dans leur ordre, chacune
  à hauteur de sa part ;
- `tache.etat`, `poids`, `date_echeance` et le recalibrage de l'activité
  (`recalibrage_motif`, `recalibre_le`, `recalibre_par`) sont supprimés.

**Deux effets se voient.** Une activité **suspendue** est recalculée
déclencheurs désactivés, `refuser_avancement_si_suspendue()` refusant sinon la
mise à jour : l'arrondi peut la décaler d'un centième (66,67 devient 66,66).
Une activité **échue** dont les tâches n'avaient pas d'échéance hérite de sa
date de fin sur chacune : si elle n'est pas terminée, elle devient
`contrainte_echue` dans `v_activite_etat`, donc potentiellement critique. C'est
exact — la tâche est en retard — mais c'est nouveau.

**L'ancien contrat sort en 422** : un poste resté sur la version antérieure du
front envoie `avancement` et `tachesFaites`, que le schéma ne connaît plus.
C'est voulu : accepter un taux d'activité le ferait disparaître sans effet.

**L'importeur du plan DFC 2026** crée ses activités avec leurs tâches en une
requête, à parts égales, faute de pondération dans le classeur source.

**Le semis de démonstration backend est aligné** : parts égales, tâche unique
« Exécution de l'activité » pour les fiches qui n'en ont pas, comme dans la
reprise, et une déclaration par tâche avancée. Le faux serveur du front
(`frontend/src/lib/demo`) ne l'est **pas**, à la demande de l'utilisateur : il
écrit encore `poids`, `etat` et `echeance`, et sa compilation échoue.

## Ce qui invaliderait cette décision

Une pondération qui ne s'additionne pas : des tâches parallèles dont la plus
lente borne l'activité, ou des jalons dont l'atteinte vaut tout ou rien. La
somme cesserait alors de décrire l'avancement.

Un besoin de la DSR de recalibrer une activité **en bloc**, sans désigner de
tâche. Il faudrait alors une règle de répartition — celle de la reprise en est
une — et l'accepter comme un arbitrage de gestion, pas comme un calcul.

## Alternatives écartées

**Garder le recalibrage sur l'activité.** Écarté par l'utilisateur : la somme
des valeurs retenues des tâches ne serait plus l'avancement retenu, et la fiche
afficherait deux vérités.

**Déclaration incrémentale** — « 5 points de plus ». Écartée par le point 1 de
la demande : une valeur cumulée se corrige en la ressaisissant, un incrément
erroné oblige à en déclarer un négatif.

**Somme à 100 portée par un déclencheur de contrainte différé.** Écarté pour la
raison dite plus haut : le refus arriverait au `COMMIT`, sans code métier, et
l'agent verrait une panne là où il a fait une erreur de saisie.

**Laisser la dernière tâche absorber le reliquat à la saisie.** Écarté : le
formulaire affiche le total courant et propose le reliquat à l'ajout d'une
ligne, mais c'est l'agent qui décide des parts. Corriger en silence la dernière
tâche changerait une pondération qu'il a écrite.

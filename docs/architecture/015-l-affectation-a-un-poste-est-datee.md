# ADR 015 — L'affectation à un poste est datée, et la colonne reste

**Date** : 14 août 2026
**Statut** : acceptée
**Exigences** : F-04, RNF-TRACE-01, principe 2 de `noyau/organisation/modeles.py`

## Le problème

`utilisateur.poste` est une clef étrangère simple. Elle dit qui occupe quel
poste **aujourd'hui**, et rien d'autre.

Trois conséquences, dont la troisième est la vraie :

1. Muter un agent écrase la colonne. L'occupant précédent disparaît.
2. La question « qui tenait le poste de chef de la DSR le 12 mars ? » n'a aucune
   réponse dans la base.
3. **La hiérarchie du circuit se lit par le poste**, jamais par l'agent — c'est
   le principe 2 du module. Un courrier validé en mars par « le chef de la DSR »
   se relit donc, en décembre, avec l'occupant de décembre. La fiche de vie du
   courrier (A-13) affiche un nom qui n'a jamais rien signé.

C'est le même trou que `utilisateur_profil` a comblé pour les droits, et il pèse
davantage : les droits d'un agent expliquent ce qu'il *pouvait* faire, le poste
explique ce qu'il *a* fait, et au nom de qui.

## Les options

**Remplacer la colonne par une jointure sur intervalle.** Le poste courant se
déduirait de `affectation_poste WHERE fin IS NULL`. C'est la forme la plus pure,
et elle a été écartée : sept écrans lisent `utilisateur.poste`, la portée
`poste` du périmètre s'appuie dessus à chaque requête de liste, et
`lecture.responsables()` la joint pour chaque structure de l'organigramme.
Remplacer une clef étrangère par un intervalle dans le chemin le plus chaud du
serveur coûte à chaque requête pour un besoin qui se pose une fois par audit.

**Garder la colonne seule et journaliser les mutations.** Le journal enregistre
déjà `compte_modifie`. Écarté : un événement dit *qu'un* poste a changé, pas
*qui occupait quoi entre quelles dates*. Reconstituer l'occupation d'un poste
supposerait de rejouer tous les événements du compte dans l'ordre — un travail
d'archéologie à chaque question, et impossible à joindre à une requête.

**Les deux, écrits ensemble.** Retenu.

## La décision

`affectation_poste` porte l'histoire : agent, poste, début, fin, motif.
`utilisateur.poste` reste le présent.

**`organisation.services.affecter()` est le seul point du dépôt qui écrit l'une
ou l'autre.** Les deux partent dans la même transaction. C'est ce qui empêche
qu'elles divergent, et c'est aussi la fragilité de la décision : un second
appelant qui poserait `agent.poste = …` directement troue l'histoire sans
qu'aucune erreur ne le signale. C'était exactement le cas de
`habilitation.services.modifier_compte`, qui passe désormais par le service.

Trois règles de fond :

- **Une seule affectation ouverte par agent.** Contrainte d'unicité partielle,
  posée en base et non dans le service : `utilisateur.poste` est une clef
  simple, et une seconde ligne ouverte n'aurait aucune traduction dans le
  présent.
- **Une mutation ne se chevauche pas d'une journée.** `affecter()` clôt la ligne
  en cours *la veille* du nouveau début. Sur un poste de validation, une journée
  à deux titulaires est une journée où deux personnes ont pu signer au même
  titre.
- **Une fin sans suite laisse l'agent sans poste**, et le poste redevient
  vacant. Le tableau de bord de l'administration le compte comme tel — c'est
  ce qu'on veut voir, pas ce qu'on veut cacher.

## Ce que la décision coûte

Le semis de l'existant date chaque affectation en cours de la **création du
compte**. C'est une approximation, et elle est assumée : la seule autre option
honnête était de laisser l'histoire vide, ce qui aurait fait croire que personne
n'a jamais occupé de poste avant la migration. Une date fausse se corrige ; une
absence se lit comme un fait.

## Conséquences

- `POST /organisation/affectations` sert la première affectation **et** la
  mutation. Il n'y a pas de route « muter » : ce serait le même geste sous deux
  noms, avec deux occasions de diverger.
- `POST /organisation/affectations/{id}/fin` sert le départ, la retraite, la
  mise à disposition — tout ce qui ne donne pas de successeur.
- La fiche d'un compte peut désormais afficher son parcours dans l'institution.
  Aucun écran ne le fait encore ; la matière existe.

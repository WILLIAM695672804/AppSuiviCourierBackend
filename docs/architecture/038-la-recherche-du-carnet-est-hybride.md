# 038 — La recherche du carnet d'adresses est hybride, et classée

28 août 2026.

## Contexte

Le référentiel des correspondants n'a qu'une raison d'être : qu'un même
ministère ne finisse pas écrit de six manières. C'est pourquoi le sélecteur
d'expéditeur ne laisse pas taper un nom au clavier.

Il ne remplit cette fonction que si l'agent **retrouve** l'entrée existante. Une
entrée qu'on ne retrouve pas est une entrée qu'on recrée — et le référentiel
produit alors exactement ce qu'il était censé empêcher, avec en prime un compte
« 14 courriers reçus » faux pour les deux moitiés.

La recherche était en `websearch` sur le vecteur plein texte. Trois manques :

1. **Pas de préfixe.** `to_tsvector` indexe des mots entiers : « minis » ne
   trouvait pas « Ministère ». L'agent tape rarement le nom complet.
2. **Aucune tolérance.** Une lettre oubliée — « minstere » — ne trouvait rien.
   Et l'apostrophe coupe le mot : « N'Djamena » s'indexe sous `djamen`, donc
   « ndjamena » ne le trouvait pas.
3. **Pas de sigle.** « MINFI » n'existait nulle part dans le schéma, alors que
   c'est ce qui est imprimé sur l'en-tête de la lettre que l'agent tient, et
   donc ce qu'il tape en premier.

À quoi s'ajoutait un défaut de présentation : les résultats sortaient dans
l'ordre alphabétique du modèle, qui ne dit rien de personne.

## Décision

**Une seule requête, trois voies de correspondance, un classement.**

| Voie | Ce qu'elle rattrape | Coût |
|---|---|---|
| Plein texte par préfixe (`mot:*`) | « minis » → « Ministère » | index GIN existant |
| Sous-chaîne (`LIKE '%…%'`) | « ndjamena » → « N'Djamena » | index trigramme |
| Similarité par mot (`<%`) | « minstere » → « Ministère » | index trigramme |

Quatre choix la soutiennent, et chacun se défend seul :

**`texte_recherche()`, une fonction du socle, aplatit des deux côtés.** Minuscules,
sans accent, sans apostrophe, ponctuation réduite à l'espace. C'est la même
fonction pour la recherche et pour la détection de doublon : comparer autrement
d'un côté que de l'autre produirait le pire des cas — une entrée refusée comme
doublon, introuvable par la recherche.

**La similarité est celle du mot (`<%`), pas de la ligne (`%`).** « minstere »
comparé à « ministere des transports » donne une ressemblance faible : la cible
est longue, et la faute se noie sous les mots qui ne la concernent pas.

**La ville est dans le plein texte, pas dans les trigrammes.** Chercher « Douala »
a un sens ; mais « douanes » ressemble à « Douala » à 0,71, et la Direction
Générale des Douanes passait derrière quatre entreprises doualaises. Un filet à
fautes de frappe ne doit pardonner que sur ce qu'on cherche : un nom.

**Le classement compte autant que le filtre.** Rang plein texte (pesé trois fois,
parce qu'il dit que la frappe est un début correct, là où la similarité ne dit
qu'une ressemblance), plus la similarité, plus un bonus à ce qui *commence* par
la frappe. À égalité, **le nombre de courriers déjà reçus** départage : l'entrée
que l'agent cherche est presque toujours celle qu'il a déjà utilisée vingt fois.

Le seuil `pg_trgm.word_similarity_threshold` passe de 0,6 à **0,5**, posé sur la
base et non par session. « minstere » vaut 0,58 : la faute la plus banale — une
lettre oubliée au milieu d'un mot long — passait juste sous la barre. Une
session qui appliquerait un autre seuil rendrait des résultats différents pour
la même frappe.

## Ce que la décision écarte

**Un moteur externe** — Elasticsearch, Meilisearch, Typesense. À cette
volumétrie, quelques milliers d'entrées, il ajoute un service à exploiter, une
synchronisation à maintenir et une fenêtre d'incohérence, pour un gain nul.
L'index PostgreSQL, lui, est dans la même transaction que la donnée : une entrée
créée est trouvable au commit, pas « bientôt ».

**Le tri alphabétique**, qui ne classe rien : il ordonne.

**Chercher par `icontains`**, qui aurait été sensible aux accents — donc aurait
conduit l'agent à créer un doublon plutôt qu'à retrouver l'entrée existante.

## Conséquences

La requête est écrite en **SQL direct** et non par l'ORM : elle mélange
`tsquery`, `word_similarity()` et une latérale sur `courrier`, table que `noyau`
n'a pas le droit d'importer (la ligne de partage d'`INSTALLED_APPS`). L'écrire en
Django aurait demandé trois annotations et un `RawSQL` au milieu, c'est-à-dire du
SQL déguisé.

Le terme frappé est découpé sur `[^\W_]+` avant d'être composé en `tsquery`. Ce
n'est pas de la cosmétique : une requête `raw` est du langage `tsquery`, et une
parenthèse frappée par l'agent aurait fait répondre 500 à une recherche.

`correspondant.cible_recherche` est une colonne **générée**, donc non déclarée au
modèle : rien en Python ne la lit, et une colonne générée que l'ORM croirait
modifiable serait un piège, pas un service.

## Ce qui reste ouvert

- **Qui saisit le sigle.** La colonne existe et la modale de création l'expose ;
  les entrées du semis n'en ont pas. Un rattrapage sur l'existant relève de
  l'administrateur fonctionnel, et l'écran de paramétrage ne le permet pas
  encore.
- **Les alias.** « MINFI », « Ministère des Finances », « Finances » : le
  troisième ne trouve toujours l'entrée que par le plein texte. Une table
  d'alias serait la suite, si le besoin apparaît.

Voir `noyau/migrations/sql/0020_recherche_correspondant_hybride.sql` et
`noyau/parametrage/lecture_referentiel.py`.

# 046 — Le déploiement mutualisé renonce à trois fonctions, et le dit

*Statut : acceptée — 5 septembre 2026*

## Contexte

Le Port dispose déjà d'un hébergement mutualisé cPanel doté de PostgreSQL.
L'utilisateur a décidé d'y déployer la préproduction plutôt que de servir
l'application depuis un poste de travail (ADR 044) :

> « on va tester une fois sur le tas »

La qualification du serveur n'a pas été faite — le script
`deploiement/qualifier-postgres.sql` existe et répond en deux minutes, mais
la décision est de l'éprouver en conditions réelles. Ni la version de
PostgreSQL, ni la présence des quatre extensions ne sont donc connues au
moment d'écrire.

Trois contraintes de l'hébergement, elles, sont certaines et ne dépendent
d'aucune vérification :

1. **Aucun processus résident.** Ni ouvrier Celery, ni horloge, ni Redis :
   un mutualisé interrompt tout ce qui survit à la requête.
2. **Aucun binaire installable.** LibreOffice, qui convertit le `.docx` en
   PDF (ADR 023), ne peut pas y être posé.
3. **Aucune maîtrise du serveur frontal.** Apache et Passenger servent
   l'application ; le TLS relève du panneau.

Le risque n'était pas de rencontrer ces limites, mais de les rencontrer
*sans les avoir nommées* — une file de notifications qui ne part jamais, un
état qui ne se recalcule plus, un PDF qui rend une page blanche, et
personne pour savoir si c'est une panne ou le mode d'emploi.

## Décision

Le déploiement mutualisé est décrit par un module de réglages propre,
`config/reglages/cpanel.py`, qui **constate ces trois absences au lieu de
les subir**, et par une commande `manage.py traitements` qui exécute les
sept tâches du calendrier depuis l'ordonnanceur du panneau.

Les tâches différées s'exécutent dans la requête qui les demande
(`CELERY_TASK_ALWAYS_EAGER`), avec propagation des erreurs : une tâche qui
échoue doit échouer bruyamment, et non répondre « fait ».

## Conséquences

**Les traitements de nuit dépendent d'une ligne de cron.** Sept tâches, un
ordre qui n'est pas décoratif — les obligations avant les relances, les
agrégats en dernier. `manage.py traitements` le porte, et sort en erreur si
l'une échoue, pour que le panneau envoie son courriel d'alerte. Si cette
ligne n'est pas posée, la panne est **muette** : les écrans répondent, les
saisies passent, et seul le temps cesse de s'écouler.

**Il n'y a plus de PDF.** La route sert le `.docx` et refuse le PDF avec un
message explicite. C'est le comportement déjà prévu par l'ADR 023, désormais
permanent sur cet hébergement.

**Une écriture lente le reste.** Sans ouvrier, ce qui était différé est
maintenant dans la requête. Une cotation qui déclenche des notifications
attend leur traitement. Le contrat de la file — ne jamais faire échouer
l'acte métier à cause d'un envoi — tient toujours, mais son intérêt
disparaît.

**Un second module d'URL existe.** Passenger monte l'application sur `/api`
et lui transmet le chemin amputé de ce préfixe ; `config/urls_cpanel.py`
monte donc l'API à la racine. `config/urls.py` reste intact : le front
continue d'appeler `/api/courriers`, sur tous les hébergements.

**Deux barrières plutôt qu'une sur les pièces jointes.** Le stockage vit
hors de `public_html`, et le `.htaccess` refuse `/media` en 404. L'accès
légitime reste `GET /api/pieces/{uid}/contenu`, qui vérifie le périmètre et
inscrit un accès au journal.

## Ce qui invaliderait cette décision

- **La qualification échoue.** Si PostgreSQL est antérieur à 16 ou si les
  extensions manquent, le schéma ne s'applique pas et rien de ce qui
  précède ne sert.
- **La lenteur des écritures devient sensible.** C'est le symptôme qui dit
  que l'absence d'ouvrier n'est plus tenable.
- **Le PDF devient exigible.** Une note de synthèse qu'on ne peut pas
  produire au format attendu par le Port ferme le débat.
- **Le Port fournit une machine.** L'ADR 044 redevient applicable, avec les
  conteneurs, Celery et LibreOffice.

## Alternatives écartées

**Attendre la qualification.** Proposée, écartée par l'utilisateur, qui
préfère éprouver l'hébergement en conditions réelles. La décision lui
appartient ; le script reste disponible et répond en deux minutes le jour
où l'on veut savoir avant plutôt qu'après.

**Traduire le schéma en MySQL.** Écarté : 3 292 lignes de SQL PostgreSQL,
dont une contrainte d'exclusion GiST qui n'a d'équivalent dans aucun autre
SGBD, dix-huit colonnes `TSVECTOR`, six index GIN, GiST et BRIN, quatorze
fonctions PL/pgSQL. Ce serait une réécriture, pas un portage.

**Émuler l'horloge par une requête HTTP déclenchée par le premier visiteur
du jour.** Écarté : le traitement dépendrait de la présence d'un usager, et
sa durée serait imputée à sa requête.

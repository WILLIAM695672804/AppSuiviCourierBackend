# Décisions d'architecture

Une décision par fichier, numérotée, datée, **jamais modifiée**.

Si une décision devient fausse, on n'y touche pas : on en écrit une nouvelle qui
porte la mention « remplace la 00N ». L'ancienne reste lisible, parce que
quelqu'un voudra un jour savoir pourquoi c'était ainsi — et parce qu'une
décision effacée revient toujours, sous une forme un peu pire.

C'est la même forme que les décisions de cadrage métier D1–D9, dont ces
décisions techniques sont le pendant.

| # | Décision | Statut |
|---|---|---|
| [001](001-django-ninja.md) | django-ninja plutôt que DRF | acceptée |
| [002](002-permissions-hors-django-auth.md) | Permissions et périmètre hors de `django.contrib.auth` | acceptée |
| [003](003-django-proprietaire-du-schema.md) | PostgreSQL propriétaire du schéma, Django suiveur | acceptée |
| [004](004-session-cookie-sans-jeton.md) | Session par cookie, sans jeton | acceptée |
| [005](005-regles-parametrables.md) | Les règles sans source vivent en base, marquées hypothèses | acceptée |
| [006](006-un-seul-engagement.md) | Une seule table d'engagement, trois origines | acceptée |
| [007](007-referentiel-organigramme-sans-perimetre.md) | Le référentiel de l'organigramme se lit sans périmètre | acceptée |
| [008](008-debranchement-du-serveur-de-demonstration.md) | Le serveur de démonstration est débranché | acceptée |
| [009](009-garde-large-contenu-filtre.md) | Un écran d'accueil partagé : garde large, contenu filtré | acceptée |
| [010](010-la-matrice-se-recalcule.md) | La matrice de scoring se recalcule, elle ne se stocke pas | acceptée |
| [011](011-le-pilotage-nomme-ce-qu-il-ne-mesure-pas.md) | Le pilotage rend ce qu'il mesure et nomme ce qu'il ne mesure pas | acceptée |
| [012](012-le-journal-est-l-histoire-du-dossier.md) | Le journal du noyau est l'histoire du dossier | acceptée |
| [013](013-le-portail-ne-passe-pas-par-restreindre.md) | Le portail restreint par déposant, pas par périmètre | acceptée |
| [014](014-la-supervision-mesure-ce-que-le-serveur-traverse.md) | La supervision mesure ce que le serveur traverse, et déclare le reste | acceptée |
| [015](015-l-affectation-a-un-poste-est-datee.md) | L'affectation à un poste est datée | acceptée |
| [016](016-une-hypothese-ne-se-tranche-qu-en-citant-sa-source.md) | Une hypothèse ne se tranche qu'en citant sa source | acceptée |
| [017](017-la-garde-des-pieces-est-portee-par-le-service.md) | La garde des pièces jointes est portée par le service, pas par le décorateur | acceptée |
| [018](018-la-file-existe-avant-les-transports.md) | La file des notifications existe avant ses transports | acceptée |
| [019](019-un-rapport-porte-sur-une-periode-close.md) | Un rapport porte sur une période close | acceptée |
| [020](020-on-designe-un-agent-par-son-identifiant.md) | On désigne un agent par son identifiant, choisi dans un annuaire | acceptée |
| [021](021-l-organigramme-tient-sous-une-seule-permission.md) | L'organigramme tient sous une seule permission | acceptée |
| [022](022-le-registre-est-une-porte-de-visibilite.md) | Le registre est une porte de visibilité | acceptée |
| [023](023-le-document-est-ecrit-pas-capture.md) | Le document est écrit, pas capturé | acceptée |
| [024](024-la-serrure-du-confidentiel-ne-ferme-pas-son-propre-registre.md) | La serrure du confidentiel ne ferme pas son propre registre | acceptée |
| [025](025-l-organigramme-reel-se-charge-il-ne-se-migre-pas.md) | L'organigramme réel se charge, il ne se migre pas | acceptée |
| [026](026-la-vue-du-comite-situe-le-membre-elle-ne-classe-plus.md) | La vue du Comité situe le membre, elle ne classe plus | acceptée |
| [027](027-le-poste-de-direction-navigue-par-ce-qu-il-regarde.md) | Le poste de direction navigue par ce qu'il regarde | acceptée |
| [028](028-une-liste-de-structures-se-cherche-elle-ne-se-parcourt-pas.md) | Une liste de structures se cherche, elle ne se parcourt pas | acceptée |
| [029](029-la-cle-de-lecture-se-trouve-toujours-au-meme-endroit.md) | La clé de lecture se trouve toujours au même endroit | acceptée |
| [030](030-le-taux-declare-et-le-taux-retenu-sont-deux-choses.md) | Le taux déclaré et le taux retenu sont deux choses | acceptée ; recalibrage descendu à la tâche par 049 |
| [031](031-l-entree-en-structure-se-pose-a-la-cotation.md) | L'entrée en structure se pose à la cotation, elle ne se saisit pas | acceptée |
| [032](032-un-evenement-appartient-a-une-structure-ou-a-personne.md) | Un événement appartient à une structure, ou à personne | acceptée |
| [033](033-le-routage-direct-ne-se-replie-sur-rien.md) | Le routage direct ne se replie sur rien | acceptée |
| [034](034-le-trajet-du-courrier-n-est-pas-un-circuit.md) | Le trajet du courrier n'est pas un circuit paramétrable | acceptée |
| [035](035-l-agent-cote-signe-avant-de-traiter.md) | L'agent coté signe avant de traiter | acceptée |
| [036](036-le-traitement-et-la-cloture-ferment-le-trajet.md) | Le traitement et la clôture ferment le trajet | acceptée |
| [037](037-la-date-de-cloture-se-lit-sur-le-courrier.md) | La date de clôture se lit sur le courrier | acceptée |
| [038](038-la-recherche-du-carnet-est-hybride.md) | La recherche du carnet d'adresses est hybride, et classée | acceptée |
| [039](039-le-cabinet-cote-au-nom-du-directeur-general.md) | Le cabinet cote au nom du Directeur général | acceptée |
| [040](040-la-file-d-affectation-est-un-onglet-du-registre.md) | La file d'affectation est un onglet du registre | acceptée |
| [041](041-les-profils-livres-se-modifient.md) | Les profils livrés se modifient, mais ne sortent pas du catalogue | acceptée |
| [042](042-la-note-de-travail-est-une-table-a-part.md) | La note de travail est une table à part, distincte du fil d'observations | acceptée |
| [043](043-la-tete-de-structure-consolide-elle-n-ouvre-rien.md) | La tête de structure consolide l'affichage, elle n'ouvre aucun accès | acceptée |
| [044](044-la-preproduction-est-servie-depuis-un-poste-par-un-tunnel.md) | La préproduction est servie depuis un poste de travail, par un tunnel sortant | acceptée, amendée par 045 |
| [045](045-la-preproduction-se-publie-par-tailscale-funnel.md) | La préproduction se publie par Tailscale Funnel, faute de nom de domaine | acceptée |
| [046](046-le-deploiement-mutualise-renonce-a-trois-fonctions.md) | Le déploiement mutualisé renonce à trois fonctions, et le dit | acceptée, sans objet depuis la qualification du 5 septembre 2026 |
| [047](047-l-activite-est-portee-par-des-structures.md) | L'activité est portée par des structures, pas par un agent | acceptée |
| [048](048-la-tache-n-a-pas-d-attributaire.md) | La tâche à réaliser n'a pas d'attributaire | acceptée ; poids et échéance remplacés par 049 |
| [049](049-l-avancement-d-une-activite-est-la-somme-de-ses-taches.md) | L'avancement d'une activité est la somme de ses tâches | acceptée |

## Écrire une décision

Cinq sections, dans cet ordre, et rien de plus :

**Contexte** — ce qui était vrai au moment de décider, sans anticiper la suite.
**Décision** — au présent, à la voix active, en une phrase si possible.
**Conséquences** — ce que cela impose, y compris ce que cela coûte.
**Ce qui invaliderait cette décision** — la section qui manque partout ailleurs.
Un fait futur qui, s'il survient, oblige à réexaminer. Sans elle, une décision
survit à ses raisons.
**Alternatives écartées** — et pourquoi. Faute de quoi elles seront reproposées
tous les six mois.

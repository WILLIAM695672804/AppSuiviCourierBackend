# 018 — La file des notifications existe avant ses transports

*Statut : acceptée — 14 août 2026*

## Contexte

RF-SUI-03 promet à l'usager des « notifications multicanal (courriel, SMS,
portail) ». L'écran de préférences du portail les propose depuis le premier
jour. Et l'état des intégrations dit, dans le même dépôt, que la messagerie
institutionnelle est « Non connecté » et la passerelle SMS aussi : ni serveur
SMTP, ni adresse d'expédition, ni passerelle ne sont arrêtés.

Trois voies s'ouvraient. Attendre l'infrastructure et ne rien écrire — l'usager
continue de régler un canal qui n'existe pas. Écrire un envoi direct dans la
requête métier — une panne de messagerie ferait alors échouer la cotation qui
l'a déclenchée. Ou écrire la file maintenant, et la laisser dire ce qu'elle ne
peut pas faire.

## Décision

Le pilier de notification est livré **en entier**, transports compris, et
chaque transport déclare s'il est branché. Un envoi qu'aucun transport ne peut
prendre passe en `sans_transport`, avec sa raison — pas en `echoue`.

La notification **interne** est créée dans tous les cas, quelles que soient les
préférences et quel que soit l'état du réseau. Elle n'a pas de ligne d'envoi :
elle est la notification elle-même.

L'envoi par courriel est écrit et **coupé par une règle en base**
(`notifications.courriel_actif`, hypothèse A51). Le SMS n'a pas de transport du
tout.

La file se dépile par la commande `envoyer_notifications`, appelée par un
ordonnanceur — jamais depuis la requête qui a produit la notification.

## Pourquoi

**`sans_transport` n'est pas un échec, et les confondre coûte deux fois.** Un
échec se rejoue : la file battrait indéfiniment contre un mur qui ne bougera pas
avant une décision d'infrastructure. Et l'écran d'exploitation ferait chercher
un incident là où il n'y a qu'un arbitrage en attente.

**La notification interne est le filet.** Elle rend la panne de messagerie
gênante au lieu de la rendre destructrice : le destinataire est prévenu dans
l'application, et la trace existe. Une file qui n'aurait que des canaux sortants
perdrait l'information dès que le réseau tombe.

**Le courriel est coupé, pas absent.** Tant que la politique n'est pas arrêtée,
un environnement de recette qui écrit à de vraies adresses d'agents est un
incident, pas un essai. Coupé par une règle plutôt que par du code : trancher
A51 est alors un geste d'administration tracé, pas une livraison.

## Conséquences

- Deux tables. `notification` est le message et ne dépend d'aucun réseau ;
  `envoi_notification` est la tentative de sortie, avec son état, ses tentatives
  et son erreur. Une seule table aurait fait dépendre la lecture d'un serveur
  SMTP.
- `session_seule` compte un **cinquième** usage : une notification est adressée
  à une personne, et il n'existe pas de permission « lire ce qui m'est
  adressé ». En créer une serait pouvoir la retirer à quelqu'un.
- Aucun événement n'est inscrit au journal du noyau pour une notification :
  c'est un effet d'un acte déjà journalisé, et l'histoire du dossier (ADR 012)
  n'a pas à porter ses propres échos. La table des envois est le journal des
  sorties.
- La carte d'exploitation vit sous les intégrations, et non dans un écran à
  elle : « Messagerie : non connecté » et « 14 notifications sans transport »
  sont la même phrase, dite deux fois.

## Ce qui invaliderait cette décision

- Le jour où la DSI fournit un serveur SMTP et une adresse d'expédition, A51 se
  tranche et le transport courriel s'ouvre sans livraison. Si à ce moment-là le
  volume dépasse ce qu'une commande périodique absorbe, la file devra passer à
  un courtier (Celery est déjà présent) — et cet ADR devra le dire.
- Si l'institution choisissait une plateforme de notification externe qui tient
  elle-même la file et les états, ces deux tables deviendraient un doublon de
  son tableau de bord.

## Alternatives écartées

**Envoyer dans la requête, avec `transaction.on_commit`.** Un serveur de
messagerie lent rendrait lente la route qui cote un courrier, et une panne SMTP
ferait remonter une erreur sur un acte qui, lui, a réussi.

**Ne pas écrire les transports du tout, et poser un `TODO`.** L'écran de
préférences promettrait alors un canal que rien n'implémente, sans qu'aucune
page ne dise ce qui manque. C'est exactement le trompe-l'œil que le dépôt
s'interdit ailleurs.

**Marquer les envois non branchés comme `echoue` pour n'avoir que trois
états.** Un état de moins, et la perte de la seule distinction utile : ce qui se
répare tout seul contre ce qui attend une décision.

## Voir aussi

- [012](012-le-journal-est-l-histoire-du-dossier.md) — pourquoi une notification
  n'entre pas au journal des événements.
- [013](013-le-portail-ne-passe-pas-par-restreindre.md) — le même principe de
  filtre par personne plutôt que par périmètre.
- [005](005-regles-parametrables.md) — pourquoi la coupure du courriel vit en
  base et non dans le code.
- `docs/questions-ouvertes.md`, A48 et A51.

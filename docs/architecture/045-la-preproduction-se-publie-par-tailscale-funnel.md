# 045 — La préproduction se publie par Tailscale Funnel, faute de nom de domaine

*Statut : acceptée — 5 septembre 2026*
*Amende l'[ADR 044](044-la-preproduction-est-servie-depuis-un-poste-par-un-tunnel.md) sur le seul point de la publication.*

## Contexte

L'ADR 044 retient un tunnel sortant Cloudflare pour publier la
préproduction. Ce montage suppose un **nom de domaine confié à
Cloudflare** : le tunnel ne publie que sur une zone présente dans le compte.

L'utilisateur a posé une contrainte que l'ADR 044 n'avait pas :

> « j'ai besoin de la méthode la plus stable et totalement gratuite »

Or un domaine coûte une dizaine d'euros l'an. Les voies gratuites ont été
examinées :

- **Les domaines gratuits historiques** (`.tk`, `.ml`, `.ga`) n'existent
  plus : leur registre a cessé les enregistrements gratuits en 2023.
- **Les sous-domaines dynamiques** (DuckDNS, No-IP) ne peuvent pas être
  déclarés comme zone Cloudflare : la délégation des serveurs de noms n'y
  est pas possible. Ils sont donc incompatibles avec un tunnel nommé.
- **`.eu.org`** donne un sous-domaine gratuit, permanent, et délégable à
  Cloudflare. C'est la seule voie qui combine gratuité et nom présentable —
  mais son approbation est manuelle et prend de quelques jours à quelques
  semaines. Elle ne débloque pas la recette aujourd'hui.
- **Le tunnel éphémère `trycloudflare.com`** ne demande rien, mais son
  adresse **change à chaque redémarrage**. Pour un environnement que des
  agents du Port doivent retrouver chaque matin, c'est disqualifiant.
- **Le domaine statique gratuit d'ngrok** impose une page d'avertissement
  avant chaque première visite, et plafonne à un gigaoctet mensuel.

## Décision

La préproduction se publie par **Tailscale Funnel**, installé **sur
l'hôte** et non en conteneur, sur le nom stable que Tailscale attribue au
poste, en `<machine>.<tailnet>.ts.net`.

Gratuit sur le plan Personal, certificat Let's Encrypt obtenu et renouvelé
sans intervention, connexion sortante — donc insensible au partage
d'adresse de l'opérateur —, et **le nom ne change pas** d'un redémarrage à
l'autre. C'est la seule des voies examinées à réunir les deux exigences.

Sur l'hôte plutôt qu'en conteneur : Funnel réclame `/dev/net/tun` et la
capacité `NET_ADMIN`, et un conteneur privilégié pour publier une recette
est un mauvais échange. Le service de l'hôte se relève au démarrage, comme
les conteneurs.

## Conséquences

**Le service `tunnel` du compose ne démarre plus.** Il est retenu par le
profil `cloudflare` et attend son domaine. Le reste du fichier est
inchangé : la bascule sera d'un mot.

**L'adresse n'est pas présentable.** `suivi.tailXXXXX.ts.net` se dicte mal
au téléphone et ne ressemble à rien d'institutionnel. Pour une recette
interne dont le lien s'envoie par écrit, c'est un inconvénient, pas un
obstacle.

**La bande passante est bridée**, à une valeur que Tailscale ne publie pas.
Le trafic transite par ses relais, sans connexion directe possible — le
navigateur d'un agent du Port n'a pas Tailscale. Sur des pièces jointes
plafonnées à 25 Mo, cela devrait tenir ; c'est à surveiller, et c'est le
premier symptôme qui justifierait de repasser à Cloudflare.

**Une dépendance de plus à un tiers.** Le trafic est déchiffré chez
Tailscale comme il l'aurait été chez Cloudflare : l'écart à `RNF-SOUV-01`
constaté par l'ADR 044 est inchangé, ni aggravé ni réduit.

**La demande d'un `.eu.org` doit partir en parallèle.** Son délai est la
seule raison de ne pas l'avoir retenu ; obtenu, il rend le montage
Cloudflare gratuit, et l'adresse redevient présentable.

## Ce qui invaliderait cette décision

- **Un nom de domaine devient disponible** — acheté, obtenu en `.eu.org`,
  ou délégué par la DSI du Port. Le profil `cloudflare` reprend alors la
  main.
- **Le débit devient le premier motif de plainte.** Les relais Tailscale
  sont le maillon lent ; Cloudflare ne l'est pas.
- **Tailscale restreint Funnel sur le plan gratuit.** La fonction est
  offerte, pas contractuelle.

## Alternatives écartées

Voir le contexte : chacune l'a été pour une raison précise — registre
fermé, délégation impossible, délai d'approbation, adresse changeante,
page d'avertissement et quota. Aucune ne réunit stabilité et gratuité.

**Le HTTP en clair sur un simple renvoi de port** reste écarté pour la
raison de l'ADR 044 : les agents s'authentifient avec leurs identifiants
réels.

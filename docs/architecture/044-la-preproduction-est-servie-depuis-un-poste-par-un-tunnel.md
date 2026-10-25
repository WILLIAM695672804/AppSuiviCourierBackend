# 044 — La préproduction est servie depuis un poste de travail, par un tunnel sortant

*Statut : acceptée — 4 septembre 2026*

## Contexte

Le Port doit éprouver la plateforme sur des **données réelles** avant toute
mise en service : les jeux d'essai montrent que le code fonctionne, ils ne
montrent pas comment une organisation s'en sert. Il fallait donc un
environnement accessible aux agents du Port, alimenté par eux, et durable
sur plusieurs semaines.

Trois cibles ont été examinées dans l'ordre où elles se sont présentées.

**Un hébergement mutualisé cPanel** a été écarté d'emblée : six dépendances
du socle y sont hors de portée. PostgreSQL 16 — les offres mutualisées
servent MySQL —, les quatre extensions `pgcrypto`, `btree_gist`, `pg_trgm`
et `unaccent` dont la création exige le superutilisateur, les deux démons
Celery qu'un mutualisé interrompt, Redis qui n'y est pas fourni, le binaire
LibreOffice qu'on ne peut y installer (ADR 023), et Python 3.12 que
l'hébergeur fige. Le schéma est écrit en SQL PostgreSQL (ADR 003) : il ne se
transpose pas.

**Un VPS** répondait techniquement — la configuration examinée offrait 2
cœurs, 4 Go et 128 Go de NVMe, ce qui suffit au socle moyennant des brides
sur Gunicorn, Celery et LibreOffice. Il plaçait cependant les courriers
réels du Port chez un hébergeur étranger.

**Le poste de travail du développeur** a été retenu. Il offre 16 cœurs et
13 Go, davantage que le VPS, et ne demande aucune location. Mais il est
situé à domicile, derrière une connexion grand public, tandis que les
testeurs sont au Port : l'accès n'est donc pas local, il traverse Internet.

Or une connexion domestique n'a ni adresse stable, ni port entrant garanti —
le partage d'adresse pratiqué par les opérateurs interdit toute redirection.
Un environnement qui, de surcroît, porte de vraies identités et de vrais
mots de passe d'agents ne peut pas être servi en clair.

## Décision

La préproduction tourne **entièrement en conteneurs** sur le poste du
développeur, décrite par `compose.preprod.yaml`, et se publie par un
**tunnel sortant Cloudflare** : aucun port n'est ouvert sur la box, le
certificat est valide sans intervention sur les postes du Port, et
l'adresse dynamique de la ligne cesse d'avoir de l'importance.

Le durcissement de `config/reglages/preprod.py` est celui de la production.
Cet environnement porte les mêmes données : il porte les mêmes règles.

## Conséquences

**Le travail de déploiement n'est pas jetable.** Le `Dockerfile`, le
`compose`, la configuration Nginx et le script de sauvegarde sont ceux qui
serviront sur la machine du Port. Seuls changeront la publication — le
tunnel disparaîtra au profit du réseau interne — et l'emplacement des
sauvegardes.

**La souveraineté n'est pas satisfaite.** `RNF-SOUV-01` veut que les
données ne quittent pas le périmètre de l'institution ; elles résident ici
sur une machine privée et leur chiffrement est terminé chez Cloudflare, qui
voit donc le trafic en clair. C'est un écart **assumé, borné et
temporaire** : il vaut pour la durée de la recette, et la bascule sur site
en est la sortie. Sa contrepartie minimale est écrite dans le runbook —
sauvegardes sorties de la machine, jeton de tunnel traité comme un secret,
suppression de l'environnement à la bascule.

**La disponibilité dépend d'un poste de travail.** Une veille, une coupure
de courant, une mise à jour qui redémarre, et l'application disparaît pour
le Port sans que personne ne sache pourquoi. Les conteneurs se relèvent
seuls (`restart: unless-stopped`), la machine non.

**Le débit montant de la ligne devient celui de l'application.** Une pièce
jointe consultée à Douala remonte par ce lien, toujours le plus étroit
d'une connexion domestique.

**Les pièces jointes ne sont pas servies par Nginx.** `/media` répond 404.
Le seul accès reste `GET /api/pieces/{uid}/contenu`, qui vérifie le
périmètre et inscrit un accès au journal (RNF-TRACE-01). Exposer le volume
aurait contourné les deux d'un seul réglage.

## Ce qui invaliderait cette décision

- **Le Port fournit une machine.** C'est la sortie prévue : le même
  `compose` s'y applique, le tunnel s'efface, `RNF-SOUV-01` est satisfait.
- **La recette dure au-delà de quelques semaines.** L'écart de souveraineté
  a été accepté comme temporaire ; s'il s'installe, il doit être réexaminé
  et non reconduit par habitude.
- **Le volume des pièces sature la ligne montante.** Si les téléchargements
  deviennent le premier motif de plainte, l'hébergement doit se rapprocher
  des usagers.
- **Les données saisies deviennent la référence du Port.** Le jour où
  personne ne peut plus les perdre, l'environnement n'est plus une
  préproduction : il faut alors la disponibilité d'une machine dédiée.

## Alternatives écartées

**L'hébergement mutualisé cPanel.** Techniquement impossible, pour les six
raisons ci-dessus. Aucune n'est contournable par un réglage.

**Le VPS.** Meilleur sur la disponibilité et le débit, et il reste la
seconde cible si le poste ne tient pas. Écarté parce qu'il déplace les
données chez un tiers sans rien résoudre de la souveraineté, tout en
ajoutant un coût récurrent à un environnement temporaire.

**La redirection de port sur la box, avec nom dynamique et Let's Encrypt.**
C'est l'option la plus proche de `RNF-SOUV-01` : aucun tiers dans le trajet
des données. Écartée parce qu'elle suppose une adresse publique véritable,
que rien ne garantit chez un opérateur grand public, et qu'elle expose
directement le réseau domestique du développeur.

**Un réseau privé virtuel avec client sur chaque poste testeur.** Écarté
parce qu'il demande une installation sur des machines administrées par la
DSI du Port, ce qui transforme une recette en projet d'infrastructure.

**Le HTTP en clair.** Écarté sans discussion : les agents s'authentifient
avec leurs identifiants réels.

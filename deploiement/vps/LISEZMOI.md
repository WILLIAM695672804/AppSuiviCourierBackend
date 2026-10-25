# Mise en ligne sur le VPS Netcup, à côté de SASI

Publie la plateforme sur `https://suivicourier.the7ing.site`, derrière le
frontal Caddy que la machine partage déjà avec SASI.

La préproduction du Latitude **reste debout** pendant toute l'opération.
Elle est le seul retour possible, et on ne l'arrête qu'après un essai
réussi depuis un téléphone en 4G.

## Les trois scripts, dans l'ordre

| | Où | Quoi |
|---|---|---|
| `1-mesurer.sh` | VPS | Mesure. Ne modifie rien. |
| `2-preparer-paquet.sh` | Latitude | Assemble `~/paquet-vps-suivicourier/`. |
| `3-installer.sh` | VPS | Construit, restaure, démarre, vérifie. |

Puis deux commandes à la main, qui touchent le frontal.

```
# Sur le Latitude
bash backend/deploiement/vps/2-preparer-paquet.sh

rsync -az --delete \
  ~/paquet-vps-suivicourier/ \
  root@152.53.116.238:/root/suivicourier/

# Sur le VPS
ssh root@152.53.116.238
cd /root/suivicourier
bash 1-mesurer.sh
bash 3-installer.sh
```

`3-installer.sh` s'arrête **avant** de publier et affiche les deux
commandes restantes. Il est relançable : il ne refait pas le `.env` et ne
restaure pas une base déjà peuplée.

## Pourquoi le front est bâti sur le Latitude

Le `dist` de Vite ne dépend d'aucune architecture. Le bâtir ici, où la
mémoire est abondante, puis ne transférer que le résultat, évite un
`npm ci` de 400 Mo et un `vite build` de 1,5 Gio sur un VPS à 2 vCore
dont SASI occupe déjà la moitié de la mémoire.

Conséquence : **ce qui part en ligne est le bundle construit sur le
poste.** `2-preparer-paquet.sh` le reconstruit systématiquement pour
cette raison — un `dist` laissé dans l'arbre date de la dernière
construction, et rien ne le dit. Le 25 octobre, celui de l'arbre portait
`index-BnehCBmp.js` quand la préproduction servait `index-CPQ3eoK0.js`.

## Le budget mémoire

La machine a 3,8 Gio et 2 Gio d'échange. SASI y tient sept conteneurs
dont une TimescaleDB. Les plafonds de `compose.vps.yaml` somment à
**exactement 2 Gio** :

```
web      704 Mio    (2 ouvriers × 3 fils)
ouvrier  576 Mio    (concurrence 1 — LibreOffice demande ~500 Mio)
base     448 Mio    (shared_buffers 112 Mo, max_connections 20)
horloge  160 Mio
file      96 Mio    (maxmemory 64 Mo)
proxy     64 Mio
```

La consommation réelle mesurée sur le Latitude est de **544 Mio** au
repos, les six services réunis. Les plafonds ne réservent rien : ils
bornent le pic. Mais si `1-mesurer.sh` montre que SASI dépasse 1,8 Gio,
réduisez-les **avant** le premier démarrage, et non après le premier
`oom-kill` — qui frappe le plus gros processus de la machine, c'est-à-dire
la base de l'autre application.

## Le cloisonnement

Deux réseaux. `interne` porte le trafic de la plateforme ; seul `proxy`
rejoint `frontal`, sous l'alias `suivicourier-proxy`. La base et le
courtier restent donc hors de portée de SASI, qui partage ce frontal.

Aucun `ports:` dans la composition — vérifié par `docker compose config`.
`ufw` n'a rien à ouvrir.

## Ce qui n'a pas été vérifié par exécution réelle

Tout ce qui suit est raisonné, non exécuté. La mise en service de SASI a
révélé trois pannes qu'aucun test ne pouvait voir : voici où celles-ci se
cacheraient.

1. **L'image applicative n'a jamais été construite en ARM64.**
   `libreoffice-writer` existe en `arm64` chez Debian, `psycopg[binary]`
   et `lxml` publient des roues `manylinux_aarch64` — vérifié par
   catalogue, pas par `docker build`. C'est le risque principal, et il se
   lèvera à l'étape 3 du script, en cinq à dix minutes.
2. **Le fichier `.caddy` n'a pas été comparé à
   `exemple-seconde-app.caddy.modele`**, que je n'ai pas sous les yeux.
   Si le modèle impose une forme (un `import`, un bloc d'en-têtes
   communs), la mienne est à aligner. Caddy refuse un fichier invalide
   **en gardant l'ancienne configuration** : l'erreur est bénigne.
3. **La directive `request_body { max_size 30MB }`** suppose Caddy v2.
   À vérifier contre la version installée.
4. **Le réseau `frontal` et la liberté de l'alias** : `1-mesurer.sh` et
   `3-installer.sh` les contrôlent, je ne l'ai pas fait.
5. **`pg_restore` d'un dump produit par PostgreSQL 16 `amd64` vers
   PostgreSQL 16 `arm64`.** Le format `-Fc` est indépendant de
   l'architecture ; la lecture réelle reste à faire.
6. **`wget --spider` de busybox** dans `nginx:alpine` et `alpine:3.20`.
   Son `wget` n'a pas d'option `-S` : les vérifications ne lisent qu'un
   succès ou un échec, jamais un code HTTP. Le test de Django, lui, passe
   par Python et rend un vrai code.
7. **Le transfert par `rsync`.** Ce projet **n'est pas un dépôt Git** —
   `git status` le confirme encore le 25 octobre. Le dépôt public dont
   parle le contexte du serveur est celui de SASI. Il n'y a donc rien à
   cloner : le code passe par `rsync`, et le `.env` est engendré sur
   place, jamais transféré.

En revanche, **la résolution du domaine est vérifiée** :
`suivicourier.the7ing.site` → `152.53.116.238`, mesuré le 25 octobre.

## Les pièges de la machine, et ce qu'ils ont imposé

| Piège | Ce que les fichiers en font |
|---|---|
| Le terminal indente les collages et coupe les lignes longues | Tout passe par des scripts transférés, aucune ligne à coller ne dépasse 70 caractères |
| `read` consomme la ligne suivante du collage | Aucun `read` : le `.env` est engendré, jamais saisi |
| `openssl rand -base64` glisse un `/` dans une URL | `-hex 24` pour le mot de passe, `-hex 48` pour `SECRET_KEY` |
| Une valeur à `$` arrive tronquée dans `.env` | Aucune valeur engendrée ne contient de `$` : hexadécimal pur |
| `${VARIABLE:?}` échoue aussi sur une valeur vide | **Aucune** interpolation `${...}` dans `compose.vps.yaml` |
| `python:*-slim` n'a pas `libgomp1` | Sans objet : aucune dépendance OpenMP (ni NumPy, ni SciPy, ni Pillow) |
| Deux images partageant un volume doivent avoir le même UID | `web`, `ouvrier` et `horloge` sortent de la **même** image, UID 1000 (`useradd --uid 1000 suivi`) ; `proxy` ne partage aucun volume |
| `localhost` dans un conteneur le désigne lui-même | `DATABASE_URL` pointe sur `base`, `REDIS_URL` sur `file`, Caddy sur `suivicourier-proxy` — des noms de service, résolus par Docker |

## Après la mise en service

- La sauvegarde : `deploiement/sauvegarder.sh` suppose le projet
  `suivi-preprod`. Sur le VPS, le projet s'appelle `suivicourier` — le
  script est à adapter, et son timer `systemd` à réinstaller. **Non fait.**
- Un instantané Netcup, **juste après l'installation réussie et avant
  d'ouvrir aux testeurs**. Une préproduction se casse, par définition.
- Ni `dg` ni `dsr` ne portent `ENR` ou `ACT_SAI` : ils ne saisissent pas.

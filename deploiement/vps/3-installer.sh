#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  A LANCER SUR LE VPS, depuis /root/suivicourier/, apres 1-mesurer.sh.
#
#      bash 3-installer.sh
#
#  IL NE TOUCHE PAS AU FRONTAL. Il construit, restaure, demarre et
#  verifie la plateforme sur le reseau `frontal` sans y publier le
#  moindre port ; puis il s'arrete et affiche les commandes qui publient
#  le domaine, a lancer a la main. Cette separation est deliberee : un
#  rechargement de Caddy est anodin, un redemarrage interrompt l'autre
#  application, et la difference tient a un mot.
#
#  Relancable sans dommage : il ne reecrit pas le `.env` s'il existe, et
#  ne restaure la base que si elle est vide.
# ---------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
COMPOSE="docker compose -f compose.vps.yaml"

arret() { echo; echo "ARRET : $1"; exit 1; }

# ---------------------------------------------------------------------
#  1. Preconditions. Chacune a deja coute une mise en service ailleurs.
# ---------------------------------------------------------------------
echo "== 1/7  Preconditions =="

[ "$(uname -m)" = "aarch64" ] \
    || arret "architecture $(uname -m), attendue aarch64"
echo "  architecture aarch64"

docker network inspect frontal >/dev/null 2>&1 \
    || arret "le reseau Docker « frontal » n'existe pas"
echo "  reseau frontal present"

if docker network inspect frontal | grep -q "suivicourier-proxy"; then
    arret "l'alias « suivicourier-proxy » est deja pris sur frontal"
fi
echo "  alias suivicourier-proxy libre"

for f in compose.vps.yaml base.dump controle.txt env.vps.modele \
         backend/Dockerfile front/Dockerfile.front front/dist/index.html; do
    [ -e "$f" ] || arret "fichier manquant : $f"
done
echo "  paquet complet"

libre=$(free -m | awk '/^Mem:/ {print $7}')
echo "  memoire disponible : ${libre} Mio"
if [ "$libre" -lt 1200 ]; then
    echo "  AVERTISSEMENT : moins de 1,2 Gio libre. Les plafonds de"
    echo "  compose.vps.yaml somment a 2 Gio ; l'echange absorbera le"
    echo "  depassement, au prix de la vitesse."
fi
echo

# ---------------------------------------------------------------------
#  2. Le fichier d'environnement.
#
#     `openssl rand -hex` et non `-base64` : un « / » dans le mot de
#     passe casse l'URL de connexion une fois sur deux, et la panne se
#     lit « role does not exist » plutot que « mot de passe ».
#
#     Aucune valeur engendree ne contient de « $ » ni d'espace : rien a
#     proteger par des guillemets, rien que Compose puisse tronquer en
#     silence.
# ---------------------------------------------------------------------
echo "== 2/7  Fichier .env =="
if [ -f .env ]; then
    echo "  deja present, conserve — le refaire changerait le mot de"
    echo "  passe de la base, que le volume a deja enregistre"
else
    mot=$(openssl rand -hex 24)
    cle=$(openssl rand -hex 48)
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$cle|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$mot|" \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=postgres://suivi:$mot@base:5432/suivi|" \
        env.vps.modele > .env
    chmod 600 .env
    if grep -q "A_ENGENDRER" .env; then
        arret "une valeur est restee a A_ENGENDRER dans .env"
    fi
    echo "  engendre, droits 600"
fi
echo

# ---------------------------------------------------------------------
#  3. Construction. Pas de Node : le `dist` est deja bati.
# ---------------------------------------------------------------------
echo "== 3/7  Construction des images =="
echo "  l'image applicative installe LibreOffice Writer : comptez cinq"
echo "  a dix minutes sur 2 vCore."
$COMPOSE build
echo

# ---------------------------------------------------------------------
#  4. La base seule, puis la restauration. Dans cet ordre : le service
#     `web` applique les migrations a son demarrage, et des migrations
#     posees sur une base vide se heurteraient ensuite au dump.
# ---------------------------------------------------------------------
echo "== 4/7  Base de donnees =="
$COMPOSE up -d base
etat=""
for _ in $(seq 1 30); do
    etat=$($COMPOSE ps base --format '{{.Health}}' 2>/dev/null || echo "")
    [ "$etat" = "healthy" ] && break
    sleep 2
done
[ "$etat" = "healthy" ] || arret "la base n'est pas devenue saine"
echo "  base saine"

tables=$($COMPOSE exec -T base psql -U suivi -d suivi -At \
    -c "select count(*) from pg_tables where schemaname='public'")
if [ "$tables" -gt 5 ]; then
    echo "  deja peuplee ($tables tables), restauration ignoree"
else
    echo "  restauration du dump"
    # `--clean --if-exists` : rejouable. Sur une base vide, les ordres
    # de suppression sont sans objet et restent silencieux.
    $COMPOSE exec -T base pg_restore -U suivi -d suivi \
        --clean --if-exists --no-owner < base.dump \
        2> restauration.log || true
    graves=$(grep -c "^pg_restore: error" restauration.log 2>/dev/null || true)
    echo "  erreurs graves : ${graves:-0}   (detail : restauration.log)"
fi
echo

# ---------------------------------------------------------------------
#  5. Les pieces jointes. Le chemin d'une piece est derive de son
#     empreinte : les binaires doivent retrouver la meme racine.
# ---------------------------------------------------------------------
echo "== 5/7  Pieces jointes =="
if [ -s pieces.tar.gz ]; then
    $COMPOSE up -d web >/dev/null
    sleep 8
    if $COMPOSE exec -T web tar -xzf - -C /app/media < pieces.tar.gz; then
        echo "  extraites"
    else
        echo "  ECHEC de l'extraction — a reprendre a la main"
    fi
else
    echo "  archive vide : aucune piece a reprendre"
fi
echo

# ---------------------------------------------------------------------
#  6. Tout le reste.
# ---------------------------------------------------------------------
echo "== 6/7  Demarrage =="
$COMPOSE up -d
sleep 12
$COMPOSE ps --format '  {{.Service}}  {{.State}}  {{.Health}}'
echo

# ---------------------------------------------------------------------
#  7. Verification. Rien n'est publie : on interroge depuis l'interieur.
# ---------------------------------------------------------------------
echo "== 7/7  Verification =="

$COMPOSE exec -T base psql -U suivi -d suivi -At -c "
  select 'activites '    || count(*) from activite
  union all select 'taches '       || count(*) from tache
  union all select 'indicateurs '  || count(*) from activite_indicateur
  union all select 'utilisateurs ' || count(*) from utilisateur
  union all select 'courriers '    || count(*) from courrier
  union all select 'plans '        || count(*) from paa
" > obtenu.txt

echo "  comparaison au releve du poste de travail :"
while read -r ligne; do
    cle=${ligne%% *}
    att=${ligne##* }
    case "$cle" in
        activites|taches|indicateurs|utilisateurs|courriers|plans) ;;
        *) continue ;;
    esac
    obt=$(awk -v c="$cle" '$1==c {print $2}' obtenu.txt)
    if [ "$att" = "$obt" ]; then
        echo "    OK     $cle $obt"
    else
        echo "    ECART  $cle : attendu $att, obtenu ${obt:-rien}"
    fi
done < controle.txt

# Nginx sert-il le front ? Le `wget` de busybox ne sait pas rendre le
# code HTTP (pas d'option `-S`) : on n'en tire qu'un succes ou un echec,
# ce qui suffit a distinguer « sert » de « ne sert pas ».
if $COMPOSE exec -T proxy wget -q --spider http://127.0.0.1/ 2>/dev/null
then echo "  nginx sert le front : OK"
else echo "  nginx sert le front : ECHEC"
fi

# Django repond-il ? L'en-tete `X-Forwarded-Proto: https` est
# indispensable : sans lui, `SECURE_SSL_REDIRECT` rend un 301 vers HTTPS
# et la mesure ne dit plus rien de l'application. Python est dans
# l'image applicative, et lui sait lire un code de retour.
code=$($COMPOSE exec -T web python -c 'import urllib.request as u; r=u.Request("http://127.0.0.1:8000/api/docs", headers={"X-Forwarded-Proto":"https"}); print(u.urlopen(r, timeout=10).status)' 2>/dev/null || echo "")
echo "  django repond : ${code:-ECHEC}   (200 attendu)"

# L'alias est-il joignable depuis le reseau du frontal ? C'est
# exactement ce que Caddy fera. Conteneur jetable de 8 Mio, qui ne
# touche a rien et disparait.
if docker run --rm --network frontal alpine:3.20 \
    wget -q --spider http://suivicourier-proxy/ 2>/dev/null
then echo "  alias depuis frontal : OK"
else echo "  alias depuis frontal : ECHEC — Caddy rendrait 502"
fi
echo

# ---------------------------------------------------------------------
#  Fin. Ce qui suit touche le frontal : a vous de le lancer.
# ---------------------------------------------------------------------
cat <<'RESTE'
== La plateforme tourne, et n'est pas encore publiee ==

Ce qui reste touche le frontal partage. Si une ligne ci-dessus porte
ECHEC ou ECART, corrigez-la d'abord : publier par-dessus une panne
ajoute un certificat demande pour rien.

  cp suivicourier.caddy \
     ~/AppSuivi/sasi-ia/config/proxy/sites/

  cd ~/AppSuivi/sasi-ia/config/proxy

  docker compose exec caddy caddy reload \
    --config /etc/caddy/Caddyfile

RECHARGEMENT, jamais redemarrage : un reload ne coupe pas SASI, un
restart si. Si Caddy refuse le fichier, il le dit et garde l'ancienne
configuration — rien n'est casse : corrigez, rechargez.

Le certificat est demande au premier appel du domaine. Comptez une
dizaine de secondes, puis essayez DEPUIS UN TELEPHONE EN 4G, et non
depuis cette machine :

  https://suivicourier.the7ing.site

N'arretez la preproduction du Latitude qu'apres cet essai reussi.
RESTE

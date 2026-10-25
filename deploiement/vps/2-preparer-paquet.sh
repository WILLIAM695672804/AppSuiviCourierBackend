#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  A LANCER SUR LE POSTE DE TRAVAIL (le Latitude), pas sur le VPS.
#
#      bash backend/deploiement/vps/2-preparer-paquet.sh
#
#  Il assemble ~/paquet-vps-suivicourier/ : le code, le front DEJA BATI,
#  la base, les pieces et les fichiers d'installation. Il ne modifie rien
#  dans le projet et ne touche pas a la preproduction en cours — qui doit
#  rester debout jusqu'a ce que le VPS ait repondu depuis Internet.
#
#  Le front est rebati a chaque fois. C'est le seul moyen d'etre sur que
#  ce qui part est le code d'aujourd'hui : un `dist` laisse dans l'arbre
#  date de la derniere construction, et rien ne le dit.
# ---------------------------------------------------------------------
set -euo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VPS="$PROJET/backend/deploiement/vps"
PAQUET="$HOME/paquet-vps-suivicourier"
COMPOSE="docker compose -f compose.preprod.yaml -p suivi-preprod"

echo "Projet  : $PROJET"
echo "Paquet  : $PAQUET"
echo

# ---------------------------------------------------------------------
#  1. Le front, bati ici et non la-bas.
# ---------------------------------------------------------------------
echo "== 1/5  Construction du front =="
cd "$PROJET/frontend"
npm ci --silent
npm run build
bundle=$(grep -o 'index-[A-Za-z0-9_-]*\.js' dist/index.html | head -1)
echo "  bundle : $bundle"
echo

# ---------------------------------------------------------------------
#  2. La base et les pieces, depuis la preproduction en cours.
# ---------------------------------------------------------------------
echo "== 2/5  Export de la base =="
rm -rf "$PAQUET"
mkdir -p "$PAQUET"
cd "$PROJET/backend"

# `-Fc` et non `-Fp` : le format personnalise permet `--clean
# --if-exists` a la restauration, et pese le quart d'un fichier SQL.
$COMPOSE exec -T base pg_dump -U suivi -d suivi -Fc > "$PAQUET/base.dump"
echo "  base.dump : $(du -h "$PAQUET/base.dump" | cut -f1)"

$COMPOSE exec -T web tar -czf - -C /app/media . > "$PAQUET/pieces.tar.gz"
echo "  pieces.tar.gz : $(du -h "$PAQUET/pieces.tar.gz" | cut -f1)"
echo

# ---------------------------------------------------------------------
#  3. Le releve de controle. C'est lui qui prouve le transfert : une
#     restauration se verifie par comparaison, pas par absence d'erreur.
# ---------------------------------------------------------------------
echo "== 3/5  Releve de controle =="
$COMPOSE exec -T base psql -U suivi -d suivi -At -c "
  select 'activites '    || count(*) from activite
  union all select 'taches '       || count(*) from tache
  union all select 'indicateurs '  || count(*) from activite_indicateur
  union all select 'utilisateurs ' || count(*) from utilisateur
  union all select 'courriers '    || count(*) from courrier
  union all select 'evenements '   || count(*) from evenement
  union all select 'plans '        || count(*) from paa
  union all select 'versions '     || count(*) from paa_version
" > "$PAQUET/controle.txt"
echo "  bundle $bundle" >> "$PAQUET/controle.txt"
echo "  preleve le $(date '+%Y-%m-%d %H:%M')" >> "$PAQUET/controle.txt"
sed 's/^/  /' "$PAQUET/controle.txt"
echo

# ---------------------------------------------------------------------
#  4. Le code. Sans `.venv`, sans caches, et SANS AUCUNE CLE : une clef
#     privee TLS tramait dans `backend/` depuis un diagnostic du
#     8 septembre, et `tar` s'arretait dessus faute de droits.
# ---------------------------------------------------------------------
echo "== 4/5  Code et fichiers d'installation =="
mkdir -p "$PAQUET/backend" "$PAQUET/front"
rsync -a \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '.mypy_cache' \
    --exclude 'media' \
    --exclude 'staticfiles' \
    --exclude '.env*' \
    --exclude '*.key' \
    --exclude '*.crt' \
    --exclude '*.dump' \
    "$PROJET/backend/" "$PAQUET/backend/"

cp "$PROJET/frontend/nginx.conf"     "$PAQUET/front/nginx.conf"
cp "$VPS/front/Dockerfile.front"     "$PAQUET/front/Dockerfile.front"
rsync -a "$PROJET/frontend/dist/"    "$PAQUET/front/dist/"

cp "$VPS/compose.vps.yaml"     "$PAQUET/"
cp "$VPS/env.vps.modele"       "$PAQUET/"
cp "$VPS/suivicourier.caddy"   "$PAQUET/"
cp "$VPS/1-mesurer.sh"         "$PAQUET/"
cp "$VPS/3-installer.sh"       "$PAQUET/"
cp "$VPS/LISEZMOI.md"          "$PAQUET/"
chmod +x "$PAQUET"/*.sh

# Verification : aucun secret ne doit partir dans le paquet.
echo "  recherche de secrets residuels :"
if grep -rlE "POSTGRES_PASSWORD=.|SECRET_KEY=.{20}|TUNNEL_TOKEN=." \
    "$PAQUET/backend" 2>/dev/null | head -5; then
    echo "  ARRET : un fichier ci-dessus porte un secret."
    exit 1
fi
echo "  aucun"
echo

# ---------------------------------------------------------------------
#  5. Ce qu'il reste a taper. Volontairement court : le terminal du VPS
#     coupe les lignes longues et indente les collages.
# ---------------------------------------------------------------------
echo "== 5/5  Paquet pret =="
du -sh "$PAQUET"
echo
echo "Transferez-le, puis mesurez AVANT d'installer :"
echo
echo "  rsync -az --delete \\"
echo "    $PAQUET/ \\"
echo "    root@152.53.116.238:/root/suivicourier/"
echo
echo "  ssh root@152.53.116.238"
echo "  cd /root/suivicourier"
echo "  bash 1-mesurer.sh"
echo
echo "La preproduction locale n'a pas ete touchee. Ne l'arretez pas."

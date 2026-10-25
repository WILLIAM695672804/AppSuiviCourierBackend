#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  A LANCER SUR LE VPS, AVANT TOUT. Ne modifie rien, n'installe rien, ne
#  touche pas au frontal.
#
#      bash 1-mesurer.sh
#
#  Il repond a la seule question qui decide du dimensionnement : combien
#  de memoire la premiere application laisse-t-elle libre ? Les plafonds
#  de `compose.vps.yaml` somment a 2 Gio, posés sur l'hypothese que SASI
#  en consomme environ 2. Si le releve dit autre chose, les plafonds
#  s'ajustent avant le premier demarrage, et non apres le premier
#  `oom-kill`.
# ---------------------------------------------------------------------
set -u

echo "== Machine =="
echo "  architecture : $(uname -m)   (attendu : aarch64)"
echo "  noyau        : $(uname -r)"
echo "  distribution : $(. /etc/os-release && echo "$PRETTY_NAME")"
echo

echo "== Memoire =="
free -h
echo

echo "== Ce que la premiere application consomme =="
if docker ps -q >/dev/null 2>&1; then
    docker stats --no-stream \
        --format '  {{.Name}}  {{.MemUsage}}  {{.CPUPerc}}'
    echo
    total=$(docker stats --no-stream --format '{{.MemUsage}}' \
        | awk -F' / ' '{print $1}' \
        | sed 's/MiB//; s/GiB/*1024/' \
        | bc 2>/dev/null \
        | awk '{s+=$1} END {printf "%.0f", s}')
    echo "  somme mesuree : ${total:-?} Mio"
    echo "  budget de la plateforme : 2048 Mio de plafonds"
    echo "  si somme + 2048 depasse 3000, reduisez les plafonds."
else
    echo "  docker inaccessible pour cet utilisateur"
fi
echo

echo "== Le reseau du frontal =="
docker network inspect frontal --format \
    '  {{.Name}} ({{.Driver}}) — {{len .Containers}} conteneur(s) attache(s)' \
    2>/dev/null || echo "  ABSENT : le reseau « frontal » n'existe pas"
echo

echo "== L'alias est-il libre ? =="
if docker network inspect frontal 2>/dev/null \
    | grep -q "suivicourier-proxy"; then
    echo "  OCCUPE : « suivicourier-proxy » est deja pris sur ce reseau"
else
    echo "  libre : « suivicourier-proxy » n'est pas utilise"
fi
echo

echo "== Resolution du domaine =="
attendu="152.53.116.238"
for outil in dig host getent; do
    command -v "$outil" >/dev/null 2>&1 || continue
    case "$outil" in
        dig)    trouve=$(dig +short suivicourier.the7ing.site A | tail -1) ;;
        host)   trouve=$(host -t A suivicourier.the7ing.site 2>/dev/null \
                    | awk '/has address/ {print $NF}' | tail -1) ;;
        getent) trouve=$(getent ahostsv4 suivicourier.the7ing.site \
                    | awk '{print $1}' | head -1) ;;
    esac
    break
done
if [ "${trouve:-}" = "$attendu" ]; then
    echo "  OK : suivicourier.the7ing.site -> $trouve"
else
    echo "  ECART : attendu $attendu, obtenu « ${trouve:-rien} »"
    echo "  N'ALLEZ PAS PLUS LOIN : Caddy demanderait un certificat qui"
    echo "  echouerait, et Let's Encrypt compte les echecs."
fi
echo

echo "== Disque =="
df -h / | tail -1 | awk '{print "  / : "$4" libres sur "$2}'
echo "  l'image applicative pese environ 1,1 Gio (LibreOffice compris)"
echo

echo "== Echange =="
swapon --show 2>/dev/null || echo "  aucun fichier d'echange actif"
echo

echo "== Pare-feu =="
ufw status 2>/dev/null | head -8 || echo "  ufw non interrogeable sans privileges"
echo

echo "Rien n'a ete modifie."

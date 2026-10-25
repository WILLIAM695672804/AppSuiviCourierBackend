#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  L'application repond-elle, et tout tourne-t-il ?
#
#      ./deploiement/etat.sh
#
#  A lancer apres toute interruption — veille, redemarrage, coupure de
#  courant ou de connexion — et une fois par jour sans raison
#  particuliere. Il verifie ce qu'un coup d'oeil au navigateur ne dit
#  pas : notamment que l'horloge tourne, dont l'arret est la panne la
#  plus discrete du systeme.
# ---------------------------------------------------------------------
set -uo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
# Une fonction, et non une variable : le chemin du projet contient des
# espaces, et une variable developpee sans guillemets couperait la commande
# en deux. Le symptome est trompeur — chaque service parait « absent »
# alors que tout tourne.
compose() { docker compose -f "${RACINE}/compose.preprod.yaml" -p suivi-preprod "$@"; }

# `grep -q` ferme le tuyau des qu'il a trouve ; la commande en amont meurt
# d'un SIGPIPE, et `pipefail` propage cet echec. Le test conclut alors
# « absent » sur une chaine qui a pourtant trouve. On capture d'abord, on
# cherche ensuite — jamais `… | grep -q` sous `pipefail`.
contient() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# Sans acces au demon, `docker compose ps` ne rend rien : sans cette
# distinction le script annonce six services arretes alors qu'ils tournent.
# Un diagnostic faux coute plus cher qu'un diagnostic absent.
if docker info >/dev/null 2>&1; then
    DOCKER_LISIBLE=1
else
    DOCKER_LISIBLE=0
fi
ADRESSE="$(grep -m1 '^CSRF_TRUSTED_ORIGINS=' "${RACINE}/.env.preprod" | cut -d= -f2- | cut -d, -f1)"
souci=0

dire() { printf '  %-10s %s\n' "$1" "$2"; }

echo
echo "── Services ──"
if [ "$DOCKER_LISIBLE" -eq 0 ]; then
    dire "INCONNU" "demon Docker injoignable — relancez : sudo $0"
else
    tableau="$(compose ps --format '{{.Service}} {{.State}}' 2>/dev/null)"
    for s in base file web ouvrier horloge proxy; do
        etat="$(printf '%s\n' "$tableau" | awk -v s="$s" '$1==s{print $2}')"
        [ "$s" = "horloge" ] && ETAT_HORLOGE="${etat:-absent}"
        if [ "${etat:-absent}" = "running" ]; then
            dire "OK" "$s"
        else
            dire "ARRETE" "$s (${etat:-absent})"
            souci=$((souci + 1))
        fi
    done
fi

echo
echo "── L'horloge ──"
# Sans `beat`, les ecrans repondent et seul le temps cesse de s'ecouler.
# Aucun symptome visible : c'est pourquoi elle se verifie a part.
if [ "$DOCKER_LISIBLE" -eq 0 ]; then
    dire "INCONNU" "demon Docker injoignable — relancez : sudo $0"
else
    traces="$(compose logs horloge --since 24h 2>/dev/null)"
    # L'etat du conteneur prime sur les traces : un service qui redemarre en
    # boucle ecrit « beat: Starting » a chaque tentative, et le seul examen
    # des journaux le declare donc vivant. Il l'a fait.
    if [ "${ETAT_HORLOGE:-absent}" != "running" ]; then
        dire "ARRETE" "conteneur ${ETAT_HORLOGE:-absent} — aucun traitement planifie ne part"
        if contient "$traces" "Permission denied"; then
            dire "" "beat n'ecrit pas son fichier d'etat : voir docs/pieges.md"
        fi
        souci=$((souci + 1))
    elif contient "$traces" "beat: Starting" || contient "$traces" "Scheduler:"; then
        dire "OK" "l'ordonnanceur a donne signe de vie"
    else
        dire "MUET" "aucune trace depuis 24 h — les traitements de nuit ne passent plus"
        souci=$((souci + 1))
    fi
fi

echo
echo "── Le tunnel ──"
funnel="$(tailscale funnel status 2>/dev/null)"
if contient "$funnel" "Funnel on"; then
    dire "OK" "$(printf '%s\n' "$funnel" | grep -m1 'https://' | sed 's/^[^h]*//')"
else
    dire "COUPE" "relancer : sudo tailscale funnel --bg 8080"
    souci=$((souci + 1))
fi

echo
echo "── Depuis Internet ──"
# Le nom `…ts.net` resout, sur cette machine, vers l'adresse du tailnet :
# un `curl` lance ici emprunte le reseau interne et non le Funnel. Il a
# repondu 200 des jours durant pendant que le site etait injoignable pour
# tout le monde. La seule question qui compte est donc : le DNS **public**
# connait-il ce nom ? Tailscale ne l'y publie qu'une fois le certificat
# emis.
hote="${ADRESSE#https://}"; hote="${hote%%/*}"
# `grep` sur la forme complete d'une adresse : `dig` glisse parfois un
# avertissement sur la sortie standard, et un motif trop large le capture.
ip_publique="$(dig +short A "$hote" @1.1.1.1 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)"
if [ -z "$ip_publique" ]; then
    dire "INVISIBLE" "${hote} inconnu du DNS public — personne hors du tailnet n'entre"
    dire "" "sudo tailscale cert ${hote}   (HTTPS actif dans la console Tailscale)"
    souci=$((souci + 1))
else
    dire "PUBLIE" "${hote} → ${ip_publique}"
fi
# `--resolve` force le passage par l'adresse publique. Sans lui, le nom
# resout ici vers le tailnet et la mesure porte sur le reseau interne.
for chemin in / /api/docs; do
    code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' \
        ${ip_publique:+--resolve "${hote}:443:${ip_publique}"} \
        "${ADRESSE}${chemin}" 2>/dev/null)"
    if [ "$code" = "200" ]; then
        dire "OK" "${chemin} → 200"
    else
        dire "ECHEC" "${chemin} → ${code:-injoignable}"
        souci=$((souci + 1))
    fi
done

echo
echo "── La derniere sauvegarde ──"
derniere="$(ls -t "${HOME}"/sauvegardes-suivi/base-*.dump 2>/dev/null | head -1)"
if [ -n "$derniere" ]; then
    jours=$(( ( $(date +%s) - $(stat -c %Y "$derniere") ) / 86400 ))
    if [ "$jours" -le 1 ]; then
        dire "OK" "$(basename "$derniere")"
    else
        dire "VIEILLE" "$jours jours — la tache cron ne tourne pas"
        souci=$((souci + 1))
    fi
else
    dire "AUCUNE" "poser la ligne de cron (voir preproduction.md)"
    souci=$((souci + 1))
fi

echo
if [ "$souci" -eq 0 ]; then
    echo "Tout va bien."
else
    echo "${souci} point(s) a regarder. Pour tout relancer :"
    echo "   cd '${RACINE}' && docker compose -f compose.preprod.yaml -p suivi-preprod up -d"
    echo "   sudo tailscale funnel --bg 8080"
fi
echo

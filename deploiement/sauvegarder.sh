#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  Sauvegarde de la preproduction : la base, les pieces jointes ET la
#  documentation qui n'est dans aucun depot Git.
#
#  Les deux ensemble, toujours. Les binaires ne sont pas en base : une
#  sauvegarde de base seule restaure des courriers dont toutes les pieces
#  ont disparu — c'est-a-dire rien.
#
#  Usage :  ./deploiement/sauvegarder.sh [repertoire]
#  Defaut :  ~/sauvegardes-suivi
#
#  A poser dans une tache `cron` de l'utilisateur, une fois par nuit :
#      30 23 * * *  /chemin/backend/deploiement/sauvegarder.sh
#
#  ATTENTION. Une sauvegarde qui reste sur la machine qu'elle protege ne
#  protege de rien : elle disparait avec le disque. Recopiez le
#  repertoire ailleurs — disque externe, autre machine. Et une
#  restauration jamais essayee n'est pas une sauvegarde.
# ---------------------------------------------------------------------
set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
# Une fonction, et non une variable : le chemin du projet contient des
# espaces, et une variable developpee sans guillemets coupe la commande en
# deux — « unknown docker command: "compose de" ». Voir docs/pieges.md.
compose() { docker compose -f "${RACINE}/compose.preprod.yaml" "$@"; }

# Le nom d'utilisateur et la base viennent du meme fichier que
# l'application. Les redemander ici, c'est se tromper le jour ou l'un des
# deux change.
set -a
# shellcheck disable=SC1091
. "${RACINE}/.env.preprod"
set +a
# Sous `sudo`, `HOME` vaut /root : la sauvegarde atterrirait la, invisible
# pour `etat.sh` qui la cherche chez l'utilisateur, et perdue le jour d'une
# reinstallation. On resout le foyer de l'utilisateur reel.
if [ -n "${SUDO_USER:-}" ]; then
    FOYER="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
else
    FOYER="${HOME}"
fi
DESTINATION="${1:-${FOYER}/sauvegardes-suivi}"
JOUR="$(date +%F-%H%M)"
RETENTION_JOURS=30

mkdir -p "${DESTINATION}"

echo "→ base de donnees"
# Format `custom` : compresse, et surtout restaurable table par table avec
# `pg_restore`. Un dump SQL brut ne se restaure qu'en entier.
compose exec -T base pg_dump \
    --format=custom --no-owner \
    --username "${POSTGRES_USER}" \
    "${POSTGRES_DB}" \
    > "${DESTINATION}/base-${JOUR}.dump"

echo "→ pieces jointes"
# Depuis le conteneur : le volume Docker n'est pas lisible directement par
# l'utilisateur, et un `sudo` dans une tache cron nocturne est un piege.
compose exec -T web tar -cf - -C /app/media . \
    | gzip > "${DESTINATION}/pieces-${JOUR}.tar.gz"

echo "→ documentation hors depot"
# ---------------------------------------------------------------------
#  TROISIEME VOLET, ajoute le 25 octobre 2026.
#
#  Les deux depots Git couvrent `backend/` et `frontend/`. `docs/`,
#  `diagrammes/`, `CLAUDE.md` et `README.md` restent volontairement hors
#  Git (arbitrage de l'utilisateur) : ils ne sont donc versionnes
#  nulle part, et le journal de bord, `docs/pieges.md` et
#  `docs/questions-ouvertes.md` sont la memoire du projet — ce que le
#  code ne dit pas et que personne ne retrouvera.
#
#  Sans ce volet, une panne du disque emporterait cette memoire alors
#  que le code, lui, survivrait sur GitHub.
# ---------------------------------------------------------------------
PROJET="$(cd "${RACINE}/.." && pwd)"
tar -czf "${DESTINATION}/documentation-${JOUR}.tar.gz" \
    -C "${PROJET}" \
    docs diagrammes CLAUDE.md README.md 2>/dev/null \
    || echo "  (au moins un element est absent — archive partielle)"

# Ecrits par root sous `sudo`, les fichiers seraient illisibles pour la
# tache cron de l'utilisateur — et pour la recopie hors machine.
if [ -n "${SUDO_USER:-}" ]; then
    chown -R "${SUDO_USER}:${SUDO_USER}" "${DESTINATION}"
fi

echo "→ rotation (au-dela de ${RETENTION_JOURS} jours)"
find "${DESTINATION}" -name 'base-*.dump' -mtime "+${RETENTION_JOURS}" -delete
find "${DESTINATION}" -name 'pieces-*.tar.gz' -mtime "+${RETENTION_JOURS}" -delete
find "${DESTINATION}" -name 'documentation-*.tar.gz' -mtime "+${RETENTION_JOURS}" -delete

echo
echo "Sauvegarde du ${JOUR} :"
ls -lh "${DESTINATION}"/*-"${JOUR}".* | awk '{print "   " $9 "  " $5}'
echo
echo "RESTAURATION (a essayer avant d'en avoir besoin) :"
C="docker compose -f '${RACINE}/compose.preprod.yaml'"
echo "   ${C} exec -T base psql -U suivi -c 'DROP DATABASE suivi'"
echo "   ${C} exec -T base createdb -U suivi suivi"
echo "   ${C} exec -T base pg_restore -U suivi -d suivi < base-${JOUR}.dump"
echo "   gunzip -c pieces-${JOUR}.tar.gz | ${C} exec -T web tar -xf - -C /app/media"

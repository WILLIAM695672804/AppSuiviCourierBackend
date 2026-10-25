#!/usr/bin/env bash
#
# Prepare le paquet de transfert vers la machine qui fera office de serveur.
#
#     ./deploiement/exporter.sh [destination]
#
# Produit un repertoire autonome : le code, les secrets, la base et les
# pieces. Tout ce qui ne s'y trouve pas se reconstruit sur la cible (images
# Docker, volume de l'ordonnanceur, dependances).
#
# Ce script **ne touche a rien** : il lit. Le poste actuel continue de servir
# pendant et apres l'export.
set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
PROJET="$(cd "${RACINE}/.." && pwd)"

compose() { docker compose -f "${RACINE}/compose.preprod.yaml" -p suivi-preprod "$@"; }

# `sudo` deplace HOME vers /root — le foyer se resout par SUDO_USER.
if [ -n "${SUDO_USER:-}" ]; then
    FOYER="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
else
    FOYER="${HOME}"
fi

JOUR="$(date +%F-%H%M)"
DESTINATION="${1:-${FOYER}/transfert-suivi-${JOUR}}"
mkdir -p "${DESTINATION}"

echo "→ paquet de transfert : ${DESTINATION}"
echo

# ---------------------------------------------------------------------
#  1. La base
#
#  Format `custom` (-Fc) et non SQL : `pg_restore` sait alors restaurer
#  dans un ordre qu'il calcule, ce qui evite les echecs de dependance
#  entre declencheurs, vues et contraintes de ce schema.
# ---------------------------------------------------------------------
echo "→ base de donnees"
compose exec -T base pg_dump -U suivi -Fc suivi > "${DESTINATION}/base.dump"
if ! head -c 5 "${DESTINATION}/base.dump" | grep -q PGDMP; then
    echo "   ECHEC : le dump ne porte pas l'entete PGDMP." >&2
    exit 1
fi
echo "   $(du -h "${DESTINATION}/base.dump" | cut -f1)"

# ---------------------------------------------------------------------
#  2. Les pieces jointes
#
#  Le volume, pas le repertoire de l'hote : `pieces` est un volume nomme,
#  il n'existe nulle part dans l'arborescence du projet.
# ---------------------------------------------------------------------
echo "→ pieces jointes"
compose exec -T web tar -cf - -C /app/media . | gzip > "${DESTINATION}/pieces.tar.gz"
echo "   $(du -h "${DESTINATION}/pieces.tar.gz" | cut -f1)"

# ---------------------------------------------------------------------
#  3. Le code et les secrets
#
#  Les `*.key` et `*.crt` sont exclus : une cle privee ne voyage pas dans un
#  paquet de code, et le Funnel de la machine cible obtiendra la sienne. Ceux
#  qui tranent a la racine du backend viennent d'un `tailscale cert` de
#  diagnostic du 8 septembre 2026 ; ils n'ont jamais servi.
#
#  `.env.preprod` porte les mots de passe : il est copie **avec** le reste,
#  et c'est la raison pour laquelle ce paquet ne se transporte pas sur une
#  cle qu'on prete. Exclus : le virtualenv, les dependances npm et les
#  caches, qui se reconstruisent et pesent dix fois le reste.
# ---------------------------------------------------------------------
echo "→ code et configuration"
tar -czf "${DESTINATION}/projet.tar.gz" \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.pyc' \
    --exclude='*.key' \
    --exclude='*.crt' \
    -C "$(dirname "${PROJET}")" "$(basename "${PROJET}")"
echo "   $(du -h "${DESTINATION}/projet.tar.gz" | cut -f1)"

# ---------------------------------------------------------------------
#  4. Le releve de ce qui doit se retrouver a l'arrivee
#
#  Un transfert se verifie par comparaison, pas par confiance : ces
#  chiffres sont ceux que la cible doit afficher.
# ---------------------------------------------------------------------
echo "→ releve de controle"
compose exec -T base psql -U suivi -d suivi -At -F '|' -c "
select 'utilisateurs', count(*) from utilisateur
union all select 'activites', count(*) from activite
union all select 'taches', count(*) from tache where invalide_le is null
union all select 'courriers', count(*) from courrier
union all select 'evenements', count(*) from evenement
union all select 'plans', count(*) from paa
union all select 'versions de plan', count(*) from paa_version
order by 1;" > "${DESTINATION}/controle.txt"
cat "${DESTINATION}/controle.txt" | sed 's/^/   /'

if [ -n "${SUDO_USER:-}" ]; then
    chown -R "${SUDO_USER}:${SUDO_USER}" "${DESTINATION}"
fi

echo
echo "Paquet complet : $(du -sh "${DESTINATION}" | cut -f1)"
echo
echo "ATTENTION : ce paquet contient les mots de passe de la base et de"
echo "l'application. Il ne se laisse pas sur une cle que l'on prete."
echo
echo "Suite de la procedure : backend/docs/exploitation/bascule-vers-un-serveur.md"

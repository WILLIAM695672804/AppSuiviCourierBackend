#!/usr/bin/env bash
# ---------------------------------------------------------------------
#  Met un des deux depots sous Git et le pousse sur GitHub, une premiere
#  fois.
#
#      bash backend/deploiement/premier-depot.sh backend
#      bash backend/deploiement/premier-depot.sh frontend "Message"
#
#  Le message du commit est facultatif : a defaut, « Versement initial »
#  sur un depot vide, « Mise a jour du depot » sur un depot qui a deja
#  un historique.
#
#  LES DEUX DEPOTS SONT PUBLICS. Le script verifie donc, AVANT tout
#  `commit`, qu'aucun secret n'est entre dans l'index — et s'arrete si
#  c'en est le cas. Un secret pousse reste dans l'historique apres sa
#  suppression : la seule reparation est de le revoquer.
#
#  Relancable : si le depot est deja initialise, il ne refait que le
#  controle et s'arrete.
# ---------------------------------------------------------------------
set -euo pipefail

PROJET="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

case "${1:-}" in
    backend)
        COIN="$PROJET/backend"
        DISTANT="https://github.com/WILLIAM695672804/AppSuiviCourierBackend.git"
        ;;
    frontend)
        COIN="$PROJET/frontend"
        DISTANT="https://github.com/WILLIAM695672804/AppSuiviCourier.git"
        ;;
    *)
        echo "Usage : premier-depot.sh backend|frontend"
        exit 2
        ;;
esac

cd "$COIN"
echo "Depot  : $COIN"
echo "Distant: $DISTANT"
echo

arret() { echo; echo "ARRET : $1"; exit 1; }

# ---------------------------------------------------------------------
#  1. Initialisation. `main` et non `master` : c'est ce que GitHub
#     attend, et une branche mal nommee se corrige mal a distance.
# ---------------------------------------------------------------------
# `[ -d .git ]` ne suffit pas : un `.git` vide, vestige d'un `git init`
# avorte, existait dans `backend/` depuis le 14 aout. Le test par
# repertoire le prenait pour un depot, et tout ce qui suivait echouait
# sur « ni ceci ni aucun de ses repertoires parents n'est un depot ».
if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "== Depot deja initialise =="
else
    echo "== 1/4  Initialisation =="
    git init -q -b main
    echo "  fait"
fi
echo

# ---------------------------------------------------------------------
#  2. L'index. `add -A` respecte `.gitignore` ; le controle qui suit
#     verifie qu'il l'a bien respecte, parce qu'un motif absent ne
#     produit aucun message.
# ---------------------------------------------------------------------
echo "== 2/4  Preparation de l'index =="
git add -A
echo "  $(git diff --cached --name-only | wc -l) fichier(s) dans l'index"
echo

# ---------------------------------------------------------------------
#  3. LE CONTROLE. C'est la seule raison d'etre de ce script.
# ---------------------------------------------------------------------
echo "== 3/4  Controle des secrets =="

# Les noms d'abord. Un `.env.example` est legitime, un `.env.preprod`
# ne l'est pas, et les deux se ressemblent.
suspects=$(git diff --cached --name-only \
    | grep -E '(^|/)\.env($|\.)|\.(key|crt|pem|p12|pfx|dump)$' \
    | grep -vE '\.example$' || true)
if [ -n "$suspects" ]; then
    echo "$suspects" | sed 's|^|  |'
    arret "les fichiers ci-dessus ne doivent pas etre publies."
fi
echo "  noms de fichiers : rien de suspect"

# Le contenu ensuite. Les valeurs reelles connues de cet environnement
# sont cherchees telles quelles : c'est le controle qui attrape un
# secret recopie dans un commentaire ou un document.
# Les motifs exigent une valeur qui RESSEMBLE a un secret, et non un
# nom de variable. Premiere redaction, trop large, attrapait trois faux
# positifs : `POSTGRES_PASSWORD=CHANGEZ_MOI` d'un modele, les motifs de
# ce script lui-meme, et `etat_recouvrements` — ou `at_` suivait un `t`.
# D'ou la frontiere de mot devant `at_`, et des classes de caracteres
# qui excluent `$`, `\` et `.`, par lesquels commence toute substitution.
motifs='SECRET_KEY=[A-Za-z0-9_+/=-]{25,}'
motifs="$motifs|POSTGRES_PASSWORD=[A-Za-z0-9][A-Za-z0-9!@#%^*_+-]{7,}"
motifs="$motifs|TUNNEL_TOKEN=[A-Za-z0-9]{10,}"
motifs="$motifs|\bat_[A-Za-z0-9]{12,}"
motifs="$motifs|BEGIN (RSA |EC )?PRIVATE KEY"
trouve=$(git diff --cached -U0 \
    | grep -E '^\+' \
    | grep -Ei "$motifs" \
    | grep -v '^--$' \
    | grep -vE 'A_ENGENDRER|CHANGEZ_MOI|CHANGE_ME|changez|modele|exemple|example|placeholder|developpement-uniquement' || true)
if [ -n "$trouve" ]; then
    echo "$trouve" | head -10 | sed 's|^|  |'
    arret "une valeur sensible figure dans le contenu ajoute."
fi
echo "  contenu : aucune valeur sensible"

# Le poids, enfin. Un depot qui part a 100 Mo porte autre chose que du
# code — une archive, un dump, un `node_modules` oublie.
# `set -o pipefail` est actif : sans le repli, un seul fichier absent de
# l'index ferait echouer toute la chaine et arreter le script ici.
poids=$(git diff --cached --name-only -z \
    | xargs -0 du -ck 2>/dev/null | tail -1 | cut -f1 || true)
poids=${poids:-0}
echo "  poids de l'index : $((poids / 1024)) Mio"
if [ "$poids" -gt 102400 ]; then
    arret "plus de 100 Mio : verifiez ce qui est entre dans l'index."
fi
echo

# ---------------------------------------------------------------------
#  4. Le commit et la poussee. GitHub demandera un jeton d'acces
#     personnel, pas le mot de passe du compte : le mot de passe est
#     refuse depuis 2021.
# ---------------------------------------------------------------------
echo "== 4/4  Commit et poussee =="
# Un depot peut exister et n'avoir rien recu depuis des mois : celui du
# front datait du 25 aout avec 74 fichiers modifies en attente. Le test
# porte donc sur l'ecart entre l'index et HEAD, et non sur l'existence
# d'un commit.
if git diff --cached --quiet 2>/dev/null; then
    echo "  rien a commiter : l'index est identique a HEAD"
else
    if git rev-parse HEAD >/dev/null 2>&1; then
        defaut="Mise a jour du depot"
    else
        defaut="Versement initial de la plateforme de suivi du PAD"
    fi
    git -c user.name="William Fondjo" \
        -c user.email="w7722879@gmail.com" \
        commit -q -m "${2:-$defaut}"
    echo "  commit cree : $(git log -1 --format='%h %s')"
fi

git remote get-url origin >/dev/null 2>&1 \
    || git remote add origin "$DISTANT"
echo "  distant : $(git remote get-url origin)"
echo
echo "Il reste a pousser, et c'est a vous de le faire — GitHub demandera"
echo "un jeton d'acces personnel :"
echo
echo "  cd $COIN"
echo "  git push -u origin main"

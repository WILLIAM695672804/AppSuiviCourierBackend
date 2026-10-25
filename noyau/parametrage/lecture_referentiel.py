"""
Ce que les referentiels de saisie rendent — natures, mentions, correspondants.

Distinct de `lecture.py`, qui construit l'ecran de parametrage. La difference
n'est pas cosmetique : cet ecran-la sert un administrateur, et rend l'usage, les
doublons presumes et les regles en attente d'arbitrage ; ces trois lectures-ci
servent un agent qui remplit un formulaire, et ne rendent que de quoi choisir.

**Aucune ne restreint par perimetre**, et la raison n'est pas la meme que pour
l'organigramme (ADR 007) : ces tables n'ont pas de structure proprietaire. Une
nature n'appartient a personne, une mention non plus, et un correspondant est une
adresse deja imprimee sur l'enveloppe que l'agent tient en main. Il n'y a rien a
filtrer — ce qui n'est pas la meme chose que renoncer a filtrer.
"""

import re

from django.db import connection

from noyau.parametrage.lecture import CATEGORIES_CORRESPONDANT
from noyau.parametrage.modeles import Correspondant, MentionType, Nature

#: Combien d'entrees du carnet d'adresses une recherche peut rendre au plus.
#: Une borne cote serveur et non seulement cote client : `limite` arrive de
#: l'URL, et un appelant qui demande dix mille lignes ne doit pas les obtenir.
PLAFOND_CORRESPONDANTS = 50

#: En deca, la recherche ne rend rien. Meme seuil que le front (`enabled:
#: recherche.trim().length >= 2`) : le tenir des deux cotes evite qu'une premiere
#: frappe ramene le carnet entier si un autre client vient a appeler la route.
MINIMUM_CARACTERES = 2

#: Ressemblance minimale entre la frappe et le mot le plus proche du nom.
#:
#: **Ecrit ici et non laisse a l'operateur `<%`**, qui lit le seuil dans
#: `pg_trgm.word_similarity_threshold` — un reglage de session, que personne ne
#: pose et qu'un `ALTER DATABASE ... SET` changerait sans qu'aucun code ne le
#: dise. La recherche du carnet ne doit pas dependre d'un parametre invisible.
#:
#: 0,55 et non le defaut 0,60 : « minstere » ressemble a « ministere des
#: transports » a 0,58, et c'est exactement la faute de frappe que ce filet
#: existe pour rattraper. Le seuil reste au-dessus de 0,50, ou « douanes »
#: commencerait a ramener « Douala International Terminal » — mesure sur le
#: carnet de demonstration, pas devinee.
SEUIL_SIMILARITE = 0.55


def natures() -> list[dict]:
    """
    Les natures de courrier en vigueur.

    `actif` **et** `invalide_le` : une nature retiree du formulaire reste lisible
    sur les courriers de l'an dernier (principe 2 de `modeles.py`), et les deux
    colonnes ne disent pas la meme chose — `actif` retire du choix, `invalide_le`
    retire du referentiel.
    """
    return [
        {
            "id": nature.pk,
            "libelle": nature.libelle,
            "delaiParDefaut": nature.delai_defaut_jours,
        }
        for nature in Nature.objects.filter(invalide_le__isnull=True, actif=True)
    ]


def mentions() -> list[dict]:
    """Les mentions de cotation en vigueur, dans l'ordre d'affichage administre."""
    return [
        {"id": mention.pk, "libelle": mention.libelle}
        for mention in MentionType.objects.filter(invalide_le__isnull=True, actif=True)
    ]


#: Les mots de la frappe, ponctuation et soulignes exclus. `[^\W_]+` garde
#: les lettres accentuees, que `\w` inclut deja en Unicode.
_MOTS = re.compile(r"[^\W_]+", re.UNICODE)


def _requete_par_prefixe(terme: str) -> str | None:
    """
    Compose `mot:* & mot:*` a partir de la frappe.

    **Pourquoi decouper soi-meme plutot que passer le terme brut.** Ce texte est
    du langage `tsquery` : un `&`, un `|` ou une parenthese frappes par l'agent
    y seraient des operateurs, et une parenthese non fermee ferait repondre 500 a
    une recherche. Ne garder que des suites de lettres et de chiffres retire au
    passage tout ce qui pourrait etre lu comme un operateur.

    Rend `None` quand la frappe ne contient aucun mot — l'appelant repond alors
    une liste vide plutot qu'une requete que PostgreSQL refuserait.
    """
    mots = _MOTS.findall(terme)
    if not mots:
        return None

    return " & ".join(f"{mot}:*" for mot in mots)


def correspondants(recherche: str, limite: int) -> list[dict]:
    """
    Le carnet d'adresses, cherche par nom, par sigle ou par a-peu-pres.

    **Trois voies, une seule requete.** Le referentiel n'existe que pour eviter
    qu'un meme ministere finisse ecrit de six manieres, et il n'y parvient que si
    l'agent **retrouve** l'entree. Une entree qu'on ne retrouve pas est une
    entree qu'on recree.

     1. **Plein texte par prefixe** — « minis » trouve « Ministere ». C'est la
        voie la plus precise, et celle qui pese le plus au classement.
     2. **Sous-chaine** — « ndjamena » trouve « N'Djamena », que le plein texte
        coupe a l'apostrophe.
     3. **Similarite trigramme par mot** — « minstere » trouve « Ministere ».
        C'est le filet de la faute de frappe, et le seul des trois qui ne demande
        pas que la frappe soit un debut correct. Son seuil est `SEUIL_SIMILARITE`,
        pose ici et non pris sur le reglage de session de `pg_trgm`.

    La similarite est celle du **mot** (`<%`) et non de la ligne entiere (`%`) :
    « minstere » compare a « ministere des transports douala » donne une
    ressemblance faible, parce que la cible est longue — la ligne noierait la
    faute de frappe sous les mots qui ne la concernent pas.

    **En SQL direct et non par l'ORM.** La requete melange `tsquery`,
    `similarity()` et une laterale sur `courrier` que `noyau` n'a pas le droit
    d'importer (la ligne de partage d'`INSTALLED_APPS`). L'ecrire en Django
    aurait demande trois annotations et un `RawSQL` au milieu, c'est-a-dire du
    SQL deguise.

    **Le classement compte autant que le filtre.** A pertinence voisine, l'entree
    que l'agent cherche est presque toujours celle dont il a deja recu vingt
    courriers. L'ordre alphabetique, lui, ne dit rien de personne.
    """
    terme = recherche.strip()
    if len(terme) < MINIMUM_CARACTERES:
        return []

    prefixes = _requete_par_prefixe(terme)
    if prefixes is None:
        return []

    plafond = max(1, min(limite, PLAFOND_CORRESPONDANTS))

    with connection.cursor() as curseur:
        curseur.execute(_REQUETE, [terme, prefixes, SEUIL_SIMILARITE, plafond])
        lignes = curseur.fetchall()

    return [
        {
            "id": identifiant,
            "libelle": libelle,
            "sigle": sigle or None,
            "categorie": CATEGORIES_CORRESPONDANT.get(type_, type_),
            "initiales": initiales(libelle),
            "nombreCourriers": nombre,
            "dernierCourrier": dernier,
        }
        for identifiant, libelle, sigle, type_, nombre, dernier in lignes
    ]


#: La requete de recherche. Les `%%` sont des `%` : le curseur de Django lit
#: `%s` comme un parametre, et `%` est donc a doubler — y compris l'operateur
#: de similarite de `pg_trgm`.
_REQUETE = """
WITH frappe AS (SELECT texte_recherche(%s) AS mots, to_tsquery('fr_unaccent', %s) AS question)
SELECT c.id,
       coalesce(c.raison_sociale, btrim(coalesce(c.nom, '') || ' ' || coalesce(c.prenom, ''))),
       c.sigle,
       c.type,
       coalesce(u.nombre, 0),
       u.dernier
  FROM correspondant c
  LEFT JOIN LATERAL (
      SELECT count(*) AS nombre, max(date_reception) AS dernier
        FROM courrier
       WHERE expediteur_id = c.id AND invalide_le IS NULL
  ) u ON TRUE
  CROSS JOIN frappe f
 WHERE c.invalide_le IS NULL
   AND c.actif
   AND (
        c.recherche @@ f.question
     OR texte_recherche(c.cible_recherche) LIKE '%%' || f.mots || '%%'
     OR word_similarity(f.mots, texte_recherche(c.cible_recherche)) >= %s
   )
 ORDER BY
       -- Le plein texte pese le plus : il dit que la frappe est un debut
       -- correct, la ou la similarite ne dit qu'une ressemblance.
       coalesce(ts_rank_cd(c.recherche, f.question), 0) * 3
     + word_similarity(f.mots, texte_recherche(c.cible_recherche))
     -- Ce qui commence par la frappe passe devant ce qui la contient au
     -- milieu : « Port » doit rendre « Port Autonome » avant « Syndicat du
     -- Port ».
     + CASE WHEN texte_recherche(c.cible_recherche) LIKE f.mots || '%%' THEN 1 ELSE 0 END
       DESC,
       coalesce(u.nombre, 0) DESC,
       coalesce(c.raison_sociale, c.nom)
 LIMIT %s
"""


def correspondant(ligne: Correspondant) -> dict:
    """
    Une entree seule, dans la forme que rend la recherche.

    Sert la creation depuis l'ecran d'enregistrement : le selecteur affiche
    l'entree qu'il vient de creer sans second aller-retour. Ses compteurs sont a
    zero — un correspondant tout juste inscrit n'a envoye aucun courrier — et ce
    n'est pas une valeur par defaut posee faute de mieux : c'est la verite.
    """
    return _ligne_correspondant(ligne, 0, None)


def _ligne_correspondant(ligne: Correspondant, nombre: int, dernier: object) -> dict:
    return {
        "id": ligne.pk,
        "libelle": ligne.designation,
        "sigle": ligne.sigle or None,
        "categorie": CATEGORIES_CORRESPONDANT.get(ligne.type, ligne.type),
        "initiales": initiales(ligne.designation),
        "nombreCourriers": nombre,
        "dernierCourrier": dernier,
    }


def initiales(designation: str) -> str:
    """
    Deux lettres au plus, pour la pastille du selecteur.

    Calculees et non stockees : une initiale enregistree en base finirait par
    contredire le nom le jour ou celui-ci est corrige. Les mots vides sont
    ecartes — « Direction générale des impôts » donne « DG » et non « DD ».
    """
    vides = {"de", "des", "du", "la", "le", "les", "et", "d", "l", "au", "aux"}
    mots = [mot for mot in designation.split() if mot.lower().strip(".'") not in vides]
    lettres = [mot[0].upper() for mot in mots if mot[:1].isalpha()]
    return "".join(lettres[:2]) or "?"


def _courriers_par_correspondant(identifiants: list[int]) -> dict[int, tuple[int, object]]:
    """
    Combien de courriers chaque correspondant a envoyes, et quand pour la
    derniere fois.

    **En SQL direct et non par l'ORM.** `noyau` n'importe aucun pilier — c'est la
    ligne de partage posee dans `INSTALLED_APPS` — et le modele `Courrier` vit
    dans l'application `courrier`. Meme forme, et meme raison, que
    `_courriers_en_cours` dans l'habilitation.

    Rien ici ne restreint par perimetre, et il n'y a rien a restreindre : la
    requete rend deux nombres et une date par correspondant. Aucun numero, aucun
    objet, aucune structure de courrier n'en sort. Un compte a zero est exact
    tant qu'aucun courrier n'est enregistre.
    """
    if not identifiants:
        return {}

    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT expediteur_id, count(*), max(date_reception)
              FROM courrier
             WHERE expediteur_id = ANY(%s) AND invalide_le IS NULL
             GROUP BY expediteur_id
            """,
            [identifiants],
        )
        return {ligne[0]: (ligne[1], ligne[2]) for ligne in curseur.fetchall()}
